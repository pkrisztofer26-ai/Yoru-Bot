from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import random
import re

from app import activity_config as cfg
from app.database import Database
from app.services.server_settings import ServerSettingsService


@dataclass(frozen=True)
class ActivityProfile:
    total_xp: int
    chat_xp: int
    voice_xp: int
    message_count: int
    voice_seconds: int
    level: int
    last_chat_xp_at: str | None = None
    last_message_at: str | None = None
    last_message_hash: str | None = None


@dataclass(frozen=True)
class ActivityUpdate:
    counted: bool
    xp_awarded: int
    old_level: int
    new_level: int
    profile: ActivityProfile

    @property
    def leveled_up(self) -> bool:
        return self.new_level > self.old_level


class ActivityService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.settings = ServerSettingsService(db)
        self._message_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._voice_locks: dict[tuple[int, int], asyncio.Lock] = {}

    @staticmethod
    def _dt(raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    @staticmethod
    def _hash_message(content: str) -> str:
        normalized = re.sub(r"\s+", " ", content.strip().casefold())
        return hashlib.blake2b(normalized.encode("utf-8"), digest_size=12).hexdigest()

    @staticmethod
    def _valid_message(content: str) -> bool:
        stripped = content.strip()
        if not stripped or stripped.startswith("!"):
            return False
        return sum(1 for char in stripped if char.isalnum()) >= cfg.ACTIVITY_MIN_MESSAGE_ALNUM

    async def is_enabled(self, guild_id: int) -> bool:
        return await self.settings.get_bool(guild_id, cfg.ACTIVITY_ENABLED_KEY, cfg.ACTIVITY_DEFAULT_ENABLED)

    async def chat_enabled(self, guild_id: int) -> bool:
        return await self.settings.get_bool(guild_id, cfg.ACTIVITY_CHAT_ENABLED_KEY, cfg.ACTIVITY_DEFAULT_CHAT_ENABLED)

    async def voice_enabled(self, guild_id: int) -> bool:
        return await self.settings.get_bool(guild_id, cfg.ACTIVITY_VOICE_ENABLED_KEY, cfg.ACTIVITY_DEFAULT_VOICE_ENABLED)

    async def exclude_self_deaf(self, guild_id: int) -> bool:
        return await self.settings.get_bool(guild_id, cfg.ACTIVITY_EXCLUDE_SELF_DEAF_KEY, cfg.ACTIVITY_DEFAULT_EXCLUDE_SELF_DEAF)

    async def get_levelup_channel_id(self, guild_id: int) -> int | None:
        return await self.settings.get_int(guild_id, cfg.ACTIVITY_LEVELUP_CHANNEL_KEY)

    async def chat_xp_range(self, guild_id: int) -> tuple[int, int]:
        low = await self.settings.get_int(guild_id, cfg.ACTIVITY_CHAT_XP_MIN_KEY)
        high = await self.settings.get_int(guild_id, cfg.ACTIVITY_CHAT_XP_MAX_KEY)
        low = cfg.ACTIVITY_DEFAULT_CHAT_XP_MIN if low is None else max(cfg.ACTIVITY_CHAT_XP_MIN_LIMIT, min(cfg.ACTIVITY_CHAT_XP_MAX_LIMIT, low))
        high = cfg.ACTIVITY_DEFAULT_CHAT_XP_MAX if high is None else max(cfg.ACTIVITY_CHAT_XP_MIN_LIMIT, min(cfg.ACTIVITY_CHAT_XP_MAX_LIMIT, high))
        if low > high:
            low, high = high, low
        return low, high

    async def chat_cooldown(self, guild_id: int) -> int:
        value = await self.settings.get_int(guild_id, cfg.ACTIVITY_CHAT_XP_COOLDOWN_KEY)
        value = cfg.ACTIVITY_DEFAULT_CHAT_XP_COOLDOWN_SECONDS if value is None else value
        return max(cfg.ACTIVITY_CHAT_COOLDOWN_MIN, min(cfg.ACTIVITY_CHAT_COOLDOWN_MAX, int(value)))

    async def message_min_interval(self, guild_id: int) -> int:
        value = await self.settings.get_int(guild_id, cfg.ACTIVITY_MESSAGE_MIN_INTERVAL_KEY)
        value = cfg.ACTIVITY_DEFAULT_MESSAGE_MIN_INTERVAL_SECONDS if value is None else value
        return max(cfg.ACTIVITY_MESSAGE_INTERVAL_MIN, min(cfg.ACTIVITY_MESSAGE_INTERVAL_MAX, int(value)))

    async def voice_xp_per_minute(self, guild_id: int) -> int:
        value = await self.settings.get_int(guild_id, cfg.ACTIVITY_VOICE_XP_PER_MINUTE_KEY)
        value = cfg.ACTIVITY_DEFAULT_VOICE_XP_PER_MINUTE if value is None else value
        return max(cfg.ACTIVITY_VOICE_XP_MIN, min(cfg.ACTIVITY_VOICE_XP_MAX, int(value)))

    async def profile(self, guild_id: int, user_id: int) -> ActivityProfile:
        row = await self.db.get_activity_profile(guild_id, user_id)
        return ActivityProfile(**row)

    async def record_message(self, guild_id: int, user_id: int, content: str, *, now: datetime | None = None) -> ActivityUpdate | None:
        if not await self.is_enabled(guild_id) or not await self.chat_enabled(guild_id) or not self._valid_message(content):
            return None
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        key = (guild_id, user_id)
        lock = self._message_locks.setdefault(key, asyncio.Lock())
        async with lock:
            before = await self.profile(guild_id, user_id)
            last_message = self._dt(before.last_message_at)
            min_interval = await self.message_min_interval(guild_id)
            if last_message and (now - last_message).total_seconds() < min_interval:
                return ActivityUpdate(False, 0, before.level, before.level, before)

            message_hash = self._hash_message(content)
            duplicate_since = (now - timedelta(seconds=cfg.ACTIVITY_DUPLICATE_WINDOW_SECONDS)).isoformat()
            if await self.db.activity_message_hash_seen_since(guild_id, user_id, message_hash, duplicate_since):
                return ActivityUpdate(False, 0, before.level, before.level, before)

            award = 0
            last_xp = self._dt(before.last_chat_xp_at)
            cooldown = await self.chat_cooldown(guild_id)
            if last_xp is None or (now - last_xp).total_seconds() >= cooldown:
                low, high = await self.chat_xp_range(guild_id)
                award = random.randint(low, high)

            total_xp = before.total_xp + award
            level = cfg.level_for_xp(total_xp)
            row = await self.db.record_activity_message(
                guild_id,
                user_id,
                xp_award=award,
                new_level=level,
                message_hash=message_hash,
                now=now.isoformat(),
            )
            after = ActivityProfile(**row)
            return ActivityUpdate(True, award, before.level, after.level, after)

    async def record_voice_minute(self, guild_id: int, user_id: int, *, seconds: int = cfg.ACTIVITY_VOICE_TICK_SECONDS) -> ActivityUpdate | None:
        if not await self.is_enabled(guild_id) or not await self.voice_enabled(guild_id):
            return None
        seconds = max(1, int(seconds))
        key = (guild_id, user_id)
        lock = self._voice_locks.setdefault(key, asyncio.Lock())
        async with lock:
            before = await self.profile(guild_id, user_id)
            per_minute = await self.voice_xp_per_minute(guild_id)
            award = max(1, round(per_minute * seconds / 60))
            total_xp = before.total_xp + award
            level = cfg.level_for_xp(total_xp)
            row = await self.db.record_activity_voice(
                guild_id,
                user_id,
                seconds=seconds,
                xp_award=award,
                new_level=level,
                now=datetime.now(timezone.utc).isoformat(),
            )
            after = ActivityProfile(**row)
            return ActivityUpdate(True, award, before.level, after.level, after)

    @staticmethod
    def _clean_milestone_name(value: object) -> str:
        return str(value or "").strip()[:100]

    @staticmethod
    def _clean_role_color(value: object) -> int:
        try:
            return max(0, min(0xFFFFFF, int(value)))
        except (TypeError, ValueError):
            return cfg.ACTIVITY_DEFAULT_ROLE_COLOR

    async def get_milestone_layout(self, guild_id: int) -> list[dict[str, int | str]]:
        """Return the server-owned Activity ladder stored in the DB.

        v3.17.5 makes this list fully dynamic. The file contains only the first
        install defaults; once a guild has a v3 layout, even an intentionally
        empty list remains authoritative and source replacement cannot restore
        deleted milestones.
        """
        version = await self.settings.get_int(guild_id, cfg.ACTIVITY_MILESTONE_LAYOUT_VERSION_KEY)
        stored = await self.settings.get_list(guild_id, cfg.ACTIVITY_MILESTONE_LAYOUT_KEY, [])
        layout: list[dict[str, int | str]] = []
        seen_levels: set[int] = set()
        seen_names: set[str] = set()
        for item in stored:
            if not isinstance(item, dict):
                continue
            try:
                level = int(item.get("level", 0))
            except (TypeError, ValueError):
                continue
            name = self._clean_milestone_name(item.get("role_name"))
            folded = name.casefold()
            if not (1 <= level <= cfg.ACTIVITY_MAX_MILESTONE_LEVEL):
                continue
            if not name or level in seen_levels or folded in seen_names:
                continue
            seen_levels.add(level)
            seen_names.add(folded)
            layout.append({"level": level, "role_name": name})

        # v2 -> v3 migration keeps the server's existing persisted ladder.
        # A v3 empty list is intentional and must NOT resurrect file defaults.
        if version != cfg.ACTIVITY_MILESTONE_LAYOUT_VERSION:
            if not layout:
                layout = cfg.default_milestone_layout()
            await self._save_milestone_layout(guild_id, layout)
        layout.sort(key=lambda row: int(row["level"]))
        return layout[: cfg.ACTIVITY_MAX_MILESTONES]

    async def get_milestone_levels(self, guild_id: int) -> list[int]:
        return [int(row["level"]) for row in await self.get_milestone_layout(guild_id)]

    def _normalize_milestone_row(
        self,
        definition: dict[str, int | str],
        item: dict | None,
    ) -> dict[str, int | str | bool | None]:
        item = item or {}
        level = int(definition["level"])
        role_name = self._clean_milestone_name(definition["role_name"])
        role_id = item.get("role_id")
        try:
            role_id = int(role_id) if role_id not in (None, "") else None
        except (TypeError, ValueError):
            role_id = None
        try:
            income = max(0, int(item.get("hourly_income", 0)))
        except (TypeError, ValueError):
            income = 0
        return {
            "level": level,
            "role_id": role_id,
            "role_name": role_name,
            "hourly_income": income,
            "role_color": self._clean_role_color(item.get("role_color", cfg.ACTIVITY_DEFAULT_ROLE_COLOR)),
            "role_hoist": bool(item.get("role_hoist", False)),
            "role_mentionable": bool(item.get("role_mentionable", False)),
        }

    async def get_milestones(self, guild_id: int) -> list[dict[str, int | str | bool | None]]:
        stored = await self.settings.get_list(guild_id, cfg.ACTIVITY_MILESTONES_KEY, [])
        by_level: dict[int, dict] = {}
        by_name: dict[str, dict] = {}
        for item in stored:
            if not isinstance(item, dict):
                continue
            try:
                level = int(item.get("level", 0))
            except (TypeError, ValueError):
                level = 0
            if level > 0:
                by_level[level] = item
            old_name = self._clean_milestone_name(item.get("role_name")).casefold()
            if old_name:
                by_name[old_name] = item

        layout = await self.get_milestone_layout(guild_id)
        result: list[dict[str, int | str | bool | None]] = []
        for definition in layout:
            level = int(definition["level"])
            role_name = self._clean_milestone_name(definition["role_name"])
            # Name matching preserves mappings when v3.17.4 moved the default
            # social ladder to different levels. Level matching handles all
            # normal dynamic edits from v3.17.5 onward.
            item = by_level.get(level) or by_name.get(role_name.casefold()) or {}
            result.append(self._normalize_milestone_row(definition, item))

        if result != stored:
            await self._save_milestones(guild_id, result)
        return result

    async def _save_milestones(self, guild_id: int, milestones: list[dict]) -> None:
        rows = sorted(milestones, key=lambda row: int(row["level"]))[: cfg.ACTIVITY_MAX_MILESTONES]
        await self.settings.set_list(guild_id, cfg.ACTIVITY_MILESTONES_KEY, rows)

    async def _save_milestone_layout(self, guild_id: int, layout: list[dict[str, int | str]]) -> None:
        rows = sorted(layout, key=lambda row: int(row["level"]))[: cfg.ACTIVITY_MAX_MILESTONES]
        await self.settings.set_list(guild_id, cfg.ACTIVITY_MILESTONE_LAYOUT_KEY, rows)
        await self.settings.set_int(guild_id, cfg.ACTIVITY_MILESTONE_LAYOUT_VERSION_KEY, cfg.ACTIVITY_MILESTONE_LAYOUT_VERSION)

    async def get_retired_role_ids(self, guild_id: int) -> list[int]:
        raw = await self.settings.get_list(guild_id, cfg.ACTIVITY_RETIRED_ROLE_IDS_KEY, [])
        result: list[int] = []
        for value in raw:
            try:
                role_id = int(value)
            except (TypeError, ValueError):
                continue
            if role_id > 0 and role_id not in result:
                result.append(role_id)
        return result[:250]

    async def retire_role(self, guild_id: int, role_id: int | None) -> None:
        if not role_id:
            return
        rows = await self.get_retired_role_ids(guild_id)
        role_id = int(role_id)
        if role_id not in rows:
            rows.append(role_id)
            await self.settings.set_list(guild_id, cfg.ACTIVITY_RETIRED_ROLE_IDS_KEY, rows[-250:])

    async def unretire_role(self, guild_id: int, role_id: int | None) -> None:
        if not role_id:
            return
        rows = await self.get_retired_role_ids(guild_id)
        role_id = int(role_id)
        if role_id in rows:
            rows.remove(role_id)
            await self.settings.set_list(guild_id, cfg.ACTIVITY_RETIRED_ROLE_IDS_KEY, rows)

    async def set_milestone(
        self,
        guild_id: int,
        level: int,
        *,
        role_id: int | None | object = ...,
        role_name: str | None = None,
        hourly_income: int | None = None,
        role_color: int | None = None,
        role_hoist: bool | None = None,
        role_mentionable: bool | None = None,
    ) -> dict[str, int | str | bool | None]:
        rows = await self.get_milestones(guild_id)
        target = next((row for row in rows if int(row["level"]) == int(level)), None)
        if target is None:
            raise ValueError("Ismeretlen Activity milestone.")

        if role_id is not ...:
            target["role_id"] = int(role_id) if role_id is not None else None
            if role_id is not None:
                await self.unretire_role(guild_id, int(role_id))
        if role_name is not None:
            name = self._clean_milestone_name(role_name)
            if not name:
                raise ValueError("A rang neve nem lehet üres.")
            if any(int(row["level"]) != int(level) and str(row["role_name"]).casefold() == name.casefold() for row in rows):
                raise ValueError("Már van milestone ezzel a rangnévvel.")
            target["role_name"] = name
        if hourly_income is not None:
            target["hourly_income"] = max(0, int(hourly_income))
        if role_color is not None:
            target["role_color"] = self._clean_role_color(role_color)
        if role_hoist is not None:
            target["role_hoist"] = bool(role_hoist)
        if role_mentionable is not None:
            target["role_mentionable"] = bool(role_mentionable)

        layout = [
            {"level": int(row["level"]), "role_name": str(row["role_name"])}
            for row in rows
        ]
        await self._save_milestone_layout(guild_id, layout)
        await self._save_milestones(guild_id, rows)
        return target

    async def add_milestone(
        self,
        guild_id: int,
        level: int,
        role_name: str,
        *,
        role_id: int | None = None,
        hourly_income: int = 0,
        role_color: int = cfg.ACTIVITY_DEFAULT_ROLE_COLOR,
        role_hoist: bool = False,
        role_mentionable: bool = False,
    ) -> dict[str, int | str | bool | None]:
        level = int(level)
        name = self._clean_milestone_name(role_name)
        if not (1 <= level <= cfg.ACTIVITY_MAX_MILESTONE_LEVEL):
            raise ValueError(f"A milestone szint 1–{cfg.ACTIVITY_MAX_MILESTONE_LEVEL} között legyen.")
        if not name:
            raise ValueError("A rang neve nem lehet üres.")
        rows = await self.get_milestones(guild_id)
        if len(rows) >= cfg.ACTIVITY_MAX_MILESTONES:
            raise ValueError(f"Legfeljebb {cfg.ACTIVITY_MAX_MILESTONES} Activity milestone lehet.")
        if any(int(row["level"]) == level for row in rows):
            raise ValueError(f"Már létezik Lv. {level} milestone.")
        if any(str(row["role_name"]).casefold() == name.casefold() for row in rows):
            raise ValueError("Már van milestone ezzel a rangnévvel.")
        if role_id and any(int(row.get("role_id") or 0) == int(role_id) for row in rows):
            raise ValueError("Ez a Discord rang már másik Activity milestone-hoz van kötve.")

        row: dict[str, int | str | bool | None] = {
            "level": level,
            "role_id": int(role_id) if role_id else None,
            "role_name": name,
            "hourly_income": max(0, int(hourly_income)),
            "role_color": self._clean_role_color(role_color),
            "role_hoist": bool(role_hoist),
            "role_mentionable": bool(role_mentionable),
        }
        rows.append(row)
        rows.sort(key=lambda item: int(item["level"]))
        await self._save_milestone_layout(guild_id, [
            {"level": int(item["level"]), "role_name": str(item["role_name"])} for item in rows
        ])
        await self._save_milestones(guild_id, rows)
        if role_id:
            await self.unretire_role(guild_id, int(role_id))
        return row

    async def update_milestone(
        self,
        guild_id: int,
        old_level: int,
        *,
        new_level: int,
        role_name: str,
        hourly_income: int,
    ) -> dict[str, int | str | bool | None]:
        old_level = int(old_level)
        new_level = int(new_level)
        name = self._clean_milestone_name(role_name)
        if not (1 <= new_level <= cfg.ACTIVITY_MAX_MILESTONE_LEVEL):
            raise ValueError(f"A milestone szint 1–{cfg.ACTIVITY_MAX_MILESTONE_LEVEL} között legyen.")
        if not name:
            raise ValueError("A rang neve nem lehet üres.")
        rows = await self.get_milestones(guild_id)
        target = next((row for row in rows if int(row["level"]) == old_level), None)
        if target is None:
            raise ValueError("A milestone már nem létezik.")
        if any(row is not target and int(row["level"]) == new_level for row in rows):
            raise ValueError(f"Már létezik Lv. {new_level} milestone.")
        if any(row is not target and str(row["role_name"]).casefold() == name.casefold() for row in rows):
            raise ValueError("Már van milestone ezzel a rangnévvel.")
        target["level"] = new_level
        target["role_name"] = name
        target["hourly_income"] = max(0, int(hourly_income))
        rows.sort(key=lambda item: int(item["level"]))
        await self._save_milestone_layout(guild_id, [
            {"level": int(item["level"]), "role_name": str(item["role_name"])} for item in rows
        ])
        await self._save_milestones(guild_id, rows)
        return target

    async def delete_milestone(self, guild_id: int, level: int) -> dict[str, int | str | bool | None]:
        rows = await self.get_milestones(guild_id)
        target = next((row for row in rows if int(row["level"]) == int(level)), None)
        if target is None:
            raise ValueError("A milestone már nem létezik.")
        rows.remove(target)
        if target.get("role_id"):
            await self.retire_role(guild_id, int(target["role_id"]))
        await self._save_milestone_layout(guild_id, [
            {"level": int(item["level"]), "role_name": str(item["role_name"])} for item in rows
        ])
        await self._save_milestones(guild_id, rows)
        return target

    async def sync_role_snapshot(
        self,
        guild_id: int,
        role_id: int,
        *,
        role_name: str,
        role_color: int,
        role_hoist: bool,
        role_mentionable: bool,
    ) -> dict[str, int | str | bool | None] | None:
        """Discord -> DB sync for a role already bound to an Activity milestone."""
        rows = await self.get_milestones(guild_id)
        target = next((row for row in rows if int(row.get("role_id") or 0) == int(role_id)), None)
        if target is None:
            return None
        name = self._clean_milestone_name(role_name)
        if name and not any(row is not target and str(row["role_name"]).casefold() == name.casefold() for row in rows):
            target["role_name"] = name
        target["role_color"] = self._clean_role_color(role_color)
        target["role_hoist"] = bool(role_hoist)
        target["role_mentionable"] = bool(role_mentionable)
        await self._save_milestone_layout(guild_id, [
            {"level": int(item["level"]), "role_name": str(item["role_name"])} for item in rows
        ])
        await self._save_milestones(guild_id, rows)
        return target

    async def mark_role_deleted(self, guild_id: int, role_id: int) -> dict[str, int | str | bool | None] | None:
        rows = await self.get_milestones(guild_id)
        target = next((row for row in rows if int(row.get("role_id") or 0) == int(role_id)), None)
        if target is None:
            return None
        target["role_id"] = None
        await self._save_milestones(guild_id, rows)
        return target

    async def set_chat_tuning(self, guild_id: int, *, xp_min: int, xp_max: int, cooldown: int, min_interval: int) -> None:
        if not (cfg.ACTIVITY_CHAT_XP_MIN_LIMIT <= xp_min <= cfg.ACTIVITY_CHAT_XP_MAX_LIMIT):
            raise ValueError(f"A minimum chat XP {cfg.ACTIVITY_CHAT_XP_MIN_LIMIT}–{cfg.ACTIVITY_CHAT_XP_MAX_LIMIT} között legyen.")
        if not (cfg.ACTIVITY_CHAT_XP_MIN_LIMIT <= xp_max <= cfg.ACTIVITY_CHAT_XP_MAX_LIMIT):
            raise ValueError(f"A maximum chat XP {cfg.ACTIVITY_CHAT_XP_MIN_LIMIT}–{cfg.ACTIVITY_CHAT_XP_MAX_LIMIT} között legyen.")
        if xp_min > xp_max:
            raise ValueError("A minimum chat XP nem lehet nagyobb a maximumnál.")
        if not (cfg.ACTIVITY_CHAT_COOLDOWN_MIN <= cooldown <= cfg.ACTIVITY_CHAT_COOLDOWN_MAX):
            raise ValueError(f"A chat XP cooldown {cfg.ACTIVITY_CHAT_COOLDOWN_MIN}–{cfg.ACTIVITY_CHAT_COOLDOWN_MAX} mp között legyen.")
        if not (cfg.ACTIVITY_MESSAGE_INTERVAL_MIN <= min_interval <= cfg.ACTIVITY_MESSAGE_INTERVAL_MAX):
            raise ValueError(f"A message anti-farm idő {cfg.ACTIVITY_MESSAGE_INTERVAL_MIN}–{cfg.ACTIVITY_MESSAGE_INTERVAL_MAX} mp között legyen.")
        await self.settings.set_int(guild_id, cfg.ACTIVITY_CHAT_XP_MIN_KEY, xp_min)
        await self.settings.set_int(guild_id, cfg.ACTIVITY_CHAT_XP_MAX_KEY, xp_max)
        await self.settings.set_int(guild_id, cfg.ACTIVITY_CHAT_XP_COOLDOWN_KEY, cooldown)
        await self.settings.set_int(guild_id, cfg.ACTIVITY_MESSAGE_MIN_INTERVAL_KEY, min_interval)

    async def set_voice_tuning(self, guild_id: int, *, xp_per_minute: int) -> None:
        if not (cfg.ACTIVITY_VOICE_XP_MIN <= xp_per_minute <= cfg.ACTIVITY_VOICE_XP_MAX):
            raise ValueError(f"A voice XP/perc {cfg.ACTIVITY_VOICE_XP_MIN}–{cfg.ACTIVITY_VOICE_XP_MAX} között legyen.")
        await self.settings.set_int(guild_id, cfg.ACTIVITY_VOICE_XP_PER_MINUTE_KEY, xp_per_minute)

    @staticmethod
    def voice_time_text(seconds: int) -> str:
        minutes = max(0, int(seconds)) // 60
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours} óra {minutes} perc"
        return f"{minutes} perc"
