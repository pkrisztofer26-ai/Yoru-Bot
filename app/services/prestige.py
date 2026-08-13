from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.database import Database
from app.prestige_config import PRESTIGE_BONUS_SOURCES
from app.services.gameplay_settings import GameplaySettingsService
from app.services.statistics import StatisticsService
from app.progression_math import level_from_xp, minimum_xp_for_level


@dataclass(frozen=True)
class PrestigeState:
    rank: int
    current_level: int
    current_wealth: int
    required_level: int
    required_wealth: int
    income_bonus: float
    next_income_bonus: float
    income_bonus_cap: float
    total_wealth_sacrificed: int
    last_prestige_at: datetime | None

    @property
    def eligible(self) -> bool:
        return self.current_level >= self.required_level and self.current_wealth >= self.required_wealth


@dataclass(frozen=True)
class PrestigeResult:
    old_rank: int
    new_rank: int
    wealth_sacrificed: int
    removed_items: int
    removed_boosters: int
    income_bonus: float


class PrestigeService:
    def __init__(self, database: Database, statistics: StatisticsService) -> None:
        self.db = database
        self.stats = statistics
        self.settings = GameplaySettingsService(database)

    level_from_xp = staticmethod(level_from_xp)
    minimum_xp_for_level = staticmethod(minimum_xp_for_level)

    async def state(self, guild_id: int, user_id: int) -> PrestigeState:
        profile = await self.db.get_profile(guild_id, user_id)
        prestige = await self.db.get_prestige_data(guild_id, user_id)
        rank = int(prestige["prestige_rank"])
        current_level = self.level_from_xp(int(profile.get("xp_points", 0)))
        current_wealth = int(profile["wallet"]) + int(profile["bank"])
        config = await self.settings.prestige(guild_id)
        required_level = config.level_base + rank * config.level_step
        raw_wealth = config.wealth_base * (config.wealth_growth ** rank)
        required_wealth = max(config.wealth_base, int(round(raw_wealth / 100_000.0)) * 100_000)
        last_raw = prestige.get("last_prestige_at")
        last_at = datetime.fromisoformat(str(last_raw)) if last_raw else None
        return PrestigeState(
            rank=rank,
            current_level=current_level,
            current_wealth=current_wealth,
            required_level=required_level,
            required_wealth=required_wealth,
            income_bonus=min(config.income_bonus_cap, max(0, rank) * config.income_bonus_per_rank),
            next_income_bonus=min(config.income_bonus_cap, max(0, rank + 1) * config.income_bonus_per_rank),
            income_bonus_cap=config.income_bonus_cap,
            total_wealth_sacrificed=int(prestige["total_wealth_sacrificed"]),
            last_prestige_at=last_at,
        )

    async def reward_multiplier(self, guild_id: int, user_id: int, source: str) -> float:
        if source not in PRESTIGE_BONUS_SOURCES:
            return 1.0
        rank = await self.db.get_prestige_rank(guild_id, user_id)
        config = await self.settings.prestige(guild_id)
        if not config.enabled:
            return 1.0
        return 1.0 + min(config.income_bonus_cap, max(0, rank) * config.income_bonus_per_rank)

    async def boost_reward(self, guild_id: int, user_id: int, amount: int, source: str) -> tuple[int, int]:
        """Prestige bónusz alkalmazása. Visszaadja: (új összeg, bónusz rész)."""
        amount = int(amount)
        if amount <= 0 or source not in PRESTIGE_BONUS_SOURCES:
            return amount, 0
        multiplier = await self.reward_multiplier(guild_id, user_id, source)
        boosted = max(amount, int(round(amount * multiplier)))
        bonus = max(0, boosted - amount)
        if bonus:
            await self.stats.add(guild_id, user_id, "prestige.bonus_earned", bonus)
            await self.stats.add(guild_id, user_id, f"prestige.bonus.{source}", bonus)
        return boosted, bonus

    async def prestige(self, guild_id: int, user_id: int) -> PrestigeResult:
        config = await self.settings.prestige(guild_id)
        if not config.enabled:
            raise ValueError("A Prestige rendszer ezen a szerveren ki van kapcsolva.")
        state = await self.state(guild_id, user_id)
        if state.current_level < state.required_level:
            raise ValueError(
                f"A következő prestige-hez legalább **Level {state.required_level}** kell. "
                f"Jelenleg Level {state.current_level} vagy."
            )
        if state.current_wealth < state.required_wealth:
            missing = state.required_wealth - state.current_wealth
            raise ValueError(f"Még **${missing:,}** vagyon hiányzik a prestige-hez.".replace(",", " "))

        required_xp = self.minimum_xp_for_level(state.required_level)
        result = await self.db.perform_prestige(
            guild_id,
            user_id,
            required_xp=required_xp,
            required_wealth=state.required_wealth,
        )
        return PrestigeResult(
            old_rank=int(result["old_rank"]),
            new_rank=int(result["new_rank"]),
            wealth_sacrificed=int(result["wealth_sacrificed"]),
            removed_items=int(result["removed_items"]),
            removed_boosters=int(result["removed_boosters"]),
            income_bonus=min(config.income_bonus_cap, max(0, int(result["new_rank"])) * config.income_bonus_per_rank),
        )

    async def leaderboard(self, guild_id: int, limit: int = 10) -> list[tuple[int, int, int]]:
        return await self.db.prestige_leaderboard(guild_id, limit)
