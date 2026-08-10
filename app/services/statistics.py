from __future__ import annotations

from app.database import Database


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

    async def get(self, guild_id: int, user_id: int, stat_name: str, default: int = 0) -> int:
        value = await self.db.get_user_stat(guild_id, user_id, stat_name)
        return default if value is None else value

    async def get_many(self, guild_id: int, user_id: int, prefix: str | None = None) -> dict[str, int]:
        return await self.db.get_user_statistics(guild_id, user_id, prefix=prefix)

    async def increment(self, guild_id: int, user_id: int, stat_name: str, amount: int = 1) -> int:
        return await self.add(guild_id, user_id, stat_name, amount)

    async def add(self, guild_id: int, user_id: int, stat_name: str, amount: int) -> int:
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
