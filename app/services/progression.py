from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from app.database import Database
from app.services.economy import CooldownError, EconomyService
from app import economy_config as eco
from app.progression_math import progress_for_xp
from app.services.gameplay_settings import GameplaySettingsService
from app.progression_config import (
    ACHIEVEMENT_DEFINITIONS,
    BADGE_DEFINITIONS,
    TITLE_REQUIREMENTS,
)

# Backwards-compatible exports used by the existing UI/cogs.
ACHIEVEMENTS: dict[str, tuple[str, str]] = {
    achievement_id: (definition.name, definition.description)
    for achievement_id, definition in ACHIEVEMENT_DEFINITIONS.items()
}
BADGES: dict[str, tuple[str, str, str, str]] = {
    badge_id: (definition.emoji, definition.name, definition.description, definition.requirement)
    for badge_id, definition in BADGE_DEFINITIONS.items()
}


class ProgressionService:
    INVEST_COOLDOWN = timedelta(hours=eco.INVEST_COOLDOWN_HOURS)

    def __init__(self, db: Database, economy: EconomyService) -> None:
        self.db = db
        self.economy = economy
        self.settings = GameplaySettingsService(db)

    @staticmethod
    def level_from_xp(xp: int) -> tuple[int, int, int]:
        level, current, needed, _percent = progress_for_xp(xp)
        return level, current, needed

    async def sync_achievements(self, guild_id: int, user_id: int) -> list[str]:
        profile = await self.db.get_profile(guild_id, user_id)
        statistics = await self.economy.stats.get_many(guild_id, user_id)
        wealth = int(profile["wallet"]) + int(profile["bank"])

        newly_unlocked: list[str] = []
        for achievement_id, definition in ACHIEVEMENT_DEFINITIONS.items():
            if definition.wealth_target is not None:
                passed = wealth >= definition.wealth_target
            elif definition.stat is not None:
                passed = int(statistics.get(definition.stat, 0)) >= definition.target
            else:
                passed = False
            if passed and await self.db.unlock_achievement(guild_id, user_id, achievement_id):
                newly_unlocked.append(achievement_id)

        await self.sync_badges(guild_id, user_id)
        return newly_unlocked

    async def sync_badges(self, guild_id: int, user_id: int) -> list[str]:
        unlocked_achievements = set(await self.db.get_achievements(guild_id, user_id))
        new: list[str] = []
        for badge_id, definition in BADGE_DEFINITIONS.items():
            if definition.requirement in unlocked_achievements and await self.db.unlock_badge(guild_id, user_id, badge_id):
                new.append(badge_id)
        return new

    async def badges(self, guild_id: int, user_id: int) -> list[str]:
        await self.sync_achievements(guild_id, user_id)
        return await self.db.get_badges(guild_id, user_id)

    async def achievements(self, guild_id: int, user_id: int) -> list[str]:
        await self.sync_achievements(guild_id, user_id)
        return await self.db.get_achievements(guild_id, user_id)

    async def titles(self, guild_id: int, user_id: int) -> list[str]:
        unlocked = set(await self.achievements(guild_id, user_id))
        return [title for title, requirement in TITLE_REQUIREMENTS.items() if requirement is None or requirement in unlocked]

    async def choose_title(self, guild_id: int, user_id: int, title: str) -> str:
        available = await self.titles(guild_id, user_id)
        match = next((candidate for candidate in available if candidate.lower() == title.lower()), None)
        if match is None:
            raise ValueError("Ez a cím még nincs feloldva. Nézd meg: `!titles`.")
        await self.db.set_title(guild_id, user_id, match)
        return match

    async def active_boosters(self, guild_id: int, user_id: int):
        return await self.db.list_boosters(guild_id, user_id)

    async def activate_booster(self, guild_id: int, user_id: int, item_id: str) -> tuple[str, float, datetime]:
        definition = eco.BOOSTER_DEFINITIONS.get(item_id)
        if definition is None:
            raise ValueError("Ez nem aktiválható booster.")
        if not await self.db.consume_item(guild_id, user_id, item_id, 1):
            raise ValueError("Nincs ilyen booster az inventorydban.")
        name, multiplier, duration_hours = definition
        expires = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
        await self.db.set_booster(guild_id, user_id, item_id, multiplier, expires)
        return name, multiplier, expires

    async def bank_level(self, guild_id: int, user_id: int) -> tuple[int, float, int]:
        _, bank = await self.db.get_balance(guild_id, user_id)
        ascending = list(reversed(eco.INTEREST_TIERS))
        idx = max(i for i, (minimum, _rate, _cap) in enumerate(ascending) if bank >= minimum)
        _minimum, rate, cap = ascending[idx]
        rate *= await self.economy.guild_settings.get_interest_rate_multiplier(guild_id)
        cap = int(cap * await self.economy.guild_settings.get_interest_cap_multiplier(guild_id))
        booster = await self.db.get_active_booster(guild_id, user_id, "interest_booster")
        if booster:
            rate *= booster[0]
            cap = int(cap * booster[0])
        return idx + 1, rate, cap

    async def invest(self, guild_id: int, user_id: int, risk: str, amount: int) -> tuple[int, int, datetime, str]:
        await self.economy.require_not_jailed(guild_id, user_id)
        runtime = await self.settings.progression(guild_id)
        if not runtime.invest_enabled:
            raise ValueError("A Befektetés ezen a szerveren ki van kapcsolva.")
        now = datetime.now(timezone.utc)
        cooldown = timedelta(hours=runtime.invest_cooldown_hours)
        last = await self.db.get_timestamp(guild_id, user_id, "last_invest")
        if last and now < last + cooldown:
            raise CooldownError(last + cooldown)
        wallet, _ = await self.db.get_balance(guild_id, user_id)
        if amount < runtime.invest_min_amount or amount > wallet:
            raise ValueError(f"Minimum ${runtime.invest_min_amount:,}, és nem fektethetsz be többet a tárcádnál.".replace(",", " "))
        modes = eco.INVEST_MODES
        aliases = {"l": "low", "low": "low", "alacsony": "low", "m": "medium", "medium": "medium", "kozepes": "medium", "közepes": "medium", "h": "high", "high": "high", "magas": "high"}
        key = aliases.get(risk.lower())
        if key is None:
            raise ValueError("Kockázat: `low`, `medium` vagy `high`.")
        chance, min_gain, max_gain, max_loss, label = modes[key]
        won = random.random() < chance
        if won:
            profit = int(amount * random.uniform(min_gain, max_gain))
        else:
            profit = -int(amount * random.uniform(eco.INVEST_MIN_LOSS_RATE, max_loss))
        await self.db.add_wallet(guild_id, user_id, profit, f"investment:{key}")
        await self.db.increment_stat(guild_id, user_id, "investment_profit", profit)
        await self.economy.stats.increment(guild_id, user_id, "investment.count")
        await self.economy.stats.add(guild_id, user_id, "investment.profit", profit)
        await self.economy.stats.add(guild_id, user_id, "investment.wagered", amount)
        if profit > 0:
            await self.economy.stats.increment(guild_id, user_id, "investment.wins")
            await self.economy.stats.set_max(guild_id, user_id, "investment.biggest_win", profit)
        else:
            await self.economy.stats.increment(guild_id, user_id, "investment.losses")
            await self.economy.stats.set_max(guild_id, user_id, "investment.biggest_loss", -profit)
        await self.db.set_timestamp(guild_id, user_id, "last_invest", now)
        wallet, _ = await self.db.get_balance(guild_id, user_id)
        return profit, wallet, now + cooldown, label
