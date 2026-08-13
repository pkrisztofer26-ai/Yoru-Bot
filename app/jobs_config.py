from __future__ import annotations

from dataclasses import dataclass

JOBS_ENABLED_KEY = "jobs_enabled"
JOB_ENABLED_PREFIX = "jobs_enabled_"
JOBS_LOG_CHANNEL_KEY = "jobs_log_channel_id"
JOB_REWARD_MULTIPLIER_KEY = "jobs_reward_multiplier_bp"  # 10000 = 1.00x

DEFAULT_REWARD_MULTIPLIER_BP = 10_000
MAX_MASTERY_LEVEL = 50
MASTERY_BONUS_PER_LEVEL = 0.005
MASTERY_BONUS_CAP = 0.10
SESSION_TIMEOUT_SECONDS = 300

# v3.22.2 gameplay pacing / anti-farm
# One shared Jobs cooldown: finishing ANY job locks the full Jobs pool.
JOB_COOLDOWN_SECONDS = 2 * 60 * 60
ABANDON_COOLDOWN_SECONDS = 15 * 60

# Decision windows are intentionally generous: Jobs are decisions, not reflex tests.
DECISION_TIMEOUT_SECONDS = 30.0
WAREHOUSE_ANIMATION_SECONDS = 2.8
WAREHOUSE_MEMORIZE_SECONDS = 5.5
WAREHOUSE_DECISION_TIMEOUT_SECONDS = 35.0
BORSOD_DECISION_TIMEOUT_SECONDS = 30.0
TRANSPORT_DECISION_TIMEOUT_SECONDS = 30.0
ROUTE_ANIMATION_HOLD_SECONDS = 2.9
BORSOD_REVEAL_HOLD_SECONDS = 2.1


@dataclass(frozen=True, slots=True)
class JobDefinition:
    key: str
    name: str
    emoji: str
    description: str
    accent: tuple[int, int, int]
    base_mastery_xp: int


JOBS: tuple[JobDefinition, ...] = (
    JobDefinition("warehouse", "Raktáros", "📦", "Memória + sorrend alapú aktív műszak.", (84, 120, 255), 44),
    JobDefinition("borsod", "Borsodi Lopkodás", "🔌", "5×5 loot grid • limitált keresések • nincs tét.", (240, 165, 50), 42),
    JobDefinition("courier", "Futár", "🚚", "Útvonalválasztás, események és teljesítmény rating.", (81, 190, 145), 48),
    JobDefinition("taxi", "Taxi", "🚕", "NPC fuvarok, döntések, tip és rating.", (247, 204, 70), 48),
)

JOB_BY_KEY = {j.key: j for j in JOBS}

RATING_ORDER = ("D", "C", "B", "A", "S")
RATING_SCORE = {
    "D": 0,
    "C": 45,
    "B": 62,
    "A": 78,
    "S": 92,
}


def mastery_level_for_xp(xp: int) -> int:
    """Slow, uncapped-XP -> capped level curve. Level 1 is immediate."""
    xp = max(0, int(xp))
    level = 1
    spent = 0
    while level < MAX_MASTERY_LEVEL:
        need = 90 + (level - 1) * 22 + ((level - 1) ** 2) * 2
        if xp < spent + need:
            break
        spent += need
        level += 1
    return level


def mastery_progress(xp: int) -> tuple[int, int, int]:
    xp = max(0, int(xp))
    level = mastery_level_for_xp(xp)
    spent = 0
    for lv in range(1, level):
        spent += 90 + (lv - 1) * 22 + ((lv - 1) ** 2) * 2
    if level >= MAX_MASTERY_LEVEL:
        return level, 1, 1
    need = 90 + (level - 1) * 22 + ((level - 1) ** 2) * 2
    return level, max(0, xp - spent), need


def rating_for_score(score: int) -> str:
    score = max(0, min(100, int(score)))
    if score >= 92:
        return "S"
    if score >= 78:
        return "A"
    if score >= 62:
        return "B"
    if score >= 45:
        return "C"
    return "D"


def mastery_bonus(level: int) -> float:
    return min(MASTERY_BONUS_CAP, max(0, int(level) - 1) * MASTERY_BONUS_PER_LEVEL)
