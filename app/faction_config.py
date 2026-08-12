from __future__ import annotations

from dataclasses import dataclass

# Yoru v3.14 Frakció 2.0.  The old Crew infrastructure level (1-5) stays
# untouched for backwards compatibility; this is the new social progression.
FACTION_MAX_LEVEL = 100
FACTION_ENABLED_KEY = "faction_enabled"
FACTION_OBJECTIVES_ENABLED_KEY = "faction_objectives_enabled"
FACTION_WARS_ENABLED_KEY = "faction_wars_enabled"
FACTION_XP_MULTIPLIER_KEY = "faction_xp_multiplier_percent"
FACTION_DEFAULT_ENABLED = True
FACTION_DEFAULT_OBJECTIVES_ENABLED = True
FACTION_DEFAULT_WARS_ENABLED = True
FACTION_DEFAULT_XP_MULTIPLIER_PERCENT = 100
FACTION_XP_MULTIPLIER_MIN = 25
FACTION_XP_MULTIPLIER_MAX = 500
FACTION_OBJECTIVES_DAILY = 3
FACTION_OBJECTIVES_WEEKLY = 3
FACTION_WAR_HOURS = 24
FACTION_WAR_CHALLENGE_HOURS = 24
FACTION_WAR_WIN_BANK = 2_500_000
FACTION_WAR_WIN_XP = 1_500
FACTION_WAR_DRAW_BANK = 500_000
FACTION_WAR_DRAW_XP = 300
FACTION_MAX_CUSTOM_RANKS = 10


def xp_for_level(level: int) -> int:
    """Total XP needed to *reach* a Frakció level."""
    level = max(1, min(FACTION_MAX_LEVEL, int(level)))
    n = level - 1
    return 250 * n * n + 750 * n


def level_for_xp(xp: int) -> int:
    xp = max(0, int(xp))
    lo, hi = 1, FACTION_MAX_LEVEL
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if xp_for_level(mid) <= xp:
            lo = mid
        else:
            hi = mid - 1
    return lo


def level_progress(xp: int) -> tuple[int, int, int, int]:
    level = level_for_xp(xp)
    floor = xp_for_level(level)
    if level >= FACTION_MAX_LEVEL:
        return level, 1, 1, 100
    ceiling = xp_for_level(level + 1)
    current = max(0, xp - floor)
    needed = max(1, ceiling - floor)
    return level, current, needed, min(100, int(current * 100 / needed))


def total_perk_points(level: int) -> int:
    # One point every five Frakció levels. Level 100 => 20 points, exactly enough
    # to max all four launch-tree branches.
    return max(0, min(FACTION_MAX_LEVEL, int(level)) // 5)


@dataclass(frozen=True)
class ObjectiveDefinition:
    objective_id: str
    label: str
    emoji: str
    stat: str
    target: int
    reward_xp: int
    reward_bank: int


DAILY_OBJECTIVES: tuple[ObjectiveDefinition, ...] = (
    ObjectiveDefinition("d_work", "Dolgozzatok", "🔧", "work.count", 18, 450, 350_000),
    ObjectiveDefinition("d_crime", "Sikeres crime", "🕶️", "crime.success", 8, 500, 400_000),
    ObjectiveDefinition("d_gamble", "Gambling győzelmek", "🎰", "gambling.wins", 12, 500, 400_000),
    ObjectiveDefinition("d_search", "Keresések", "🔎", "search.count", 15, 400, 300_000),
    ObjectiveDefinition("d_daily", "Daily begyűjtések", "📅", "daily.count", 6, 500, 450_000),
    ObjectiveDefinition("d_activity", "Activity XP", "🌙", "activity.xp", 1_200, 550, 450_000),
    ObjectiveDefinition("d_deposit", "Frakció befizetés", "🏦", "crew.contributed", 2_000_000, 600, 500_000),
)

WEEKLY_OBJECTIVES: tuple[ObjectiveDefinition, ...] = (
    ObjectiveDefinition("w_work", "Heti meló", "🔧", "work.count", 120, 2_000, 1_500_000),
    ObjectiveDefinition("w_crime", "Heti crime", "🕶️", "crime.success", 50, 2_200, 1_700_000),
    ObjectiveDefinition("w_gamble", "Heti gambling win", "🎰", "gambling.wins", 80, 2_200, 1_700_000),
    ObjectiveDefinition("w_search", "Heti keresés", "🔎", "search.count", 100, 1_800, 1_300_000),
    ObjectiveDefinition("w_activity", "Heti Activity XP", "🌙", "activity.xp", 9_000, 2_400, 1_800_000),
    ObjectiveDefinition("w_deposit", "Heti Frakció befizetés", "🏦", "crew.contributed", 15_000_000, 2_500, 2_000_000),
)

OBJECTIVE_BY_ID = {o.objective_id: o for o in (*DAILY_OBJECTIVES, *WEEKLY_OBJECTIVES)}

# Exact user-stat events that contribute passive Frakció XP.  Monetary stats use
# capped conversion below in the service so whales cannot instantly max a faction.
STAT_XP: dict[str, int] = {
    "work.count": 10,
    "crime.success": 18,
    "gambling.wins": 14,
    "search.count": 8,
    "daily.count": 30,
    "weekly.count": 120,
    "monthly.count": 300,
    "community.jackpot.wins": 100,
    "community.lottery.wins": 100,
}
DEPOSIT_XP_PER = 250_000
DEPOSIT_XP_CAP_PER_EVENT = 250
ACTIVITY_XP_DIVISOR = 20  # 20 Activity XP => ~1 Frakció XP


@dataclass(frozen=True)
class PerkDefinition:
    key: str
    name: str
    emoji: str
    description: str
    max_rank: int


PERKS: tuple[PerkDefinition, ...] = (
    PerkDefinition("treasury", "Közös Kassza", "💸", "+0.5% támogatott economy income / rang", 5),
    PerkDefinition("objectives", "Célgép", "🎯", "+10% shared objective XP + bank reward / rang", 5),
    PerkDefinition("momentum", "Lendület", "⚡", "+10% minden megszerzett Frakció XP / rang", 5),
    PerkDefinition("war", "Hadigépezet", "⚔️", "+10% Frakció War jutalom / rang", 5),
)
PERK_BY_KEY = {perk.key: perk for perk in PERKS}

CUSTOM_RANK_PERMISSIONS: dict[str, tuple[str, str]] = {
    "invite": ("📨", "Tagok meghívása"),
    "kick": ("👢", "Tagok eltávolítása"),
    "bank_withdraw": ("💸", "Frakció Bank kivét"),
    "upgrade": ("⬆️", "Infrastructure fejlesztés"),
    "manage_profile": ("📝", "Leírás szerkesztése"),
    "manage_ranks": ("🎖️", "Belső rangok kezelése"),
    "manage_perks": ("🌲", "Perkek vásárlása"),
    "manage_wars": ("⚔️", "War indítás / elfogadás"),
}

WAR_OBJECTIVES: tuple[ObjectiveDefinition, ...] = (
    ObjectiveDefinition("war_work", "Work Sprint", "🔧", "work.count", 60, 0, 0),
    ObjectiveDefinition("war_crime", "Crime Race", "🕶️", "crime.success", 28, 0, 0),
    ObjectiveDefinition("war_gamble", "Gambling Clash", "🎰", "gambling.wins", 40, 0, 0),
    ObjectiveDefinition("war_activity", "Activity Rush", "🌙", "activity.xp", 4_000, 0, 0),
)
