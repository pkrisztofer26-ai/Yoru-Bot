from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone

from app.database import Database
from app.services.statistics import StatisticsService
from app import economy_config as eco
from app.progression_math import level_from_xp


MARKET_ITEMS = eco.MARKET_ASSETS

NON_SELLABLE_ITEMS = {"nitro_basic_1m", "discord_nitro_1m"}


class ShopService:
    def __init__(self, database: Database, statistics: StatisticsService | None = None) -> None:
        self.db = database
        self.stats = statistics
        self._premium_locks: dict[tuple[int, str], asyncio.Lock] = {}

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    _level_from_xp = staticmethod(level_from_xp)

    @staticmethod
    def _month_start(now: datetime) -> datetime:
        return datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    def _premium_lock(self, guild_id: int, item_id: str) -> asyncio.Lock:
        key = (guild_id, item_id)
        lock = self._premium_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._premium_locks[key] = lock
        return lock

    async def premium_remaining(self, guild_id: int, item_id: str) -> int | None:
        rule = eco.PREMIUM_REWARD_RULES.get(item_id)
        if not rule:
            return None
        now = datetime.now(timezone.utc)
        used = await self.db.count_shop_purchases_since(guild_id, item_id, self._month_start(now))
        return max(0, int(rule["guild_monthly_stock"]) - used)

    async def _validate_premium_purchase(self, guild_id: int, user_id: int, item_id: str) -> int:
        rule = eco.PREMIUM_REWARD_RULES[item_id]
        now = datetime.now(timezone.utc)
        profile = await self.db.get_profile(guild_id, user_id)
        created = datetime.fromisoformat(str(profile["created_at"]))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        min_age = timedelta(days=int(rule["min_account_age_days"]))
        if now < created + min_age:
            ready = created + min_age
            raise ValueError(
                f"Ehhez a jutalomhoz legalább {rule['min_account_age_days']} napos Yoru account kell. "
                f"Feloldás: <t:{int(ready.timestamp())}:R>."
            )

        level = self._level_from_xp(int(profile.get("xp_points", 0)))
        min_level = int(rule["min_level"])
        if level < min_level:
            raise ValueError(f"Ehhez a jutalomhoz legalább Level {min_level} kell. Jelenleg Level {level} vagy.")

        personal_since = now - timedelta(days=int(rule["personal_cooldown_days"]))
        personal = await self.db.count_shop_purchases_since(guild_id, item_id, personal_since, user_id=user_id)
        if personal >= 1:
            raise ValueError(
                f"Ebből a prémium jutalomból legfeljebb 1-et vehetsz {rule['personal_cooldown_days']} naponta."
            )

        remaining = await self.premium_remaining(guild_id, item_id)
        if remaining is None or remaining <= 0:
            raise ValueError("Ennek a prémium jutalomnak elfogyott a havi szerverkészlete.")
        return remaining

    async def _market_state(self, guild_id: int, item_id: str) -> tuple[int, int, int]:
        cfg = MARKET_ITEMS[item_id]
        today = self._today()
        state = await self.db.get_market_state(guild_id, item_id, today)
        if state is None:
            price = random.randint(cfg["min_price"], cfg["max_price"])
            stock = random.randint(cfg["min_stock"], cfg["max_stock"])
            state = await self.db.create_market_state(guild_id, item_id, today, price, stock)
        return state

    async def list_items(self):
        return await self.db.list_shop_items()

    async def list_detailed(self):
        return await self.db.list_shop_items_detailed()

    async def list_for_guild(self, guild_id: int) -> list[dict[str, object]]:
        rows = await self.db.list_shop_items_detailed()
        result: list[dict[str, object]] = []
        for item_id, name, description, price, emoji, rarity, category in rows:
            current_price = price
            stock: int | None = None
            starting_stock: int | None = None
            if item_id in MARKET_ITEMS:
                current_price, stock, starting_stock = await self._market_state(guild_id, item_id)
            premium_remaining = await self.premium_remaining(guild_id, item_id)
            result.append({
                "item_id": item_id,
                "name": name,
                "description": description,
                "price": current_price,
                "base_price": price,
                "emoji": emoji,
                "rarity": rarity,
                "category": category,
                "stock": stock,
                "starting_stock": starting_stock,
                "market": item_id in MARKET_ITEMS,
                "premium_remaining": premium_remaining,
            })
        return result

    async def buy(self, guild_id: int, user_id: int, item_id: str, quantity: int):
        normalized = item_id.lower().strip()
        is_market = normalized in MARKET_ITEMS
        is_premium = normalized in eco.PREMIUM_REWARD_RULES

        if is_premium and quantity != 1:
            raise ValueError("Prémium jutalomból egyszerre csak 1 darab vásárolható.")

        if is_premium:
            # Egy bot processzen belül sorba állítjuk a valódi jutalom vásárlásokat,
            # így két egyidejű kattintás sem tudja túllépni a havi szerverkészletet.
            async with self._premium_lock(guild_id, normalized):
                remaining_before = await self._validate_premium_purchase(guild_id, user_id, normalized)
                name, emoji, total, wallet = await self.db.buy_item(guild_id, user_id, normalized, 1)
                result = (name, emoji, total, wallet, max(0, remaining_before - 1))
        elif is_market:
            await self._market_state(guild_id, normalized)
            result = await self.db.buy_market_item(guild_id, user_id, normalized, quantity, self._today())
        else:
            name, emoji, total, wallet = await self.db.buy_item(guild_id, user_id, normalized, quantity)
            result = (name, emoji, total, wallet, None)

        if self.stats is not None:
            await self.stats.record_shop_purchase(guild_id, user_id, normalized, quantity, int(result[2]), market=is_market)
        return result

    async def inventory(self, guild_id: int, user_id: int):
        return await self.db.get_inventory(guild_id, user_id)

    async def inventory_detailed(self, guild_id: int, user_id: int):
        return await self.db.get_inventory_detailed(guild_id, user_id)

    async def sell(self, guild_id: int, user_id: int, item_id: str, quantity: int):
        normalized = item_id.lower().strip()
        if normalized in NON_SELLABLE_ITEMS:
            raise ValueError("Ezt a jutalom itemet nem lehet pénzre visszaváltani.")
        is_market = normalized in MARKET_ITEMS
        if is_market:
            await self._market_state(guild_id, normalized)
            result = await self.db.sell_market_item(guild_id, user_id, normalized, quantity, self._today())
        else:
            name, emoji, value, wallet = await self.db.sell_item(guild_id, user_id, normalized, quantity)
            result = (name, emoji, value, wallet, None)
        if self.stats is not None:
            await self.stats.record_shop_sale(guild_id, user_id, normalized, quantity, int(result[2]), market=is_market)
        return result

    async def use(self, guild_id: int, user_id: int, item_id: str) -> tuple[str, int, str]:
        normalized = item_id.lower().strip()

        if normalized in eco.BOOSTER_DEFINITIONS:
            if not await self.db.consume_item(guild_id, user_id, normalized, 1):
                raise ValueError("Nincs ilyen booster az inventorydban.")
            name, multiplier, duration_hours = eco.BOOSTER_DEFINITIONS[normalized]
            expires = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
            await self.db.set_booster(guild_id, user_id, normalized, multiplier, expires)
            if self.stats is not None:
                await self.stats.record_inventory_use(guild_id, user_id, normalized, booster=True)
            return name, 0, f"Aktív: <t:{int(expires.timestamp())}:R> • szorzó: **x{multiplier:.2f}**"

        crate_defs = eco.CRATE_DEFINITIONS
        if normalized not in crate_defs:
            raise ValueError("Ezt a tárgyat jelenleg nem lehet kézzel használni.")
        if not await self.db.consume_item(guild_id, user_id, normalized, 1):
            raise ValueError("Nincs ilyen láda az inventorydban.")

        minimum, maximum, rarity = crate_defs[normalized]
        luck_factor = 1.0
        luck = await self.db.get_active_booster(guild_id, user_id, "luck_booster")
        guild_luck = await self.db.get_guild_effect(guild_id, "luck_multiplier")
        if luck:
            luck_factor *= 1.0 + (max(1.0, float(luck[0])) - 1.0) * eco.CRATE_LUCK_STRENGTH
        if guild_luck:
            luck_factor *= 1.0 + (max(1.0, float(guild_luck[0])) - 1.0) * eco.CRATE_LUCK_STRENGTH

        # A luck a jobb loot tier valószínűségét emeli, nem közvetlenül a cash payoutot.
        roll = random.random() ** (1.0 / luck_factor)
        if roll < eco.CRATE_TIER_1_THRESHOLD:
            reward = random.randint(minimum, max(minimum, int(maximum * eco.CRATE_TIER_1_MAX_RATIO)))
        elif roll < eco.CRATE_TIER_2_THRESHOLD:
            reward = random.randint(
                max(minimum, int(maximum * eco.CRATE_TIER_2_MIN_RATIO)),
                max(minimum, int(maximum * eco.CRATE_TIER_2_MAX_RATIO)),
            )
        else:
            reward = random.randint(max(minimum, int(maximum * eco.CRATE_TIER_3_MIN_RATIO)), maximum)

        charm_used = await self.db.consume_item(guild_id, user_id, "lucky_charm", 1)
        if charm_used:
            charm_bonus = min(
                eco.LUCKY_CHARM_MAX_BONUS,
                max(0, int(reward * (eco.LUCKY_CHARM_MULTIPLIER - 1.0))),
            )
            reward += charm_bonus
        reward = max(1, reward)
        wallet = await self.db.add_wallet(guild_id, user_id, reward, f"crate:{normalized}")
        if self.stats is not None:
            await self.stats.record_inventory_use(guild_id, user_id, normalized, crate=True)
        bonus_parts = []
        if luck_factor > 1:
            bonus_parts.append("🍀 Luck aktív")
        if charm_used:
            bonus_parts.append("🍀 Szerencsehozó +15%")
        bonus = (" • " + " • ".join(bonus_parts)) if bonus_parts else ""
        return rarity, reward, f"Új tárca: ${wallet:,}".replace(",", " ") + bonus
