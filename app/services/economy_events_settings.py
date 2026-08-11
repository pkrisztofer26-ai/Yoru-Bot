from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app import economy_config as eco
from app.database import Database
from app.services.server_settings import ServerSettingsService
from app.ui import set_currency_symbol


ECONOMY_FEATURE_DEFAULTS: dict[str, bool] = {
    "economy": True,
    "daily": True,
    "weekly": True,
    "monthly": True,
    "work": True,
    "crime": True,
    "search": True,
    "beg": True,
    "rob": True,
    "slut": True,
    "bank": True,
    "interest": True,
    "role_income": True,
    "gambling": True,
}

COOLDOWN_DEFAULTS: dict[str, timedelta] = {
    "daily": eco.DAILY_COOLDOWN,
    "weekly": eco.WEEKLY_COOLDOWN,
    "monthly": eco.MONTHLY_COOLDOWN,
    "work": eco.WORK_COOLDOWN,
    "crime": eco.CRIME_COOLDOWN,
    "search": eco.SEARCH_COOLDOWN,
    "beg": eco.BEG_COOLDOWN,
    "rob": eco.ROB_COOLDOWN,
    "slut": eco.SLUT_COOLDOWN,
    "interest": eco.INTEREST_COOLDOWN,
    "role_income": eco.CLAIM_INCOME_COOLDOWN,
}

REWARD_DEFAULTS: dict[str, tuple[int, int]] = {
    "daily": eco.DAILY_REWARD,
    "weekly": eco.WEEKLY_REWARD,
    "monthly": eco.MONTHLY_REWARD,
    "work": eco.WORK_REWARD,
    "crime_reward": eco.CRIME_REWARD,
    "crime_fine": eco.CRIME_FINE,
    "slut_reward": eco.SLUT_REWARD,
    "slut_fine": eco.SLUT_FINE,
}

ECONOMY_FEATURE_LABELS: dict[str, str] = {
    "economy": "Economy",
    "daily": "Daily",
    "weekly": "Weekly",
    "monthly": "Monthly",
    "work": "Work",
    "crime": "Crime",
    "search": "Search",
    "beg": "Beg",
    "rob": "Rob",
    "slut": "Slut",
    "bank": "Bank",
    "interest": "Interest",
    "role_income": "Role Income",
    "gambling": "Gambling",
}


@dataclass(frozen=True, slots=True)
class EventRuntimeConfig:
    auto_enabled: bool
    safe_enabled: bool
    bomb_enabled: bool
    manual_enabled: bool
    channel_id: int | None
    min_hours: float
    max_hours: float
    join_seconds: int
    safe_min_reward: int
    safe_max_reward: int
    bomb_min_entry: int
    bomb_max_entry: int
    bomb_round_seconds: int
    activity_messages: int
    activity_window_minutes: int
    activity_min_users: int
    activity_user_cooldown_seconds: int
    safe_chance: float


class EconomyEventsSettingsService:
    """Per-guild Economy + Events configuration using the existing guild_state table.

    No schema migration is required; missing keys always fall back to Yoru's
    existing v3.10.1 balance/config values so upgrading does not change behaviour.
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        self.state = ServerSettingsService(db)

    async def _get_int_default(self, guild_id: int, key: str, default: int) -> int:
        value = await self.state.get_int(guild_id, key)
        return int(default if value is None else value)

    async def _get_float_default(self, guild_id: int, key: str, default: float) -> float:
        raw = await self.db.get_guild_state(guild_id, key)
        if raw is None or not str(raw).strip():
            return float(default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return float(default)

    async def _set_float(self, guild_id: int, key: str, value: float) -> None:
        await self.db.set_guild_state(guild_id, key, f"{float(value):g}")

    # -------------------- Economy --------------------

    async def get_economy_enabled(self, guild_id: int) -> bool:
        return await self.state.get_bool(guild_id, "economy_enabled", True)

    async def set_economy_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.state.set_bool(guild_id, "economy_enabled", enabled)

    async def get_feature_enabled(self, guild_id: int, feature: str) -> bool:
        if feature not in ECONOMY_FEATURE_DEFAULTS:
            raise ValueError(f"Ismeretlen economy feature: {feature}")
        if feature == "economy":
            return await self.get_economy_enabled(guild_id)
        return await self.state.get_bool(
            guild_id,
            f"economy_feature_{feature}",
            ECONOMY_FEATURE_DEFAULTS[feature],
        )

    async def set_feature_enabled(self, guild_id: int, feature: str, enabled: bool) -> None:
        if feature not in ECONOMY_FEATURE_DEFAULTS or feature == "economy":
            if feature == "economy":
                return await self.set_economy_enabled(guild_id, enabled)
            raise ValueError(f"Ismeretlen economy feature: {feature}")
        await self.state.set_bool(guild_id, f"economy_feature_{feature}", enabled)

    async def require_feature(self, guild_id: int, feature: str) -> None:
        if not await self.get_economy_enabled(guild_id):
            raise ValueError("A szerver economy rendszere jelenleg ki van kapcsolva.")
        if feature != "economy" and not await self.get_feature_enabled(guild_id, feature):
            label = ECONOMY_FEATURE_LABELS.get(feature, feature)
            raise ValueError(f"A(z) {label} funkció ezen a szerveren ki van kapcsolva.")

    ECONOMY_CHANNELS_KEY = "economy_allowed_channel_ids"
    ECONOMY_CATEGORIES_KEY = "economy_allowed_category_ids"

    @staticmethod
    def _clean_id_list(values: list) -> list[int]:
        cleaned: list[int] = []
        for raw in values:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if value > 0 and value not in cleaned:
                cleaned.append(value)
        return cleaned[:100]

    async def get_economy_channel_ids(self, guild_id: int) -> list[int]:
        """Return the allowlisted economy channels.

        v3.11.0 only stored a single ``economy_channel_id``. If the new list has
        never been configured, transparently expose that legacy channel as the
        first allowlisted channel. An explicitly stored empty list means
        unrestricted usage and does not fall back to the old key.
        """
        raw = await self.db.get_guild_state(guild_id, self.ECONOMY_CHANNELS_KEY)
        if raw is not None and raw.strip():
            return self._clean_id_list(await self.state.get_list(guild_id, self.ECONOMY_CHANNELS_KEY))
        if raw is not None:  # explicitly cleared: [] / blank means unrestricted
            return []
        legacy = await self.state.get_int(guild_id, "economy_channel_id")
        return [legacy] if legacy else []

    async def get_economy_category_ids(self, guild_id: int) -> list[int]:
        raw = await self.db.get_guild_state(guild_id, self.ECONOMY_CATEGORIES_KEY)
        if raw is None:
            return []
        return self._clean_id_list(await self.state.get_list(guild_id, self.ECONOMY_CATEGORIES_KEY))

    async def set_economy_channel_ids(self, guild_id: int, channel_ids: list[int]) -> None:
        values = self._clean_id_list(channel_ids)
        await self.state.set_list(guild_id, self.ECONOMY_CHANNELS_KEY, values)
        # Keep the legacy key synchronized for older code/builds, but the list is
        # authoritative once it exists.
        await self.state.set_int(guild_id, "economy_channel_id", values[0] if values else None)

    async def set_economy_category_ids(self, guild_id: int, category_ids: list[int]) -> None:
        await self.state.set_list(guild_id, self.ECONOMY_CATEGORIES_KEY, self._clean_id_list(category_ids))

    async def add_economy_channel_id(self, guild_id: int, channel_id: int) -> list[int]:
        values = await self.get_economy_channel_ids(guild_id)
        if int(channel_id) not in values:
            values.append(int(channel_id))
        await self.set_economy_channel_ids(guild_id, values)
        return values

    async def remove_economy_channel_id(self, guild_id: int, channel_id: int) -> list[int]:
        values = [value for value in await self.get_economy_channel_ids(guild_id) if value != int(channel_id)]
        await self.set_economy_channel_ids(guild_id, values)
        return values

    async def add_economy_category_id(self, guild_id: int, category_id: int) -> list[int]:
        values = await self.get_economy_category_ids(guild_id)
        if int(category_id) not in values:
            values.append(int(category_id))
        await self.set_economy_category_ids(guild_id, values)
        return values

    async def remove_economy_category_id(self, guild_id: int, category_id: int) -> list[int]:
        values = [value for value in await self.get_economy_category_ids(guild_id) if value != int(category_id)]
        await self.set_economy_category_ids(guild_id, values)
        return values

    async def clear_economy_locations(self, guild_id: int) -> None:
        await self.set_economy_channel_ids(guild_id, [])
        await self.set_economy_category_ids(guild_id, [])

    # Backwards-compatible single-channel API. New UI uses the list helpers.
    async def get_economy_channel_id(self, guild_id: int) -> int | None:
        values = await self.get_economy_channel_ids(guild_id)
        return values[0] if values else None

    async def set_economy_channel_id(self, guild_id: int, channel_id: int | None) -> None:
        await self.set_economy_channel_ids(guild_id, [channel_id] if channel_id else [])

    async def require_channel(
        self,
        guild_id: int,
        channel_id: int | None,
        category_id: int | None = None,
    ) -> None:
        channels = await self.get_economy_channel_ids(guild_id)
        categories = await self.get_economy_category_ids(guild_id)
        if not channels and not categories:
            return
        if channel_id is not None and int(channel_id) in channels:
            return
        if category_id is not None and int(category_id) in categories:
            return
        allowed = [*(f"<#{cid}>" for cid in channels), *(f"<#{cid}> (kategória)" for cid in categories)]
        where = ", ".join(allowed[:12])
        if len(allowed) > 12:
            where += f" +{len(allowed) - 12} további"
        raise ValueError(f"Az economy parancsokat csak az engedélyezett helyeken használhatod: {where}")

    async def prepare_currency(self, guild_id: int) -> str:
        symbol = await self.get_currency_symbol(guild_id)
        set_currency_symbol(symbol)
        return symbol

    async def get_currency_name(self, guild_id: int) -> str:
        value = (await self.state.get_text(guild_id, "economy_currency_name", "Yoru Dollar")).strip()
        return value[:32] or "Yoru Dollar"

    async def set_currency_name(self, guild_id: int, value: str) -> None:
        value = value.strip()
        if not value:
            raise ValueError("A pénznem neve nem lehet üres.")
        await self.state.set_text(guild_id, "economy_currency_name", value, max_length=32)

    async def get_currency_symbol(self, guild_id: int) -> str:
        value = (await self.state.get_text(guild_id, "economy_currency_symbol", "$" )).strip()
        return value[:12] or "$"

    async def set_currency_symbol(self, guild_id: int, value: str) -> None:
        value = value.strip()
        if not value:
            raise ValueError("A pénznem jele/emoji nem lehet üres.")
        if len(value) > 12:
            raise ValueError("A pénznem jele/emoji maximum 12 karakter lehet.")
        await self.state.set_text(guild_id, "economy_currency_symbol", value, max_length=12)

    async def get_cooldown(self, guild_id: int, feature: str) -> timedelta:
        if feature not in COOLDOWN_DEFAULTS:
            raise ValueError(f"Ismeretlen cooldown: {feature}")
        default_seconds = max(1, int(COOLDOWN_DEFAULTS[feature].total_seconds()))
        seconds = await self._get_int_default(guild_id, f"economy_cooldown_{feature}_seconds", default_seconds)
        return timedelta(seconds=max(1, min(seconds, 365 * 24 * 3600)))

    async def set_cooldown_seconds(self, guild_id: int, feature: str, seconds: int | None) -> None:
        if feature not in COOLDOWN_DEFAULTS:
            raise ValueError(f"Ismeretlen cooldown: {feature}")
        if seconds is None:
            await self.state.set_int(guild_id, f"economy_cooldown_{feature}_seconds", None)
            return
        if seconds < 1 or seconds > 365 * 24 * 3600:
            raise ValueError("A cooldown 1 másodperc és 365 nap között lehet.")
        await self.state.set_int(guild_id, f"economy_cooldown_{feature}_seconds", int(seconds))

    async def reset_all_cooldowns(self, guild_id: int) -> None:
        for feature in COOLDOWN_DEFAULTS:
            await self.set_cooldown_seconds(guild_id, feature, None)

    async def get_reward_range(self, guild_id: int, key: str) -> tuple[int, int]:
        if key not in REWARD_DEFAULTS:
            raise ValueError(f"Ismeretlen reward range: {key}")
        default_min, default_max = REWARD_DEFAULTS[key]
        minimum = await self._get_int_default(guild_id, f"economy_reward_{key}_min", default_min)
        maximum = await self._get_int_default(guild_id, f"economy_reward_{key}_max", default_max)
        if minimum < 0 or maximum < minimum:
            return default_min, default_max
        return minimum, maximum

    async def set_reward_range(self, guild_id: int, key: str, minimum: int | None, maximum: int | None) -> None:
        if key not in REWARD_DEFAULTS:
            raise ValueError(f"Ismeretlen reward range: {key}")
        if minimum is None or maximum is None:
            await self.state.set_int(guild_id, f"economy_reward_{key}_min", None)
            await self.state.set_int(guild_id, f"economy_reward_{key}_max", None)
            return
        if minimum < 0 or maximum < minimum:
            raise ValueError("A minimum nem lehet negatív, a maximum pedig nem lehet kisebb a minimumnál.")
        if maximum > 10**15:
            raise ValueError("A reward maximum túl nagy. Maximum 1 quadrillion állítható be egy jutalomra.")
        await self.state.set_int(guild_id, f"economy_reward_{key}_min", int(minimum))
        await self.state.set_int(guild_id, f"economy_reward_{key}_max", int(maximum))

    async def reset_all_reward_ranges(self, guild_id: int) -> None:
        for key in REWARD_DEFAULTS:
            await self.set_reward_range(guild_id, key, None, None)

    async def get_rob_share(self, guild_id: int) -> float:
        raw = await self._get_float_default(guild_id, "economy_rob_success_share", eco.ROB_SUCCESS_SHARE)
        return max(0.01, min(1.0, raw))

    async def set_rob_share(self, guild_id: int, share: float | None) -> None:
        if share is None:
            await self.db.set_guild_state(guild_id, "economy_rob_success_share", "")
            return
        if share < 0.01 or share > 1.0:
            raise ValueError("A Rob zsákmány százaléka 1% és 100% között lehet.")
        await self._set_float(guild_id, "economy_rob_success_share", share)

    async def get_gambling_payout_multiplier(self, guild_id: int) -> float:
        raw = await self._get_float_default(guild_id, "economy_gambling_payout_multiplier", 1.0)
        return max(0.25, min(3.0, raw))

    async def set_gambling_payout_multiplier(self, guild_id: int, value: float | None) -> None:
        if value is None:
            await self.db.set_guild_state(guild_id, "economy_gambling_payout_multiplier", "")
            return
        if value < 0.25 or value > 3.0:
            raise ValueError("A gambling payout szorzó 0.25× és 3.00× között lehet.")
        await self._set_float(guild_id, "economy_gambling_payout_multiplier", value)

    async def reset_economy_advanced(self, guild_id: int) -> None:
        await self.set_rob_share(guild_id, None)
        await self.set_gambling_payout_multiplier(guild_id, None)
        await self.db.set_guild_state(guild_id, "economy_currency_name", "")
        await self.db.set_guild_state(guild_id, "economy_currency_symbol", "")

    async def reset_economy_all(self, guild_id: int) -> None:
        await self.db.set_guild_state(guild_id, "economy_enabled", "")
        for feature in ECONOMY_FEATURE_DEFAULTS:
            if feature != "economy":
                await self.db.set_guild_state(guild_id, f"economy_feature_{feature}", "")
        await self.clear_economy_locations(guild_id)
        await self.reset_all_cooldowns(guild_id)
        await self.reset_all_reward_ranges(guild_id)
        await self.reset_economy_advanced(guild_id)

    # -------------------- Events --------------------

    async def get_event_config(self, guild_id: int, fallback) -> EventRuntimeConfig:
        fallback_channel = getattr(fallback, "event_channel_id", None)
        stored_channel = await self.state.get_int(guild_id, "events_channel_id")
        channel_id = fallback_channel if stored_channel is None else (None if stored_channel == 0 else stored_channel)

        auto_enabled = await self.state.get_bool(
            guild_id, "events_auto_enabled", bool(getattr(fallback, "auto_events_enabled", True))
        )
        safe_enabled = await self.state.get_bool(guild_id, "events_safe_enabled", True)
        bomb_enabled = await self.state.get_bool(guild_id, "events_bomb_enabled", True)
        manual_enabled = await self.state.get_bool(guild_id, "events_manual_enabled", True)

        min_hours = await self._get_float_default(
            guild_id, "events_min_hours", float(getattr(fallback, "auto_event_min_hours", eco.AUTO_EVENT_MIN_SECONDS / 3600))
        )
        max_hours = await self._get_float_default(
            guild_id, "events_max_hours", float(getattr(fallback, "auto_event_max_hours", eco.AUTO_EVENT_MAX_SECONDS / 3600))
        )
        if min_hours <= 0 or max_hours < min_hours:
            min_hours = float(getattr(fallback, "auto_event_min_hours", eco.AUTO_EVENT_MIN_SECONDS / 3600))
            max_hours = float(getattr(fallback, "auto_event_max_hours", eco.AUTO_EVENT_MAX_SECONDS / 3600))

        join_seconds = await self._get_int_default(
            guild_id, "events_join_seconds", int(getattr(fallback, "auto_join_seconds", eco.AUTO_EVENT_JOIN_SECONDS))
        )
        safe_min = await self._get_int_default(
            guild_id, "events_safe_min_reward", int(getattr(fallback, "auto_safe_min_reward", eco.AUTO_SAFE_MIN_REWARD))
        )
        safe_max = await self._get_int_default(
            guild_id, "events_safe_max_reward", int(getattr(fallback, "auto_safe_max_reward", eco.AUTO_SAFE_MAX_REWARD))
        )
        bomb_min = await self._get_int_default(
            guild_id, "events_bomb_min_entry", int(getattr(fallback, "auto_bomb_min_entry", eco.AUTO_BOMB_MIN_ENTRY))
        )
        bomb_max = await self._get_int_default(
            guild_id, "events_bomb_max_entry", int(getattr(fallback, "auto_bomb_max_entry", eco.AUTO_BOMB_MAX_ENTRY))
        )
        round_seconds = await self._get_int_default(
            guild_id, "events_bomb_round_seconds", int(getattr(fallback, "auto_bomb_round_seconds", eco.AUTO_BOMB_ROUND_SECONDS))
        )
        activity_messages = await self._get_int_default(
            guild_id, "events_activity_messages", int(getattr(fallback, "auto_event_activity_messages", eco.AUTO_EVENT_ACTIVITY_MESSAGES))
        )
        activity_window = await self._get_int_default(
            guild_id, "events_activity_window_minutes", int(getattr(fallback, "auto_event_activity_window_minutes", eco.AUTO_EVENT_ACTIVITY_WINDOW_MINUTES))
        )
        activity_users = await self._get_int_default(
            guild_id, "events_activity_min_users", int(getattr(fallback, "auto_event_activity_min_users", eco.AUTO_EVENT_ACTIVITY_MIN_USERS))
        )
        activity_user_cd = await self._get_int_default(
            guild_id,
            "events_activity_user_cooldown_seconds",
            int(getattr(fallback, "auto_event_activity_user_cooldown_seconds", eco.AUTO_EVENT_ACTIVITY_USER_COOLDOWN_SECONDS)),
        )
        safe_chance = await self._get_float_default(guild_id, "events_safe_chance", eco.AUTO_EVENT_SAFE_CHANCE)

        return EventRuntimeConfig(
            auto_enabled=auto_enabled,
            safe_enabled=safe_enabled,
            bomb_enabled=bomb_enabled,
            manual_enabled=manual_enabled,
            channel_id=channel_id,
            min_hours=max(1 / 60, min(min_hours, 24 * 30)),
            max_hours=max(max(1 / 60, min(min_hours, 24 * 30)), min(max_hours, 24 * 30)),
            join_seconds=max(eco.EVENT_JOIN_MIN_SECONDS, min(join_seconds, eco.EVENT_JOIN_MAX_SECONDS)),
            safe_min_reward=max(eco.EVENT_MIN_REWARD, safe_min),
            safe_max_reward=max(max(eco.EVENT_MIN_REWARD, safe_min), safe_max),
            bomb_min_entry=max(eco.BOMB_MIN_ENTRY, bomb_min),
            bomb_max_entry=max(max(eco.BOMB_MIN_ENTRY, bomb_min), bomb_max),
            bomb_round_seconds=max(eco.BOMB_ROUND_MIN_SECONDS, min(round_seconds, eco.BOMB_ROUND_MAX_SECONDS)),
            activity_messages=max(1, activity_messages),
            activity_window_minutes=max(1, min(activity_window, 24 * 60)),
            activity_min_users=max(1, min(activity_users, max(1, activity_messages))),
            activity_user_cooldown_seconds=max(0, min(activity_user_cd, 3600)),
            safe_chance=max(0.0, min(1.0, safe_chance)),
        )

    async def set_event_channel_id(self, guild_id: int, channel_id: int | None) -> None:
        # 0 = explicit disabled/cleared; blank = inherit legacy .env default.
        await self.state.set_int(guild_id, "events_channel_id", 0 if channel_id is None else channel_id)

    async def set_event_toggle(self, guild_id: int, key: str, enabled: bool) -> None:
        if key not in {"auto", "safe", "bomb", "manual"}:
            raise ValueError("Ismeretlen event kapcsoló.")
        await self.state.set_bool(guild_id, f"events_{key}_enabled", enabled)

    async def set_event_timing(
        self,
        guild_id: int,
        *,
        min_hours: float,
        max_hours: float,
        join_seconds: int,
        bomb_round_seconds: int,
    ) -> None:
        if min_hours < 1 / 60 or min_hours > 24 * 30:
            raise ValueError("A minimum intervallum 1 perc és 30 nap között lehet.")
        if max_hours < min_hours or max_hours > 24 * 30:
            raise ValueError("A maximum intervallum nem lehet kisebb a minimumnál, és legfeljebb 30 nap lehet.")
        if not eco.EVENT_JOIN_MIN_SECONDS <= join_seconds <= eco.EVENT_JOIN_MAX_SECONDS:
            raise ValueError(f"A nevezési idő {eco.EVENT_JOIN_MIN_SECONDS}–{eco.EVENT_JOIN_MAX_SECONDS} másodperc lehet.")
        if not eco.BOMB_ROUND_MIN_SECONDS <= bomb_round_seconds <= eco.BOMB_ROUND_MAX_SECONDS:
            raise ValueError(f"A HH köridő {eco.BOMB_ROUND_MIN_SECONDS}–{eco.BOMB_ROUND_MAX_SECONDS} másodperc lehet.")
        await self._set_float(guild_id, "events_min_hours", min_hours)
        await self._set_float(guild_id, "events_max_hours", max_hours)
        await self.state.set_int(guild_id, "events_join_seconds", join_seconds)
        await self.state.set_int(guild_id, "events_bomb_round_seconds", bomb_round_seconds)

    async def set_event_activity(
        self,
        guild_id: int,
        *,
        messages: int,
        min_users: int,
        window_minutes: int,
        user_cooldown_seconds: int,
    ) -> None:
        if messages < 1 or messages > 100_000:
            raise ValueError("Az activity üzenetszám 1–100000 között lehet.")
        if min_users < 1 or min_users > messages:
            raise ValueError("A minimum user 1 és az üzenetküszöb között lehet.")
        if window_minutes < 1 or window_minutes > 24 * 60:
            raise ValueError("Az activity ablak 1–1440 perc között lehet.")
        if user_cooldown_seconds < 0 or user_cooldown_seconds > 3600:
            raise ValueError("Az user activity cooldown 0–3600 másodperc között lehet.")
        await self.state.set_int(guild_id, "events_activity_messages", messages)
        await self.state.set_int(guild_id, "events_activity_min_users", min_users)
        await self.state.set_int(guild_id, "events_activity_window_minutes", window_minutes)
        await self.state.set_int(guild_id, "events_activity_user_cooldown_seconds", user_cooldown_seconds)

    async def set_event_rewards(
        self,
        guild_id: int,
        *,
        safe_min: int,
        safe_max: int,
        bomb_min: int,
        bomb_max: int,
        safe_chance: float,
    ) -> None:
        if safe_min < eco.EVENT_MIN_REWARD or safe_max < safe_min:
            raise ValueError(f"A Láda minimum legalább {eco.EVENT_MIN_REWARD:,}, a maximum pedig nem lehet kisebb.".replace(",", " "))
        if bomb_min < eco.BOMB_MIN_ENTRY or bomb_max < bomb_min:
            raise ValueError(f"A HH belépő minimum legalább {eco.BOMB_MIN_ENTRY:,}, a maximum pedig nem lehet kisebb.".replace(",", " "))
        if safe_max > 10**15 or bomb_max > 10**15:
            raise ValueError("Az event pénzérték maximum 1 quadrillion lehet.")
        if safe_chance < 0 or safe_chance > 1:
            raise ValueError("A Láda esély 0 és 1 között legyen.")
        await self.state.set_int(guild_id, "events_safe_min_reward", safe_min)
        await self.state.set_int(guild_id, "events_safe_max_reward", safe_max)
        await self.state.set_int(guild_id, "events_bomb_min_entry", bomb_min)
        await self.state.set_int(guild_id, "events_bomb_max_entry", bomb_max)
        await self._set_float(guild_id, "events_safe_chance", safe_chance)

    async def reset_events_all(self, guild_id: int) -> None:
        keys = [
            "events_auto_enabled", "events_safe_enabled", "events_bomb_enabled", "events_manual_enabled",
            "events_channel_id", "events_min_hours", "events_max_hours", "events_join_seconds",
            "events_safe_min_reward", "events_safe_max_reward", "events_bomb_min_entry",
            "events_bomb_max_entry", "events_bomb_round_seconds", "events_activity_messages",
            "events_activity_window_minutes", "events_activity_min_users",
            "events_activity_user_cooldown_seconds", "events_safe_chance",
        ]
        for key in keys:
            await self.db.set_guild_state(guild_id, key, "")
