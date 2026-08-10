from __future__ import annotations

import math

from app import economy_config as eco


def level_from_xp(xp_points: int) -> int:
    """Return the visible Yoru level for activity XP."""
    xp = max(0, int(xp_points))
    return max(1, int(math.sqrt(xp / eco.PROGRESSION_LEVEL_XP_SCALE)) + 1)


def minimum_xp_for_level(level: int) -> int:
    level = max(1, int(level))
    return (level - 1) ** 2 * eco.PROGRESSION_LEVEL_XP_SCALE


def progress_for_xp(xp_points: int) -> tuple[int, int, int, int]:
    xp = max(0, int(xp_points))
    level = level_from_xp(xp)
    floor = minimum_xp_for_level(level)
    ceiling = minimum_xp_for_level(level + 1)
    current = max(0, xp - floor)
    needed = max(1, ceiling - floor)
    percent = max(0, min(100, int(current / needed * 100)))
    return level, current, needed, percent
