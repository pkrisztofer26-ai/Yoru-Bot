from __future__ import annotations

from datetime import datetime, timezone
import random

from app.database import Database
from app.progression_config import QUESTS_BY_PERIOD, QUEST_COUNT_PER_PERIOD


GAME_LABELS: dict[str, tuple[str, str]] = {
    "blackjack": ("🃏", "Blackjack"),
    "coinflip": ("🪙", "Coinflip"),
    "roulette": ("🎡", "Roulette"),
    "slots": ("🎰", "Slots"),
    "dice": ("🎲", "Dice"),
    "highlow": ("🃏", "High/Low"),
    "rps": ("✂️", "RPS"),
    "chickenfight": ("🐔", "Chicken Fight"),
}


class StatisticsService:
    """Központi, névtér-alapú statisztika API.

    A statok kulcsai ponttal tagolt névteret használnak, pl. ``work.count``
    vagy ``economy.earned``. Új stat hozzáadásához nem kell adatbázis-migráció.
    """

    def __init__(self, database: Database) -> None:
        self.db = database
        self._quest_stats_by_period = {
            period: {quest.stat for quest in definitions}
            for period, definitions in QUESTS_BY_PERIOD.items()
        }

    @staticmethod
    def _quest_period_key(period: str) -> str:
        now = datetime.now(timezone.utc)
        if period == "daily":
            return now.date().isoformat()
        iso_year, iso_week, _ = now.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"

    async def _ensure_quest_assignments_before_stat_change(
        self, guild_id: int, user_id: int, stat_name: str
    ) -> None:
        """Create this period's deterministic quests before the first relevant action.

        Previously quests were first created when the user opened the Quest menu,
        which made all activity before that moment become the baseline. This hook
        runs before a quest-relevant stat changes, so the first action of the
        day/week counts even if the menu is never opened.
        """
        for period, relevant_stats in self._quest_stats_by_period.items():
            if stat_name not in relevant_stats:
                continue
            key = self._quest_period_key(period)
            if await self.db.get_quest_assignments(guild_id, user_id, period, key):
                continue
            definitions = QUESTS_BY_PERIOD[period]
            rng = random.Random(f"yoru:{guild_id}:{user_id}:{period}:{key}")
            selected = rng.sample(list(definitions), k=min(QUEST_COUNT_PER_PERIOD, len(definitions)))
            for slot, definition in enumerate(selected, start=1):
                current = await self.get(guild_id, user_id, definition.stat)
                await self.db.create_quest_assignment(
                    guild_id, user_id, period, key, slot, definition.quest_id,
                    current, definition.target, definition.reward_xp, definition.reward_item,
                )

    async def get(self, guild_id: int, user_id: int, stat_name: str, default: int = 0) -> int:
        value = await self.db.get_user_stat(guild_id, user_id, stat_name)
        return default if value is None else value

    async def get_many(self, guild_id: int, user_id: int, prefix: str | None = None) -> dict[str, int]:
        return await self.db.get_user_statistics(guild_id, user_id, prefix=prefix)

    async def increment(self, guild_id: int, user_id: int, stat_name: str, amount: int = 1) -> int:
        return await self.add(guild_id, user_id, stat_name, amount)

    async def add(self, guild_id: int, user_id: int, stat_name: str, amount: int) -> int:
        if amount != 0:
            await self._ensure_quest_assignments_before_stat_change(guild_id, user_id, stat_name)
        return await self.db.add_user_stat(guild_id, user_id, stat_name, amount)

    async def set(self, guild_id: int, user_id: int, stat_name: str, value: int) -> int:
        return await self.db.set_user_stat(guild_id, user_id, stat_name, value)

    async def set_max(self, guild_id: int, user_id: int, stat_name: str, value: int) -> int:
        return await self.db.set_user_stat_max(guild_id, user_id, stat_name, value)

    async def record_gamble(
        self,
        guild_id: int,
        user_id: int,
        game: str,
        bet: int,
        profit: int,
        won: bool,
    ) -> None:
        base = game.removesuffix("_tie")
        tied = game.endswith("_tie") or profit == 0
        await self.increment(guild_id, user_id, "gambling.plays")
        await self.increment(guild_id, user_id, f"gambling.{base}.plays")
        await self.add(guild_id, user_id, "gambling.wagered", bet)
        await self.add(guild_id, user_id, f"gambling.{base}.wagered", bet)
        await self.add(guild_id, user_id, "gambling.profit", profit)
        await self.add(guild_id, user_id, f"gambling.{base}.profit", profit)

        if tied:
            await self.increment(guild_id, user_id, "gambling.ties")
            await self.increment(guild_id, user_id, f"gambling.{base}.ties")
        elif won:
            await self.increment(guild_id, user_id, "gambling.wins")
            await self.increment(guild_id, user_id, f"gambling.{base}.wins")
        else:
            await self.increment(guild_id, user_id, "gambling.losses")
            await self.increment(guild_id, user_id, f"gambling.{base}.losses")

        if profit > 0:
            await self.set_max(guild_id, user_id, "gambling.biggest_win", profit)
            await self.set_max(guild_id, user_id, f"gambling.{base}.biggest_win", profit)
        elif profit < 0:
            loss = -profit
            await self.set_max(guild_id, user_id, "gambling.biggest_loss", loss)
            await self.set_max(guild_id, user_id, f"gambling.{base}.biggest_loss", loss)

    async def record_shop_purchase(
        self,
        guild_id: int,
        user_id: int,
        item_id: str,
        quantity: int,
        total: int,
        *,
        market: bool = False,
    ) -> None:
        await self.increment(guild_id, user_id, "shop.purchases", quantity)
        await self.add(guild_id, user_id, "shop.spent", total)
        await self.increment(guild_id, user_id, f"shop.item.{item_id}.bought", quantity)
        if market:
            await self.increment(guild_id, user_id, "market.purchases", quantity)
            await self.add(guild_id, user_id, "market.spent", total)

    async def record_shop_sale(
        self,
        guild_id: int,
        user_id: int,
        item_id: str,
        quantity: int,
        total: int,
        *,
        market: bool = False,
    ) -> None:
        await self.increment(guild_id, user_id, "shop.sales", quantity)
        await self.add(guild_id, user_id, "shop.earned", total)
        await self.increment(guild_id, user_id, f"shop.item.{item_id}.sold", quantity)
        if market:
            await self.increment(guild_id, user_id, "market.sales", quantity)
            await self.add(guild_id, user_id, "market.earned", total)

    async def record_inventory_use(
        self,
        guild_id: int,
        user_id: int,
        item_id: str,
        *,
        crate: bool = False,
        booster: bool = False,
    ) -> None:
        await self.increment(guild_id, user_id, "inventory.items_used")
        await self.increment(guild_id, user_id, f"inventory.item.{item_id}.used")
        if crate:
            await self.increment(guild_id, user_id, "inventory.crates_opened")
        if booster:
            await self.increment(guild_id, user_id, "inventory.boosters_used")

    @staticmethod
    def favorite_game(stats: dict[str, int]) -> str:
        best_label = "—"
        best_count = 0
        for game_id, (emoji, label) in GAME_LABELS.items():
            count = int(stats.get(f"gambling.{game_id}.plays", 0))
            if count > best_count:
                best_count = count
                best_label = f"{emoji} {label}"
        return best_label if best_count > 0 else "—"

    @staticmethod
    def format_stat_value(stat_key: str, value: int) -> str:
        monetary_markers = (
            "earned", "lost", "profit", "spent", "wagered", "peak",
            "reward", "deposited", "withdrawn", "sent", "received", "contributed", "bonus_earned",
        )
        formatted = f"{value:,}".replace(",", " ")
        return f"${formatted}" if any(part in stat_key for part in monetary_markers) else formatted
