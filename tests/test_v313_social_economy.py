from __future__ import annotations

from pathlib import Path
import importlib.util
import sqlite3
import sys
import tempfile
import types
import unittest

if "aiosqlite" not in sys.modules and importlib.util.find_spec("aiosqlite") is None:
    class _Cursor:
        def __init__(self, cursor):
            self._cursor = cursor
            self.rowcount = cursor.rowcount
            self.lastrowid = cursor.lastrowid
        async def fetchone(self): return self._cursor.fetchone()
        async def fetchall(self): return self._cursor.fetchall()

    class _Connection:
        def __init__(self, path): self._path = path; self._conn = None
        async def __aenter__(self): self._conn = sqlite3.connect(self._path); return self
        async def __aexit__(self, exc_type, exc, tb):
            if self._conn is not None: self._conn.close()
        async def execute(self, sql, params=()): return _Cursor(self._conn.execute(sql, params))
        async def executemany(self, sql, seq): return _Cursor(self._conn.executemany(sql, seq))
        async def commit(self): self._conn.commit()
        async def rollback(self): self._conn.rollback()

    _module = types.ModuleType("aiosqlite")
    _module.Connection = _Connection
    _module.connect = lambda path: _Connection(path)
    sys.modules["aiosqlite"] = _module

from app.database import Database
from app.services.social_economy import SocialEconomyService

ROOT = Path(__file__).resolve().parents[1]


class SocialEconomyDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "yoru.db"), 1_000_000)
        await self.db.initialize()
        self.social = SocialEconomyService(self.db)
        await self.social.initialize()

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_marketplace_escrows_items_and_taxes_sale(self) -> None:
        await self.db.add_item(1, 10, "chicken", 5)
        listing_id = await self.social.create_listing(1, 10, "chicken", 2, 100_000)
        self.assertEqual(await self.db.get_item_quantity(1, 10, "chicken"), 3)

        result = await self.social.buy_listing(1, 20, listing_id, 1)
        self.assertEqual(result["gross"], 100_000)
        self.assertEqual(result["tax"], 5_000)
        self.assertEqual(result["net"], 95_000)
        self.assertEqual(await self.db.get_item_quantity(1, 20, "chicken"), 1)
        seller_wallet, _ = await self.db.get_balance(1, 10)
        buyer_wallet, _ = await self.db.get_balance(1, 20)
        self.assertEqual(seller_wallet, 1_095_000)
        self.assertEqual(buyer_wallet, 900_000)

    async def test_market_cancel_returns_escrow(self) -> None:
        await self.db.add_item(1, 10, "chicken", 3)
        listing_id = await self.social.create_listing(1, 10, "chicken", 2, 10_000)
        returned = await self.social.cancel_listing(1, 10, listing_id)
        self.assertEqual(returned, 2)
        self.assertEqual(await self.db.get_item_quantity(1, 10, "chicken"), 3)

    async def test_server_shop_item_purchase_and_limit(self) -> None:
        reward_id = await self.social.create_server_shop_item(
            1, name="Chicken pack", description="test", emoji="🐔", price=50_000,
            reward_type="item", reward_ref="chicken", reward_quantity=2, stock=2, per_user_limit=1,
        )
        purchase = await self.social.begin_server_shop_purchase(1, 20, reward_id)
        self.assertEqual(purchase["price"], 50_000)
        await self.db.add_item(1, 20, "chicken", 2)
        await self.social.complete_server_shop_purchase(purchase["purchase_id"])
        self.assertEqual(await self.db.get_item_quantity(1, 20, "chicken"), 2)
        with self.assertRaises(ValueError):
            await self.social.begin_server_shop_purchase(1, 20, reward_id)

    async def test_custom_reward_creates_claim(self) -> None:
        reward_id = await self.social.create_server_shop_item(
            1, name="Custom", description="", emoji="🎁", price=10_000,
            reward_type="custom", reward_ref="Egyedi rangszín", stock=-1,
        )
        purchase = await self.social.begin_server_shop_purchase(1, 33, reward_id)
        self.assertIsNotNone(purchase["claim_id"])
        claims = await self.social.list_pending_claims(1)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["reward_text"], "Egyedi rangszín")
        self.assertTrue(await self.social.fulfill_claim(1, claims[0]["id"], 999))
        self.assertEqual(await self.social.list_pending_claims(1), [])

    async def test_duel_escrow_and_settlement_are_persistent(self) -> None:
        duel = await self.social.create_duel(1, 10, 20, "coinflip", 100_000, 123)
        accepted = await self.social.accept_duel(duel.id, 20)
        self.assertEqual(accepted.status, "accepted")
        self.assertEqual((await self.db.get_balance(1, 10))[0], 900_000)
        self.assertEqual((await self.db.get_balance(1, 20))[0], 900_000)
        await self.social.settle_duel(duel.id, 10)
        self.assertEqual((await self.db.get_balance(1, 10))[0], 1_100_000)
        self.assertEqual((await self.db.get_balance(1, 20))[0], 900_000)
        stats = await self.social.duel_stats(1, 10)
        self.assertEqual(stats["social.pvp.wins"], 1)

    async def test_duel_tie_refunds_both_stakes(self) -> None:
        duel = await self.social.create_duel(1, 10, 20, "rps", 75_000, 123)
        await self.social.accept_duel(duel.id, 20)
        await self.social.settle_duel(duel.id, None)
        self.assertEqual((await self.db.get_balance(1, 10))[0], 1_000_000)
        self.assertEqual((await self.db.get_balance(1, 20))[0], 1_000_000)

    async def test_analytics_tracks_social_volume(self) -> None:
        await self.db.add_item(1, 10, "chicken", 2)
        listing_id = await self.social.create_listing(1, 10, "chicken", 1, 100_000)
        await self.social.buy_listing(1, 20, listing_id, 1)
        duel = await self.social.create_duel(1, 10, 20, "dice", 50_000, 123)
        await self.social.accept_duel(duel.id, 20)
        await self.social.settle_duel(duel.id, 10)
        data = await self.social.analytics(1, 24)
        self.assertEqual(data["market_volume"], 100_000)
        self.assertEqual(data["market_trades"], 1)
        self.assertEqual(data["duel_volume"], 100_000)
        self.assertEqual(data["duels"], 1)


class SocialEconomySourceTests(unittest.TestCase):
    def test_social_group_is_grouped_and_loaded(self) -> None:
        source = (ROOT / "app" / "cogs" / "social_economy.py").read_text(encoding="utf-8")
        main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn('group_name="social"', source)
        self.assertIn("SocialEconomyCog(self, self.database, self.economy)", main)
        self.assertNotIn('@self.tree.command(name="market"', main)

    def test_social_schema_is_self_migrating(self) -> None:
        source = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
        for table in (
            "player_market_listings", "player_market_trades", "server_shop_items",
            "server_shop_purchases", "server_shop_claims", "temporary_role_grants", "pvp_duels",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", source)

    def test_release_has_no_fixed_market_or_duel_money_ceiling(self) -> None:
        cfg = (ROOT / "app" / "social_config.py").read_text(encoding="utf-8")
        amounts = (ROOT / "app" / "amounts.py").read_text(encoding="utf-8")
        self.assertNotIn("PVP_MAX_STAKE", cfg)
        self.assertIn("There is no artificial gameplay cap", amounts)

    def test_release_version_and_changelog(self) -> None:
        self.assertGreaterEqual(tuple(map(int, (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))), (3, 13, 0))
        self.assertTrue((ROOT / "CHANGELOG_3.13.0.txt").exists())
        self.assertIn("✅ v3.13", (ROOT / "ROADMAP.md").read_text(encoding="utf-8"))

    def test_market_has_search_and_page_browsing(self) -> None:
        source = (ROOT / "app" / "cogs" / "social_economy.py").read_text(encoding="utf-8")
        service = (ROOT / "app" / "services" / "social_economy.py").read_text(encoding="utf-8")
        self.assertIn("kereses: str | None", source)
        self.assertIn("oldal: app_commands.Range", source)
        self.assertIn("LOWER(l.item_id) LIKE", service)
        self.assertIn("LIMIT ? OFFSET ?", service)

    def test_prefix_wrong_channel_reuses_delete_dm_contract(self) -> None:
        source = (ROOT / "app" / "cogs" / "social_economy.py").read_text(encoding="utf-8")
        self.assertIn("handle_wrong_economy_channel(ctx, self.economy", source)


if __name__ == "__main__":
    unittest.main()
