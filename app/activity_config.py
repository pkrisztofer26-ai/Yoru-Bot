from __future__ import annotations

# Per-guild setting keys. All values live in the existing guild_state backend so
# future releases/dashboard use the exact same persisted configuration.
ACTIVITY_ENABLED_KEY = "activity_enabled"
ACTIVITY_CHAT_ENABLED_KEY = "activity_chat_enabled"
ACTIVITY_VOICE_ENABLED_KEY = "activity_voice_enabled"
ACTIVITY_LEVELUP_CHANNEL_KEY = "activity_levelup_channel_id"
ACTIVITY_EXCLUDE_SELF_DEAF_KEY = "activity_exclude_self_deaf"
ACTIVITY_CHAT_XP_MIN_KEY = "activity_chat_xp_min"
ACTIVITY_CHAT_XP_MAX_KEY = "activity_chat_xp_max"
ACTIVITY_CHAT_XP_COOLDOWN_KEY = "activity_chat_xp_cooldown_seconds"
ACTIVITY_MESSAGE_MIN_INTERVAL_KEY = "activity_message_min_interval_seconds"
ACTIVITY_DUPLICATE_WINDOW_KEY = "activity_duplicate_window_seconds"
ACTIVITY_MIN_MESSAGE_ALNUM_KEY = "activity_min_message_alnum"
ACTIVITY_VOICE_XP_PER_MINUTE_KEY = "activity_voice_xp_per_minute"
ACTIVITY_MILESTONES_KEY = "activity_milestones"
ACTIVITY_MILESTONE_LAYOUT_KEY = "activity_milestone_layout"
ACTIVITY_MILESTONE_LAYOUT_VERSION_KEY = "activity_milestone_layout_version"
ACTIVITY_RETIRED_ROLE_IDS_KEY = "activity_retired_role_ids"

ACTIVITY_DEFAULT_ENABLED = True
ACTIVITY_DEFAULT_CHAT_ENABLED = True
ACTIVITY_DEFAULT_VOICE_ENABLED = True
ACTIVITY_DEFAULT_EXCLUDE_SELF_DEAF = True

# Chat anti-farm defaults agreed during the Activity design.
ACTIVITY_DEFAULT_CHAT_XP_MIN = 12
ACTIVITY_DEFAULT_CHAT_XP_MAX = 20
ACTIVITY_DEFAULT_CHAT_XP_COOLDOWN_SECONDS = 60
ACTIVITY_DEFAULT_MESSAGE_MIN_INTERVAL_SECONDS = 8
ACTIVITY_DUPLICATE_WINDOW_SECONDS = 300
ACTIVITY_MIN_MESSAGE_ALNUM = 3

# Voice XP is awarded once per qualifying minute.
ACTIVITY_DEFAULT_VOICE_XP_PER_MINUTE = 3
ACTIVITY_VOICE_TICK_SECONDS = 60

# Tuning safety clamps. These are not balance caps on rewards/economy; they only
# prevent accidentally configuring an unusable Activity tracker.
ACTIVITY_CHAT_XP_MIN_LIMIT = 1
ACTIVITY_CHAT_XP_MAX_LIMIT = 500
ACTIVITY_CHAT_COOLDOWN_MIN = 10
ACTIVITY_CHAT_COOLDOWN_MAX = 900
ACTIVITY_MESSAGE_INTERVAL_MIN = 2
ACTIVITY_MESSAGE_INTERVAL_MAX = 120
ACTIVITY_DUPLICATE_WINDOW_MIN = 0
ACTIVITY_DUPLICATE_WINDOW_MAX = 86_400
ACTIVITY_MIN_MESSAGE_ALNUM_MIN = 1
ACTIVITY_MIN_MESSAGE_ALNUM_MAX = 100
ACTIVITY_VOICE_XP_MIN = 1
ACTIVITY_VOICE_XP_MAX = 100

# First-install Activity template. Since v3.17.5 the live ladder is fully dynamic
# and stored per guild in the DB; this tuple is used only when a guild has never
# initialized Activity milestones before.
ACTIVITY_MILESTONE_LAYOUT_VERSION = 3
ACTIVITY_DEFAULT_MILESTONES: tuple[tuple[int, str], ...] = (
    (5, "Csöves"),
    (10, "Pórnép"),
    (15, "Közmunkás"),
    (20, "Minimálbéres"),
    (30, "Melós"),
    (40, "Szakmunkás"),
    (50, "Maszekos"),
    (60, "Kft.-tulaj"),
    (75, "Vállalkozó"),
    (90, "Nagyvállalkozó"),
    (110, "Újgazdag"),
    (130, "Stróman"),
    (150, "Oligarcha"),
    (175, "Felső tízezer"),
    (200, "NER-elit"),
)
ACTIVITY_MILESTONE_LEVELS = tuple(level for level, _name in ACTIVITY_DEFAULT_MILESTONES)
ACTIVITY_MAX_MILESTONES = 200
ACTIVITY_MAX_MILESTONE_LEVEL = 10_000
ACTIVITY_DEFAULT_ROLE_COLOR = 0x8B5CF6


def xp_for_level(level: int) -> int:
    """Total Activity XP required for a level.

    The curve intentionally keeps the earlier v3.12 pacing target where
    Activity Level 40 is about 85,800 XP. It is independent from economy XP.
    """
    level = max(0, int(level))
    return 50 * level * level + 145 * level


def level_for_xp(total_xp: int) -> int:
    total_xp = max(0, int(total_xp))
    # Levels safely continue beyond every configured milestone.
    low, high = 0, 1
    while xp_for_level(high) <= total_xp:
        high *= 2
    while low + 1 < high:
        mid = (low + high) // 2
        if xp_for_level(mid) <= total_xp:
            low = mid
        else:
            high = mid
    return low


def level_progress(total_xp: int) -> tuple[int, int, int, int]:
    level = level_for_xp(total_xp)
    start = xp_for_level(level)
    end = xp_for_level(level + 1)
    current = max(0, int(total_xp) - start)
    needed = max(1, end - start)
    percent = min(100, int(current / needed * 100))
    return level, current, needed, percent


def default_milestone_layout() -> list[dict[str, int | str]]:
    return [{"level": level, "role_name": name} for level, name in ACTIVITY_DEFAULT_MILESTONES]


def default_milestones() -> list[dict[str, int | str | bool | None]]:
    return [
        {
            "level": level,
            "role_id": None,
            "role_name": name,
            "hourly_income": 0,
            "role_color": ACTIVITY_DEFAULT_ROLE_COLOR,
            "role_hoist": False,
            "role_mentionable": False,
        }
        for level, name in ACTIVITY_DEFAULT_MILESTONES
    ]
