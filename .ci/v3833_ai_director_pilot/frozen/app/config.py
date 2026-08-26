from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

from app import economy_config as eco

load_dotenv()


_TRUE_VALUES = {"1", "true", "yes", "on", "igen"}
_FALSE_VALUES = {"0", "false", "no", "off", "nem"}


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise RuntimeError(
        f"A {name} logikai érték legyen: true/false, 1/0, yes/no, on/off vagy igen/nem."
    )


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return int(default)
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise RuntimeError(f"A {name} csak egész szám lehet.") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return float(default)
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise RuntimeError(f"A {name} csak szám lehet.") from exc


def _optional_snowflake(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    value = raw.strip()
    if not value.isdigit() or int(value) <= 0:
        raise RuntimeError(
            f"A {name} Discord ID legyen pozitív egész szám, vagy hagyd üresen."
        )
    return int(value)


@dataclass(frozen=True)
class Settings:
    discord_token: str
    test_guild_id: int | None
    ai_director_pilot_enabled: bool
    starting_balance: int
    event_channel_id: int | None
    auto_events_enabled: bool
    auto_event_min_hours: float
    auto_event_max_hours: float
    auto_join_seconds: int
    auto_safe_min_reward: int
    auto_safe_max_reward: int
    auto_bomb_min_entry: int
    auto_bomb_max_entry: int
    auto_bomb_round_seconds: int
    auto_event_activity_messages: int
    auto_event_activity_window_minutes: int
    auto_event_activity_min_users: int
    auto_event_activity_user_cooldown_seconds: int
    database_path: str = "data/vaultbot.db"


def load_settings() -> Settings:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == "IDE_JON_A_BOT_TOKEN":
        raise RuntimeError("A DISCORD_TOKEN nincs beállítva a .env fájlban.")

    # A malformed TEST_GUILD_ID must never silently become None: that would
    # switch command synchronization from the intended test guild to GLOBAL.
    guild_id = _optional_snowflake("TEST_GUILD_ID")
    ai_director_pilot_enabled = env_bool("YORU_AI_DIRECTOR_PILOT_ENABLED", False)
    if ai_director_pilot_enabled and guild_id is None:
        raise RuntimeError(
            "A YORU_AI_DIRECTOR_PILOT_ENABLED csak explicit TEST_GUILD_ID mellett kapcsolható be."
        )
    event_channel_id = _optional_snowflake("EVENT_CHANNEL_ID")

    # Install-level fallback only. Per-guild `/settings` values in guild_state
    # are authoritative at runtime; the old STARTING_BALANCE env is ignored.
    starting_balance = eco.STARTING_BALANCE

    min_hours = _env_float("AUTO_EVENT_MIN_HOURS", eco.AUTO_EVENT_MIN_SECONDS / 3600)
    max_hours = _env_float("AUTO_EVENT_MAX_HOURS", eco.AUTO_EVENT_MAX_SECONDS / 3600)
    if min_hours <= 0 or max_hours < min_hours:
        raise RuntimeError("Az automatikus event időintervalluma érvénytelen.")

    # These remain install-level fallbacks. Runtime per-guild Event settings
    # override them through Yoru's DB-backed settings panel.
    safe_min = eco.AUTO_SAFE_MIN_REWARD
    safe_max = eco.AUTO_SAFE_MAX_REWARD
    bomb_min = eco.AUTO_BOMB_MIN_ENTRY
    bomb_max = eco.AUTO_BOMB_MAX_ENTRY
    if (
        safe_min < eco.EVENT_MIN_REWARD
        or safe_max < safe_min
        or bomb_min < eco.BOMB_MIN_ENTRY
        or bomb_max < bomb_min
    ):
        raise RuntimeError(
            "Az automatikus event jutalom/belépő tartománya érvénytelen "
            f"(Láda min: {eco.EVENT_MIN_REWARD}, HH min: {eco.BOMB_MIN_ENTRY})."
        )

    join_seconds = _env_int("AUTO_JOIN_SECONDS", eco.AUTO_EVENT_JOIN_SECONDS)
    bomb_round_seconds = _env_int("AUTO_BOMB_ROUND_SECONDS", eco.AUTO_BOMB_ROUND_SECONDS)
    if not eco.EVENT_JOIN_MIN_SECONDS <= join_seconds <= eco.EVENT_JOIN_MAX_SECONDS:
        raise RuntimeError(
            f"Az AUTO_JOIN_SECONDS {eco.EVENT_JOIN_MIN_SECONDS} és "
            f"{eco.EVENT_JOIN_MAX_SECONDS} másodperc között legyen."
        )
    if not eco.BOMB_ROUND_MIN_SECONDS <= bomb_round_seconds <= eco.BOMB_ROUND_MAX_SECONDS:
        raise RuntimeError(
            f"Az AUTO_BOMB_ROUND_SECONDS {eco.BOMB_ROUND_MIN_SECONDS} és "
            f"{eco.BOMB_ROUND_MAX_SECONDS} másodperc között legyen."
        )

    activity_messages = _env_int("AUTO_EVENT_ACTIVITY_MESSAGES", eco.AUTO_EVENT_ACTIVITY_MESSAGES)
    activity_window_minutes = _env_int(
        "AUTO_EVENT_ACTIVITY_WINDOW_MINUTES", eco.AUTO_EVENT_ACTIVITY_WINDOW_MINUTES
    )
    activity_min_users = _env_int("AUTO_EVENT_ACTIVITY_MIN_USERS", eco.AUTO_EVENT_ACTIVITY_MIN_USERS)
    activity_user_cooldown = _env_int(
        "AUTO_EVENT_ACTIVITY_USER_COOLDOWN_SECONDS",
        eco.AUTO_EVENT_ACTIVITY_USER_COOLDOWN_SECONDS,
    )
    if activity_messages < 1:
        raise RuntimeError("Az AUTO_EVENT_ACTIVITY_MESSAGES legalább 1 legyen.")
    if activity_window_minutes < 1:
        raise RuntimeError("Az AUTO_EVENT_ACTIVITY_WINDOW_MINUTES legalább 1 legyen.")
    if activity_min_users < 1 or activity_min_users > activity_messages:
        raise RuntimeError(
            "Az AUTO_EVENT_ACTIVITY_MIN_USERS legalább 1 legyen, és nem lehet több az üzenetküszöbnél."
        )
    if activity_user_cooldown < 0:
        raise RuntimeError("Az AUTO_EVENT_ACTIVITY_USER_COOLDOWN_SECONDS nem lehet negatív.")

    return Settings(
        discord_token=token,
        test_guild_id=guild_id,
        ai_director_pilot_enabled=ai_director_pilot_enabled,
        starting_balance=starting_balance,
        event_channel_id=event_channel_id,
        auto_events_enabled=env_bool("AUTO_EVENTS_ENABLED", True),
        auto_event_min_hours=min_hours,
        auto_event_max_hours=max_hours,
        auto_join_seconds=join_seconds,
        auto_safe_min_reward=safe_min,
        auto_safe_max_reward=safe_max,
        auto_bomb_min_entry=bomb_min,
        auto_bomb_max_entry=bomb_max,
        auto_bomb_round_seconds=bomb_round_seconds,
        auto_event_activity_messages=activity_messages,
        auto_event_activity_window_minutes=activity_window_minutes,
        auto_event_activity_min_users=activity_min_users,
        auto_event_activity_user_cooldown_seconds=activity_user_cooldown,
    )
