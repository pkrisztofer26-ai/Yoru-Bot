from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from app.database import Database
from app.services.social_economy import SocialEconomyService


class SocialUIBackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db", 100_000)
        await self.db.initialize()
        self.social = SocialEconomyService(self.db)
        await self.social.initialize()

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_server_shop_every_editable_field_roundtrips(self) -> None:
        rid = await self.social.create_server_shop_item(
            1, name="Teszt", description="x", emoji="🎁", price=1000,
            reward_type="custom", reward_ref="manual", stock=-1,
        )
        updated = await self.social.update_server_shop_item(
            1, rid,
            name="Új név", description="Új leírás", emoji="🔥", price=2_500_000,
            reward_type="item", reward_ref="chicken", reward_quantity=3,
            stock=42, per_user_limit=5, required_activity_level=10,
            required_progression_level=7, duration_minutes=0,
        )
        self.assertEqual(updated["name"], "Új név")
        self.assertEqual(updated["description"], "Új leírás")
        self.assertEqual(updated["emoji"], "🔥")
        self.assertEqual(int(updated["price"]), 2_500_000)
        self.assertEqual(updated["reward_type"], "item")
        self.assertEqual(updated["reward_ref"], "chicken")
        self.assertEqual(int(updated["reward_quantity"]), 3)
        self.assertEqual(int(updated["stock"]), 42)
        self.assertEqual(int(updated["per_user_limit"]), 5)
        self.assertEqual(int(updated["required_activity_level"]), 10)
        self.assertEqual(int(updated["required_progression_level"]), 7)

    async def test_server_shop_can_be_disabled_and_reenabled(self) -> None:
        rid = await self.social.create_server_shop_item(
            1, name="Teszt", description="", emoji="🎁", price=1000,
            reward_type="custom", reward_ref="manual",
        )
        self.assertTrue(await self.social.set_server_shop_item_active(1, rid, False))
        self.assertEqual(int((await self.social.get_server_shop_item(1, rid))["active"]), 0)
        self.assertTrue(await self.social.set_server_shop_item_active(1, rid, True))
        self.assertEqual(int((await self.social.get_server_shop_item(1, rid))["active"]), 1)


class SocialUISourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.social = (ROOT / "app/cogs/social_economy.py").read_text(encoding="utf-8")
        cls.settings = (ROOT / "app/cogs/settings.py").read_text(encoding="utf-8")

    def test_market_is_interactive_full_ui(self) -> None:
        for token in (
            "class PlayerMarketView", "MarketListingSelect", "MarketSearchModal",
            "MarketSellInventoryView", "MarketBuyModal", "MarketHistoryView",
            'label="Vásárlás"', 'label="Eladás"', 'label="Saját hirdetések"',
        ):
            self.assertIn(token, self.social)
        self.assertIn("view = PlayerMarketView", self.social)

    def test_server_shop_player_ui_is_interactive(self) -> None:
        self.assertIn("class ServerShopView", self.social)
        self.assertIn("class ServerShopSelect", self.social)
        self.assertIn('label="Megveszem"', self.social)
        self.assertIn("view = ServerShopView", self.social)

    def test_settings_has_social_entry_and_admin_ui(self) -> None:
        self.assertIn('label="Social"', self.settings)
        self.assertIn('self.cog.bot.get_cog("SocialEconomyCog")', self.settings)
        for token in (
            "class SocialSettingsHomeView", "class ServerShopAdminView",
            "ServerShopCreateModal", "ServerShopBasicsModal",
            "ServerShopRewardModal", "ServerShopLimitsModal",
            "class AnalyticsSettingsView", "class ServerShopClaimsView",
        ):
            self.assertIn(token, self.social)

    def test_analytics_has_interactive_period_buttons(self) -> None:
        for token in ('label="24 óra"', 'label="7 nap"', 'label="30 nap"', 'label="Frissítés"'):
            self.assertIn(token, self.social)

    def test_version_is_at_least_3131(self) -> None:
        self.assertGreaterEqual(tuple(map(int, (ROOT / "VERSION").read_text().strip().split("."))), (3, 13, 1))


if __name__ == "__main__":
    unittest.main()
