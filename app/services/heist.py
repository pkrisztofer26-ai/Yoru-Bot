from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from app import heist_config as cfg
from app.services.server_settings import ServerSettingsService


@dataclass(frozen=True)
class HeistSettings:
    enabled: bool
    required_activity_level: int
    required_prestige: int
    cooldown_hours: int
    jail_minutes: int
    fine_percent: int
    gear_loss_percent: int
    reward_multiplier_percent: int


class HeistService:
    def __init__(self, database, statistics, prestige, activity, crew, factions) -> None:
        self.db = database
        self.stats = statistics
        self.prestige = prestige
        self.activity = activity
        self.crew = crew
        self.factions = factions
        self.settings = ServerSettingsService(database)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _dt(raw: str | None) -> datetime | None:
        if not raw:
            return None
        value = datetime.fromisoformat(str(raw))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    async def get_settings(self, guild_id: int) -> HeistSettings:
        async def _int(key: str, default: int, minimum: int, maximum: int) -> int:
            value = await self.settings.get_int(guild_id, key)
            return max(minimum, min(maximum, default if value is None else int(value)))

        return HeistSettings(
            enabled=await self.settings.get_bool(guild_id, cfg.HEIST_ENABLED_KEY, cfg.DEFAULT_ENABLED),
            required_activity_level=await _int(cfg.HEIST_ACTIVITY_LEVEL_KEY, cfg.DEFAULT_REQUIRED_ACTIVITY_LEVEL, cfg.MIN_ACTIVITY_LEVEL, cfg.MAX_ACTIVITY_LEVEL),
            required_prestige=await _int(cfg.HEIST_PRESTIGE_KEY, cfg.DEFAULT_REQUIRED_PRESTIGE, cfg.MIN_PRESTIGE, cfg.MAX_PRESTIGE),
            cooldown_hours=await _int(cfg.HEIST_COOLDOWN_HOURS_KEY, cfg.DEFAULT_COOLDOWN_HOURS, cfg.MIN_COOLDOWN_HOURS, cfg.MAX_COOLDOWN_HOURS),
            jail_minutes=await _int(cfg.HEIST_JAIL_MINUTES_KEY, cfg.DEFAULT_JAIL_MINUTES, cfg.MIN_JAIL_MINUTES, cfg.MAX_JAIL_MINUTES),
            fine_percent=await _int(cfg.HEIST_FINE_PERCENT_KEY, cfg.DEFAULT_FINE_PERCENT, cfg.MIN_FINE_PERCENT, cfg.MAX_FINE_PERCENT),
            gear_loss_percent=await _int(cfg.HEIST_GEAR_LOSS_PERCENT_KEY, cfg.DEFAULT_GEAR_LOSS_PERCENT, cfg.MIN_GEAR_LOSS_PERCENT, cfg.MAX_GEAR_LOSS_PERCENT),
            reward_multiplier_percent=await _int(cfg.HEIST_REWARD_MULTIPLIER_KEY, cfg.DEFAULT_REWARD_MULTIPLIER_PERCENT, cfg.MIN_REWARD_MULTIPLIER_PERCENT, cfg.MAX_REWARD_MULTIPLIER_PERCENT),
        )

    async def set_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.settings.set_bool(guild_id, cfg.HEIST_ENABLED_KEY, bool(enabled))

    async def set_unlock_settings(self, guild_id: int, *, activity_level: int, prestige: int) -> None:
        if not cfg.MIN_ACTIVITY_LEVEL <= int(activity_level) <= cfg.MAX_ACTIVITY_LEVEL:
            raise ValueError(f"Az Activity követelmény {cfg.MIN_ACTIVITY_LEVEL}–{cfg.MAX_ACTIVITY_LEVEL} között lehet.")
        if not cfg.MIN_PRESTIGE <= int(prestige) <= cfg.MAX_PRESTIGE:
            raise ValueError(f"A Prestige követelmény {cfg.MIN_PRESTIGE}–{cfg.MAX_PRESTIGE} között lehet.")
        await self.settings.set_int(guild_id, cfg.HEIST_ACTIVITY_LEVEL_KEY, int(activity_level))
        await self.settings.set_int(guild_id, cfg.HEIST_PRESTIGE_KEY, int(prestige))

    async def set_risk_settings(
        self,
        guild_id: int,
        *,
        cooldown_hours: int,
        jail_minutes: int,
        fine_percent: int,
        gear_loss_percent: int,
        reward_multiplier_percent: int,
    ) -> None:
        values = (
            (cooldown_hours, cfg.MIN_COOLDOWN_HOURS, cfg.MAX_COOLDOWN_HOURS, "cooldown"),
            (jail_minutes, cfg.MIN_JAIL_MINUTES, cfg.MAX_JAIL_MINUTES, "jail idő"),
            (fine_percent, cfg.MIN_FINE_PERCENT, cfg.MAX_FINE_PERCENT, "bírság"),
            (gear_loss_percent, cfg.MIN_GEAR_LOSS_PERCENT, cfg.MAX_GEAR_LOSS_PERCENT, "gear loss"),
            (reward_multiplier_percent, cfg.MIN_REWARD_MULTIPLIER_PERCENT, cfg.MAX_REWARD_MULTIPLIER_PERCENT, "reward multiplier"),
        )
        for value, minimum, maximum, label in values:
            if not minimum <= int(value) <= maximum:
                raise ValueError(f"A(z) {label} {minimum}–{maximum} között lehet.")
        await self.settings.set_int(guild_id, cfg.HEIST_COOLDOWN_HOURS_KEY, int(cooldown_hours))
        await self.settings.set_int(guild_id, cfg.HEIST_JAIL_MINUTES_KEY, int(jail_minutes))
        await self.settings.set_int(guild_id, cfg.HEIST_FINE_PERCENT_KEY, int(fine_percent))
        await self.settings.set_int(guild_id, cfg.HEIST_GEAR_LOSS_PERCENT_KEY, int(gear_loss_percent))
        await self.settings.set_int(guild_id, cfg.HEIST_REWARD_MULTIPLIER_KEY, int(reward_multiplier_percent))

    async def eligibility(self, guild_id: int, user_id: int, target_key: str | None = None) -> dict[str, Any]:
        settings = await self.get_settings(guild_id)
        activity = await self.activity.profile(guild_id, user_id)
        prestige = await self.prestige.state(guild_id, user_id)
        target = cfg.TARGET_BY_KEY.get(target_key) if target_key else None
        required_activity = max(settings.required_activity_level, target.activity_level if target else 0)
        required_prestige = max(settings.required_prestige, target.prestige if target else 0)
        jailed_until = await self.db.get_jail_until(guild_id, user_id)
        if jailed_until and jailed_until <= self._now():
            await self.db.set_jail_until(guild_id, user_id, None)
            jailed_until = None
        cooldown_until = await self.cooldown_until(guild_id, user_id)
        return {
            "enabled": settings.enabled,
            "activity_level": activity.level,
            "prestige": prestige.rank,
            "required_activity_level": required_activity,
            "required_prestige": required_prestige,
            "jailed_until": jailed_until,
            "cooldown_until": cooldown_until,
            "eligible": (
                settings.enabled
                and activity.level >= required_activity
                and prestige.rank >= required_prestige
                and not jailed_until
                and not cooldown_until
            ),
        }

    async def cooldown_until(self, guild_id: int, user_id: int) -> datetime | None:
        settings = await self.get_settings(guild_id)
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "SELECT last_heist_at FROM heist_cooldowns WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            row = await cur.fetchone()
        if not row or not row[0]:
            return None
        last = self._dt(str(row[0]))
        until = last + timedelta(hours=settings.cooldown_hours) if last else None
        return until if until and until > self._now() else None

    async def cleanup_expired_lobbies(self, guild_id: int) -> int:
        now = self._now().isoformat()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                "SELECT lobby_id FROM heist_lobbies WHERE guild_id=? AND status='forming' AND expires_at<=?",
                (guild_id, now),
            )
            ids = [int(row[0]) for row in await cur.fetchall()]
            if ids:
                marks = ",".join("?" for _ in ids)
                await conn.execute(
                    f"UPDATE heist_lobbies SET status='expired', resolved_at=? WHERE lobby_id IN ({marks})",
                    (now, *ids),
                )
            await conn.commit()
        return len(ids)

    async def active_lobby_for_user(self, guild_id: int, user_id: int) -> dict[str, Any] | None:
        await self.cleanup_expired_lobbies(guild_id)
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                """SELECT l.* FROM heist_lobbies l
                   JOIN heist_lobby_members m ON m.lobby_id=l.lobby_id AND m.guild_id=l.guild_id
                   WHERE l.guild_id=? AND m.user_id=? AND m.status='accepted' AND l.status IN ('forming','running')
                   ORDER BY l.lobby_id DESC LIMIT 1""",
                (guild_id, user_id),
            )
            row = await cur.fetchone()
        return dict(row) if row else None

    async def pending_invites(self, guild_id: int, user_id: int) -> list[dict[str, Any]]:
        await self.cleanup_expired_lobbies(guild_id)
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                """SELECT l.lobby_id,l.leader_id,l.target_key,l.created_at,l.expires_at
                   FROM heist_lobbies l JOIN heist_lobby_members m ON m.lobby_id=l.lobby_id AND m.guild_id=l.guild_id
                   WHERE l.guild_id=? AND m.user_id=? AND m.status='pending' AND l.status='forming'
                   ORDER BY l.created_at DESC""",
                (guild_id, user_id),
            )
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def get_lobby(self, guild_id: int, lobby_id: int) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute("SELECT * FROM heist_lobbies WHERE guild_id=? AND lobby_id=?", (guild_id, lobby_id))
            row = await cur.fetchone()
        return dict(row) if row else None

    async def lobby_members(self, guild_id: int, lobby_id: int) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                """SELECT user_id,status,role_key,cut_percent,cut_accepted,gear_key,joined_at
                   FROM heist_lobby_members WHERE guild_id=? AND lobby_id=?
                   ORDER BY CASE status WHEN 'accepted' THEN 0 ELSE 1 END, joined_at""",
                (guild_id, lobby_id),
            )
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def create_lobby(self, guild_id: int, leader_id: int, target_key: str) -> dict[str, Any]:
        target = cfg.TARGET_BY_KEY.get(target_key)
        if target is None:
            raise ValueError("Ismeretlen Nagy Meló célpont.")
        eligibility = await self.eligibility(guild_id, leader_id, target_key)
        if not eligibility["enabled"]:
            raise ValueError("A Nagy Meló rendszer ezen a szerveren ki van kapcsolva.")
        if eligibility["activity_level"] < eligibility["required_activity_level"]:
            raise ValueError(f"Ehhez legalább Activity **Lv.{eligibility['required_activity_level']}** kell.")
        if eligibility["prestige"] < eligibility["required_prestige"]:
            raise ValueError(f"Ehhez legalább **Prestige {eligibility['required_prestige']}** kell.")
        if eligibility["jailed_until"]:
            raise ValueError("Börtönből nem indíthatsz Nagy Melót.")
        if eligibility["cooldown_until"]:
            raise ValueError("Még tart a Nagy Meló cooldownod.")
        if await self.active_lobby_for_user(guild_id, leader_id):
            raise ValueError("Már van aktív Nagy Meló lobbyd.")
        now = self._now()
        expires = now + timedelta(minutes=cfg.LOBBY_EXPIRE_MINUTES)
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                """INSERT INTO heist_lobbies
                   (guild_id,leader_id,target_key,status,phase,created_at,expires_at)
                   VALUES(?,?,?,'forming',0,?,?)""",
                (guild_id, leader_id, target_key, now.isoformat(), expires.isoformat()),
            )
            lobby_id = int(cur.lastrowid or 0)
            await conn.execute(
                """INSERT INTO heist_lobby_members
                   (guild_id,lobby_id,user_id,status,role_key,cut_percent,cut_accepted,gear_key,joined_at)
                   VALUES(?,?,?,'accepted','planner',100,1,NULL,?)""",
                (guild_id, lobby_id, leader_id, now.isoformat()),
            )
            await conn.commit()
        return (await self.get_lobby(guild_id, lobby_id)) or {}

    async def invite_member(self, guild_id: int, lobby_id: int, leader_id: int, user_id: int) -> None:
        if user_id == leader_id:
            raise ValueError("Saját magadat nem kell meghívnod.")
        lobby = await self.get_lobby(guild_id, lobby_id)
        if not lobby or int(lobby["leader_id"]) != leader_id or lobby["status"] != "forming":
            raise ValueError("Ezt a lobbyt már nem tudod szerkeszteni.")
        members = await self.lobby_members(guild_id, lobby_id)
        if sum(1 for m in members if m["status"] in {"accepted", "pending"}) >= cfg.MAX_PARTY_SIZE:
            raise ValueError(f"A party maximum {cfg.MAX_PARTY_SIZE} fős lehet.")
        if await self.active_lobby_for_user(guild_id, user_id):
            raise ValueError("A játékos már másik aktív Nagy Melóban van.")
        target_key = str(lobby["target_key"])
        eligible = await self.eligibility(guild_id, user_id, target_key)
        if eligible["activity_level"] < eligible["required_activity_level"] or eligible["prestige"] < eligible["required_prestige"]:
            raise ValueError("A játékos még nem teljesíti ennek a célpontnak a követelményeit.")
        if eligible["jailed_until"] or eligible["cooldown_until"]:
            raise ValueError("A játékos jelenleg nem tud csatlakozni (jail/cooldown).")
        now = self._now().isoformat()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute(
                """INSERT INTO heist_lobby_members
                   (guild_id,lobby_id,user_id,status,role_key,cut_percent,cut_accepted,gear_key,joined_at)
                   VALUES(?,?,?,'pending','support',0,0,NULL,?)
                   ON CONFLICT(guild_id,lobby_id,user_id) DO UPDATE SET status='pending',joined_at=excluded.joined_at""",
                (guild_id, lobby_id, user_id, now),
            )
            await conn.commit()

    async def _redistribute_equal_cuts(self, conn, guild_id: int, lobby_id: int) -> None:
        cur = await conn.execute(
            "SELECT user_id FROM heist_lobby_members WHERE guild_id=? AND lobby_id=? AND status='accepted' ORDER BY joined_at,user_id",
            (guild_id, lobby_id),
        )
        user_ids = [int(row[0]) for row in await cur.fetchall()]
        if not user_ids:
            return
        base = 100 // len(user_ids)
        remainder = 100 - base * len(user_ids)
        for index, user_id in enumerate(user_ids):
            cut = base + (remainder if index == 0 else 0)
            await conn.execute(
                "UPDATE heist_lobby_members SET cut_percent=?,cut_accepted=0 WHERE guild_id=? AND lobby_id=? AND user_id=?",
                (cut, guild_id, lobby_id, user_id),
            )

    async def respond_invite(self, guild_id: int, lobby_id: int, user_id: int, *, accept: bool) -> None:
        if accept and await self.active_lobby_for_user(guild_id, user_id):
            raise ValueError("Már van másik aktív Nagy Melód.")
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                """SELECT l.status,m.status,l.target_key FROM heist_lobbies l
                   JOIN heist_lobby_members m ON m.lobby_id=l.lobby_id AND m.guild_id=l.guild_id
                   WHERE l.guild_id=? AND l.lobby_id=? AND m.user_id=?""",
                (guild_id, lobby_id, user_id),
            )
            row = await cur.fetchone()
            if not row or row[0] != "forming" or row[1] != "pending":
                await conn.rollback()
                raise ValueError("Ez a meghívó már nem aktív.")
            if accept:
                await conn.execute(
                    "UPDATE heist_lobby_members SET status='accepted',role_key='support',cut_accepted=0 WHERE guild_id=? AND lobby_id=? AND user_id=?",
                    (guild_id, lobby_id, user_id),
                )
                await self._redistribute_equal_cuts(conn, guild_id, lobby_id)
            else:
                await conn.execute(
                    "UPDATE heist_lobby_members SET status='declined' WHERE guild_id=? AND lobby_id=? AND user_id=?",
                    (guild_id, lobby_id, user_id),
                )
            await conn.commit()

    async def remove_member(self, guild_id: int, lobby_id: int, actor_id: int, user_id: int) -> None:
        lobby = await self.get_lobby(guild_id, lobby_id)
        if not lobby or lobby["status"] != "forming":
            raise ValueError("A lobby már nem módosítható.")
        leader_id = int(lobby["leader_id"])
        if actor_id != user_id and actor_id != leader_id:
            raise ValueError("Csak saját magadat vagy leaderként más tagot távolíthatsz el.")
        if user_id == leader_id:
            raise ValueError("A leader nem léphet ki; a lobbyt töröld inkább.")
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            await conn.execute(
                "UPDATE heist_lobby_members SET status='left' WHERE guild_id=? AND lobby_id=? AND user_id=?",
                (guild_id, lobby_id, user_id),
            )
            await self._redistribute_equal_cuts(conn, guild_id, lobby_id)
            await conn.commit()

    async def cancel_lobby(self, guild_id: int, lobby_id: int, leader_id: int) -> None:
        lobby = await self.get_lobby(guild_id, lobby_id)
        if not lobby or int(lobby["leader_id"]) != leader_id:
            raise ValueError("Nem te vagy ennek a lobbynak a leadere.")
        if lobby["status"] != "forming":
            raise ValueError("Futó Nagy Melót már nem lehet visszavonni.")
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute(
                "UPDATE heist_lobbies SET status='cancelled',resolved_at=? WHERE guild_id=? AND lobby_id=?",
                (self._now().isoformat(), guild_id, lobby_id),
            )
            await conn.commit()

    async def set_role(self, guild_id: int, lobby_id: int, user_id: int, role_key: str) -> None:
        if role_key not in cfg.ROLE_BY_KEY:
            raise ValueError("Ismeretlen Nagy Meló szerepkör.")
        lobby = await self.get_lobby(guild_id, lobby_id)
        if not lobby or lobby["status"] != "forming":
            raise ValueError("A szerepkört már nem lehet módosítani.")
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "UPDATE heist_lobby_members SET role_key=? WHERE guild_id=? AND lobby_id=? AND user_id=? AND status='accepted'",
                (role_key, guild_id, lobby_id, user_id),
            )
            await conn.commit()
            if int(cur.rowcount or 0) == 0:
                raise ValueError("Nem vagy aktív tag ebben a lobbyban.")

    async def gear_inventory(self, guild_id: int, user_id: int) -> dict[str, int]:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "SELECT gear_key,quantity FROM heist_gear WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            rows = await cur.fetchall()
        return {str(key): int(quantity) for key, quantity in rows}

    async def buy_gear(self, guild_id: int, user_id: int, gear_key: str, quantity: int = 1) -> int:
        gear = cfg.GEAR_BY_KEY.get(gear_key)
        if gear is None:
            raise ValueError("Ismeretlen gear.")
        quantity = max(1, min(10, int(quantity)))
        total = gear.price * quantity
        await self.db.add_wallet(guild_id, user_id, -total, f"heist_gear_buy:{gear_key}x{quantity}")
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute(
                """INSERT INTO heist_gear (guild_id,user_id,gear_key,quantity) VALUES(?,?,?,?)
                   ON CONFLICT(guild_id,user_id,gear_key) DO UPDATE SET quantity=quantity+excluded.quantity""",
                (guild_id, user_id, gear_key, quantity),
            )
            await conn.commit()
        await self.stats.increment(guild_id, user_id, "heist.gear_bought", quantity)
        await self.stats.add(guild_id, user_id, "heist.gear_spent", total)
        return total

    async def set_gear(self, guild_id: int, lobby_id: int, user_id: int, gear_key: str | None) -> None:
        if gear_key is not None and gear_key not in cfg.GEAR_BY_KEY:
            raise ValueError("Ismeretlen gear.")
        lobby = await self.get_lobby(guild_id, lobby_id)
        if not lobby or lobby["status"] != "forming":
            raise ValueError("A loadout már nem módosítható.")
        if gear_key is not None:
            inv = await self.gear_inventory(guild_id, user_id)
            if inv.get(gear_key, 0) <= 0:
                raise ValueError("Nincs ilyen geared.")
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "UPDATE heist_lobby_members SET gear_key=? WHERE guild_id=? AND lobby_id=? AND user_id=? AND status='accepted'",
                (gear_key, guild_id, lobby_id, user_id),
            )
            await conn.commit()
            if int(cur.rowcount or 0) == 0:
                raise ValueError("Nem vagy aktív tag ebben a lobbyban.")

    async def set_cut(self, guild_id: int, lobby_id: int, leader_id: int, user_id: int, percent: int) -> None:
        percent = int(percent)
        if not 0 <= percent <= 100:
            raise ValueError("A részesedés 0–100% lehet.")
        lobby = await self.get_lobby(guild_id, lobby_id)
        if not lobby or int(lobby["leader_id"]) != leader_id or lobby["status"] != "forming":
            raise ValueError("Ezt a lobbyt már nem szerkesztheted.")
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                "UPDATE heist_lobby_members SET cut_percent=? WHERE guild_id=? AND lobby_id=? AND user_id=? AND status='accepted'",
                (percent, guild_id, lobby_id, user_id),
            )
            if int(cur.rowcount or 0) == 0:
                await conn.rollback()
                raise ValueError("A játékos nincs az elfogadott tagok között.")
            await conn.execute(
                "UPDATE heist_lobby_members SET cut_accepted=0 WHERE guild_id=? AND lobby_id=? AND status='accepted'",
                (guild_id, lobby_id),
            )
            await conn.commit()

    async def accept_cut(self, guild_id: int, lobby_id: int, user_id: int) -> None:
        members = [m for m in await self.lobby_members(guild_id, lobby_id) if m["status"] == "accepted"]
        if sum(int(m["cut_percent"]) for m in members) != 100:
            raise ValueError("A részesedések összege még nem 100%.")
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "UPDATE heist_lobby_members SET cut_accepted=1 WHERE guild_id=? AND lobby_id=? AND user_id=? AND status='accepted'",
                (guild_id, lobby_id, user_id),
            )
            await conn.commit()
            if int(cur.rowcount or 0) == 0:
                raise ValueError("Nem vagy aktív tag ebben a lobbyban.")

    async def _participant_state(self, guild_id: int, user_id: int, target_key: str) -> tuple[int, int]:
        activity = await self.activity.profile(guild_id, user_id)
        prestige = await self.prestige.state(guild_id, user_id)
        eligibility = await self.eligibility(guild_id, user_id, target_key)
        if not eligibility["eligible"]:
            if eligibility["jailed_until"]:
                raise ValueError(f"<@{user_id}> jelenleg börtönben van.")
            if eligibility["cooldown_until"]:
                raise ValueError(f"<@{user_id}> Nagy Meló cooldownon van.")
            raise ValueError(f"<@{user_id}> nem teljesíti a célpont követelményeit.")
        return activity.level, prestige.rank

    async def start_heist(self, guild_id: int, lobby_id: int, leader_id: int) -> dict[str, Any]:
        lobby = await self.get_lobby(guild_id, lobby_id)
        if not lobby or int(lobby["leader_id"]) != leader_id:
            raise ValueError("Nem te vagy ennek a lobbynak a leadere.")
        if lobby["status"] != "forming":
            raise ValueError("Ez a Nagy Meló már elindult vagy lezárult.")
        target = cfg.TARGET_BY_KEY.get(str(lobby["target_key"]))
        if target is None:
            raise ValueError("A célpont már nem létezik.")
        members = [m for m in await self.lobby_members(guild_id, lobby_id) if m["status"] == "accepted"]
        if not target.min_party <= len(members) <= target.max_party:
            raise ValueError(f"Ehhez a célponthoz {target.min_party}–{target.max_party} fő kell.")
        if sum(int(m["cut_percent"]) for m in members) != 100:
            raise ValueError("A részesedések összege legyen pontosan 100%.")
        if not all(bool(m["cut_accepted"]) for m in members):
            raise ValueError("Minden résztvevőnek el kell fogadnia a saját részesedését.")
        member_states: dict[int, tuple[int, int]] = {}
        for member in members:
            uid = int(member["user_id"])
            member_states[uid] = await self._participant_state(guild_id, uid, target.key)
            gear_key = member.get("gear_key")
            if gear_key:
                inv = await self.gear_inventory(guild_id, uid)
                if inv.get(str(gear_key), 0) <= 0:
                    raise ValueError(f"<@{uid}> kiválasztott gearje már nincs meg.")
        settings = await self.get_settings(guild_id)
        rng = random.Random(f"yoru:heist:reward:{guild_id}:{lobby_id}:{lobby['created_at']}")
        reward_pool = rng.randint(target.reward_min, target.reward_max)
        reward_pool = max(1, round(reward_pool * settings.reward_multiplier_percent / 100))
        now = self._now().isoformat()
        snapshot = {
            str(uid): {"activity": state[0], "prestige": state[1]}
            for uid, state in member_states.items()
        }
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                "SELECT status FROM heist_lobbies WHERE guild_id=? AND lobby_id=?",
                (guild_id, lobby_id),
            )
            row = await cur.fetchone()
            if not row or row[0] != "forming":
                await conn.rollback()
                raise ValueError("A lobby állapota közben megváltozott.")
            await conn.execute(
                "UPDATE heist_lobbies SET status='running',phase=0,started_at=? WHERE guild_id=? AND lobby_id=?",
                (now, guild_id, lobby_id),
            )
            await conn.execute(
                """INSERT INTO heist_runs
                   (guild_id,lobby_id,target_key,status,phase,reward_pool,phase_results,member_snapshot,started_at)
                   VALUES(?,?,?,'running',0,?,'[]',?,?)""",
                (guild_id, lobby_id, target.key, reward_pool, json.dumps(snapshot), now),
            )
            for member in members:
                await conn.execute(
                    """INSERT INTO heist_cooldowns (guild_id,user_id,last_heist_at)
                       VALUES(?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET last_heist_at=excluded.last_heist_at""",
                    (guild_id, int(member["user_id"]), now),
                )
            await conn.commit()
        for member in members:
            await self.stats.increment(guild_id, int(member["user_id"]), "heist.attempts")
        return await self.run_state(guild_id, lobby_id)

    async def run_state(self, guild_id: int, lobby_id: int) -> dict[str, Any]:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                "SELECT * FROM heist_runs WHERE guild_id=? AND lobby_id=? ORDER BY run_id DESC LIMIT 1",
                (guild_id, lobby_id),
            )
            row = await cur.fetchone()
        if not row:
            return {}
        result = dict(row)
        try:
            result["phase_results"] = json.loads(str(result.get("phase_results") or "[]"))
        except json.JSONDecodeError:
            result["phase_results"] = []
        try:
            result["member_snapshot"] = json.loads(str(result.get("member_snapshot") or "{}"))
        except json.JSONDecodeError:
            result["member_snapshot"] = {}
        return result

    @staticmethod
    def _phase_bonus(role_key: str, gear_key: str | None, phase_key: str) -> int:
        role = cfg.ROLE_BY_KEY.get(role_key, cfg.ROLE_BY_KEY["support"])
        gear = cfg.GEAR_BY_KEY.get(gear_key) if gear_key else None
        role_bonus = {
            "prep": role.prep_bonus,
            "execution": role.execution_bonus,
            "escape": role.escape_bonus,
        }[phase_key]
        gear_bonus = 0 if gear is None else {
            "prep": gear.prep_bonus,
            "execution": gear.execution_bonus,
            "escape": gear.escape_bonus,
        }[phase_key]
        return role_bonus + gear_bonus

    async def _resolve_run(self, guild_id: int, lobby_id: int, run: dict[str, Any], phase_results: list[dict[str, Any]]) -> dict[str, Any]:
        lobby = await self.get_lobby(guild_id, lobby_id)
        if not lobby:
            raise ValueError("A lobby nem található.")
        target = cfg.TARGET_BY_KEY[str(run["target_key"])]
        members = [m for m in await self.lobby_members(guild_id, lobby_id) if m["status"] == "accepted"]
        settings = await self.get_settings(guild_id)
        passed = sum(1 for result in phase_results if result.get("passed"))
        success = passed >= 2
        reward_pool = int(run["reward_pool"])
        effective_pool = reward_pool if passed == 3 else round(reward_pool * 0.85) if success else 0
        now = self._now()
        payouts: dict[int, int] = {}
        fines: dict[int, int] = {}
        lost_gear: dict[int, str] = {}

        # Atomically claim final settlement. This prevents two fast clicks from
        # paying the same run twice. A resolving run is never treated as runnable.
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                "UPDATE heist_runs SET status='resolving',phase=3,phase_results=? WHERE guild_id=? AND lobby_id=? AND status='running'",
                (json.dumps(phase_results), guild_id, lobby_id),
            )
            if int(cur.rowcount or 0) != 1:
                await conn.rollback()
                raise ValueError("A Nagy Meló lezárása már folyamatban van vagy megtörtént.")
            await conn.execute("UPDATE heist_lobbies SET phase=3 WHERE guild_id=? AND lobby_id=?", (guild_id, lobby_id))
            await conn.commit()

        if success:
            assigned = 0
            for index, member in enumerate(members):
                uid = int(member["user_id"])
                if index == len(members) - 1:
                    payout = max(0, effective_pool - assigned)
                else:
                    payout = max(0, effective_pool * int(member["cut_percent"]) // 100)
                    assigned += payout
                payouts[uid] = payout
                if payout:
                    await self.db.add_wallet(guild_id, uid, payout, f"heist_payout:{target.key}")
                await self.stats.increment(guild_id, uid, "heist.successes")
                await self.stats.add(guild_id, uid, "heist.earned", payout)
                await self.stats.set_max(guild_id, uid, "heist.biggest_payout", payout)
                await self.db.add_progression_xp(guild_id, uid, 500 + 100 * passed, "heist_success")
                if self.factions is not None:
                    await self.factions.add_xp_for_member(guild_id, uid, 180 + 40 * passed, "heist_success")
        else:
            for member in members:
                uid = int(member["user_id"])
                fine = max(0, reward_pool * settings.fine_percent * int(member["cut_percent"]) // 10_000)
                fines[uid] = fine
                if fine:
                    await self.db.add_wallet(guild_id, uid, -fine, f"heist_fine:{target.key}", allow_negative=True)
                    await self.stats.add(guild_id, uid, "heist.fines", fine)
                await self.stats.increment(guild_id, uid, "heist.failures")
                await self.db.add_progression_xp(guild_id, uid, 150, "heist_attempt")
                if settings.jail_minutes > 0:
                    await self.db.set_jail_until(guild_id, uid, now + timedelta(minutes=settings.jail_minutes))
                gear_key = member.get("gear_key")
                if gear_key:
                    rng = random.Random(f"yoru:heist:gear:{guild_id}:{lobby_id}:{uid}:{run['started_at']}")
                    if rng.randint(1, 100) <= settings.gear_loss_percent:
                        async with aiosqlite.connect(self.db.path) as conn:
                            await conn.execute("BEGIN IMMEDIATE")
                            cur = await conn.execute(
                                "SELECT quantity FROM heist_gear WHERE guild_id=? AND user_id=? AND gear_key=?",
                                (guild_id, uid, str(gear_key)),
                            )
                            row = await cur.fetchone()
                            if row and int(row[0]) > 0:
                                await conn.execute(
                                    "UPDATE heist_gear SET quantity=quantity-1 WHERE guild_id=? AND user_id=? AND gear_key=?",
                                    (guild_id, uid, str(gear_key)),
                                )
                                lost_gear[uid] = str(gear_key)
                            await conn.commit()

        status = "success" if success else "failed"
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            await conn.execute(
                """UPDATE heist_runs SET status=?,phase=3,phase_results=?,success=?,total_reward=?,resolved_at=?
                   WHERE guild_id=? AND lobby_id=? AND status='resolving'""",
                (status, json.dumps(phase_results), 1 if success else 0, effective_pool, now.isoformat(), guild_id, lobby_id),
            )
            await conn.execute(
                "UPDATE heist_lobbies SET status='finished',phase=3,resolved_at=? WHERE guild_id=? AND lobby_id=?",
                (now.isoformat(), guild_id, lobby_id),
            )
            await conn.commit()
        result = await self.run_state(guild_id, lobby_id)
        result["payouts"] = payouts
        result["fines"] = fines
        result["lost_gear"] = lost_gear
        return result

    async def advance_phase(self, guild_id: int, lobby_id: int, leader_id: int) -> dict[str, Any]:
        lobby = await self.get_lobby(guild_id, lobby_id)
        if not lobby or int(lobby["leader_id"]) != leader_id:
            raise ValueError("Csak a lobby leadere viheti tovább a fázist.")
        if lobby["status"] != "running":
            raise ValueError("Ez a Nagy Meló jelenleg nem fut.")
        run = await self.run_state(guild_id, lobby_id)
        if not run or run["status"] != "running":
            raise ValueError("A futás már lezárult.")
        phase = int(run["phase"])
        if phase >= 3:
            return run
        phase_key, phase_label = cfg.PHASE_LABELS[phase]
        target = cfg.TARGET_BY_KEY[str(run["target_key"])]
        members = [m for m in await self.lobby_members(guild_id, lobby_id) if m["status"] == "accepted"]
        snapshot = dict(run.get("member_snapshot") or {})
        team_bonus = 0
        for member in members:
            uid = int(member["user_id"])
            team_bonus += self._phase_bonus(str(member.get("role_key") or "support"), member.get("gear_key"), phase_key)
            state = snapshot.get(str(uid), {})
            team_bonus += min(6, int(state.get("activity", 0)) // 20)
            team_bonus += min(5, int(state.get("prestige", 0)))
        team_bonus += max(0, len(members) - target.min_party) * 5
        base_chance = 82 - target.difficulty // 2
        chance = max(18, min(94, base_chance + team_bonus))
        rng = random.Random(f"yoru:heist:phase:{guild_id}:{lobby_id}:{phase}:{run['started_at']}")
        roll = rng.randint(1, 100)
        passed = roll <= chance
        phase_results = list(run.get("phase_results") or [])
        phase_results.append({
            "phase": phase + 1,
            "key": phase_key,
            "label": phase_label,
            "chance": chance,
            "roll": roll,
            "passed": passed,
        })
        new_phase = phase + 1
        if new_phase >= 3:
            return await self._resolve_run(guild_id, lobby_id, run, phase_results)
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                "SELECT phase,status FROM heist_runs WHERE guild_id=? AND lobby_id=? ORDER BY run_id DESC LIMIT 1",
                (guild_id, lobby_id),
            )
            current = await cur.fetchone()
            if not current or int(current[0]) != phase or current[1] != "running":
                await conn.rollback()
                raise ValueError("A fázis állapota közben megváltozott.")
            await conn.execute(
                "UPDATE heist_runs SET phase=?,phase_results=? WHERE guild_id=? AND lobby_id=? AND status='running'",
                (new_phase, json.dumps(phase_results), guild_id, lobby_id),
            )
            await conn.execute(
                "UPDATE heist_lobbies SET phase=? WHERE guild_id=? AND lobby_id=?",
                (new_phase, guild_id, lobby_id),
            )
            await conn.commit()
        return await self.run_state(guild_id, lobby_id)

    async def history(self, guild_id: int, user_id: int, limit: int = 15) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                """SELECT r.run_id,r.lobby_id,r.target_key,r.status,r.success,r.total_reward,r.resolved_at,m.cut_percent
                   FROM heist_runs r JOIN heist_lobby_members m ON m.lobby_id=r.lobby_id AND m.guild_id=r.guild_id
                   WHERE r.guild_id=? AND m.user_id=? AND r.status IN ('success','failed')
                   ORDER BY r.run_id DESC LIMIT ?""",
                (guild_id, user_id, max(1, min(50, int(limit)))),
            )
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def leaderboard(self, guild_id: int, limit: int = 10) -> list[tuple[int, int, int]]:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                """SELECT user_id,
                          MAX(CASE WHEN stat_name='heist.earned' THEN value ELSE 0 END) AS earned,
                          MAX(CASE WHEN stat_name='heist.successes' THEN value ELSE 0 END) AS wins
                   FROM user_statistics
                   WHERE guild_id=? AND stat_name IN ('heist.earned','heist.successes')
                   GROUP BY user_id ORDER BY earned DESC,wins DESC LIMIT ?""",
                (guild_id, max(1, min(25, int(limit)))),
            )
            rows = await cur.fetchall()
        return [(int(uid), int(earned or 0), int(wins or 0)) for uid, earned, wins in rows]
