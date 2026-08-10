from __future__ import annotations

from app import economy_config as eco

# A Prestige balance tényleges értékei az economy_config.py-ban élnek.
PRESTIGE_LEVEL_BASE = eco.PRESTIGE_LEVEL_BASE
PRESTIGE_LEVEL_STEP = eco.PRESTIGE_LEVEL_STEP
PRESTIGE_WEALTH_BASE = eco.PRESTIGE_WEALTH_BASE
PRESTIGE_WEALTH_GROWTH = eco.PRESTIGE_WEALTH_GROWTH
PRESTIGE_INCOME_BONUS_PER_LEVEL = eco.PRESTIGE_INCOME_BONUS_PER_LEVEL
PRESTIGE_INCOME_BONUS_CAP = eco.PRESTIGE_INCOME_BONUS_CAP

PRESTIGE_BONUS_SOURCES = {
    "daily", "weekly", "monthly", "work", "crime", "search", "beg", "slut", "role_income", "interest",
}


def requirement_for_rank(current_rank: int) -> tuple[int, int]:
    rank = max(0, int(current_rank))
    required_level = PRESTIGE_LEVEL_BASE + rank * PRESTIGE_LEVEL_STEP
    raw_wealth = PRESTIGE_WEALTH_BASE * (PRESTIGE_WEALTH_GROWTH ** rank)
    # 100k-s lépcsőkre kerekítjük, mert az új economy skálán ez olvashatóbb.
    required_wealth = int(round(raw_wealth / 100_000) * 100_000)
    return required_level, max(PRESTIGE_WEALTH_BASE, required_wealth)


def income_bonus_for_rank(rank: int) -> float:
    return min(PRESTIGE_INCOME_BONUS_CAP, max(0, int(rank)) * PRESTIGE_INCOME_BONUS_PER_LEVEL)
