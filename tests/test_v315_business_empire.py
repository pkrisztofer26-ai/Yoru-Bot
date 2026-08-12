from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
        def __init__(self, path): self._path = path; self._conn = None; self._row_factory = None
        @property
        def row_factory(self): return self._row_factory
        @row_factory.setter
        def row_factory(self, value):
            self._row_factory = value
            if self._conn is not None: self._conn.row_factory = value
        async def __aenter__(self):
            self._conn = sqlite3.connect(self._path)
            if self._row_factory is not None: self._conn.row_factory = self._row_factory
            return self
        async def __aexit__(self, exc_type, exc, tb):
            if self._conn is not None: self._conn.close()
        async def execute(self, sql, params=()): return _Cursor(self._conn.execute(sql, params))
        async def executemany(self, sql, seq): return _Cursor(self._conn.executemany(sql, seq))
        async def commit(self): self._conn.commit()
        async def rollback(self): self._conn.rollback()
    _module = types.ModuleType("aiosqlite")
    _module.Connection = _Connection
    _module.Row = sqlite3.Row
    _module.connect = lambda path: _Connection(path)
    sys.modules["aiosqlite"] = _module

import aiosqlite

from app.database import Database
from app.services.statistics import StatisticsService
from app.services.prestige import PrestigeService
from app.services.activity import ActivityService
from app.services.crew import CrewService
from app.services.faction import FactionService
from app.services.business import BusinessService

ROOT = Path(__file__).resolve().parents[1]


class BusinessBackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "yoru.db"), 2_000_000_000)
        await self.db.initialize()
        self.stats = StatisticsService(self.db)
        self.prestige = PrestigeService(self.db, self.stats)
        self.activity = ActivityService(self.db)
        self.crew = CrewService(self.db, self.stats)
        self.factions = FactionService(self.db, self.stats, self.crew)
        self.business = BusinessService(self.db, self.stats, self.prestige, self.activity, self.crew, self.factions)
        for user_id in (10, 20):
            await self.db.ensure_user(1, user_id)
            await self._unlock(user_id)

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def _unlock(self, user_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute(
                """INSERT OR REPLACE INTO activity_users
                   (guild_id,user_id,total_xp,chat_xp,voice_xp,message_count,voice_seconds,level,updated_at)
                   VALUES(?,?,1000000,1000000,0,1000,0,100,?)""",
                (1, user_id, now),
            )
            await conn.execute(
                """INSERT OR REPLACE INTO user_prestige
                   (guild_id,user_id,prestige_rank,total_wealth_sacrificed) VALUES(?,?,3,0)""",
                (1, user_id),
            )
            await conn.commit()

    async def _license_and_first_property(self, user_id: int) -> dict:
        await self.business.buy_license(1, user_id)
        available = await self.business.properties(1, available_only=True)
        await self.business.buy_property(1, user_id, int(available[0]["property_id"]))
        return (await self.business.properties(1, owner_id=user_id))[0]

    async def test_permanent_license_unlock_and_unique_catalog(self) -> None:
        eligibility = await self.business.eligibility(1, 10)
        self.assertTrue(eligibility["eligible"])
        self.assertFalse(eligibility["has_license"])
        price = await self.business.buy_license(1, 10)
        self.assertGreater(price, 0)
        self.assertTrue(await self.business.has_license(1, 10))
        catalog = await self.business.properties(1)
        self.assertGreaterEqual(len(catalog), 12)
        self.assertEqual(len({row["template_key"] for row in catalog}), len(catalog))

    async def test_business_license_survives_prestige_reset(self) -> None:
        await self.business.buy_license(1, 10)
        self.assertTrue(await self.business.has_license(1, 10))
        await self.db.perform_prestige(1, 10, required_xp=0, required_wealth=0)
        self.assertTrue(await self.business.has_license(1, 10))

    async def test_property_claim_reputation_upgrade_and_faction_dividend(self) -> None:
        prop = await self._license_and_first_property(10)
        faction = await self.crew.create(1, 10, "BizniszTeszt")
        two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute(
                "UPDATE business_properties SET last_claim_at=?,reputation=500 WHERE guild_id=? AND property_id=?",
                (two_hours_ago, 1, int(prop["property_id"])),
            )
            await conn.commit()
        wallet_before, _ = await self.db.get_balance(1, 10)
        crew_before = await self.crew.get_crew(1, faction.crew.crew_id)
        claim = await self.business.claim(1, 10, int(prop["property_id"]))
        wallet_after, _ = await self.db.get_balance(1, 10)
        crew_after = await self.crew.get_crew(1, faction.crew.crew_id)
        self.assertGreater(claim["total_payout"], 0)
        self.assertGreater(wallet_after, wallet_before)
        self.assertGreater(claim["new_reputation"], 500)
        self.assertGreaterEqual(crew_after.bank, crew_before.bank)
        upgraded = await self.business.upgrade_property(1, 10, int(prop["property_id"]))
        self.assertEqual(upgraded["new_level"], 2)

    async def test_rotating_worker_hire_respects_slots(self) -> None:
        prop = await self._license_and_first_property(10)
        pool = await self.business.worker_pool(1)
        self.assertEqual(len(pool), 6)
        result = await self.business.hire_worker(1, 10, int(prop["property_id"]), pool[0].key)
        self.assertEqual(result["worker"].key, pool[0].key)
        active = await self.business.active_workers(1, int(prop["property_id"]))
        self.assertEqual(len(active), 1)

    async def test_property_offer_escrow_accept_and_transfer(self) -> None:
        prop = await self._license_and_first_property(10)
        property_id = int(prop["property_id"])
        pool = await self.business.worker_pool(1)
        await self.business.hire_worker(1, 10, property_id, pool[0].key)
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute(
                "UPDATE business_properties SET level=3,reputation=420 WHERE guild_id=? AND property_id=?",
                (1, property_id),
            )
            await conn.commit()
        await self.business.buy_license(1, 20)
        wallet_before, _ = await self.db.get_balance(1, 20)
        offer = await self.business.create_offer(1, 20, property_id, 80_000_000)
        wallet_escrow, _ = await self.db.get_balance(1, 20)
        self.assertEqual(wallet_before - wallet_escrow, 80_000_000)
        result = await self.business.resolve_offer(1, 10, int(offer["offer_id"]), accept=True)
        self.assertTrue(result["accepted"])
        transferred = await self.business.get_property(1, property_id)
        self.assertEqual(int(transferred["owner_id"]), 20)
        self.assertEqual(int(transferred["level"]), 3)
        self.assertEqual(int(transferred["reputation"]), 420)
        self.assertEqual(len(await self.business.active_workers(1, property_id)), 1)

    async def test_cancelled_offer_refund_restores_wallet_and_transaction_net(self) -> None:
        prop = await self._license_and_first_property(10)
        await self.business.buy_license(1, 20)
        wallet_before, _ = await self.db.get_balance(1, 20)
        offer = await self.business.create_offer(1, 20, int(prop["property_id"]), 50_000_000)
        refunded = await self.business.cancel_offer(1, 20, int(offer["offer_id"]))
        wallet_after, _ = await self.db.get_balance(1, 20)
        self.assertEqual(refunded, 50_000_000)
        self.assertEqual(wallet_after, wallet_before)
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE guild_id=? AND user_id=? AND reason LIKE 'business_offer_%'",
                (1, 20),
            )
            net = int((await cur.fetchone())[0])
        self.assertEqual(net, 0)

    async def test_admin_settings_roundtrip(self) -> None:
        await self.business.set_unlock_settings(1, activity_level=30, prestige=2, license_price=25_000_000)
        await self.business.set_economy_settings(1, tax_percent=15, offline_cap_hours=48, income_multiplier_percent=125, worker_contract_days=10)
        await self.business.set_limit_settings(1, base_cap=2, prestige_step=3, absolute_cap=7, city_cap=2)
        settings = await self.business.get_settings(1)
        self.assertEqual(settings.required_activity_level, 30)
        self.assertEqual(settings.license_price, 25_000_000)
        self.assertEqual(settings.tax_percent, 15)
        self.assertEqual(settings.offline_cap_hours, 48)
        self.assertEqual(settings.absolute_cap, 7)


class BusinessSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cog = (ROOT / "app" / "cogs" / "business.py").read_text(encoding="utf-8")
        cls.service = (ROOT / "app" / "services" / "business.py").read_text(encoding="utf-8")
        cls.settings = (ROOT / "app" / "cogs" / "settings.py").read_text(encoding="utf-8")
        cls.database = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
        cls.main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        cls.help_ui = (ROOT / "app" / "help_ui.py").read_text(encoding="utf-8")
        cls.social_service = (ROOT / "app" / "services" / "social_economy.py").read_text(encoding="utf-8")

    def test_interaction_first_player_ui(self) -> None:
        for token in ("PlayerBusinessView", "PropertySelect", "MarketPropertySelect", "WorkerSelect", "OfferSelect", "OfferAmountModal", 'label="Ingatlanpiac"', 'label="Dolgozók"', 'label="Ajánlatok"'):
            self.assertIn(token, self.cog)

    def test_settings_has_business_admin_panel(self) -> None:
        self.assertIn('label="Biznisz"', self.settings)
        self.assertIn('self.cog.bot.get_cog("BusinessCog")', self.settings)
        for token in ("BusinessAdminView", "UnlockSettingsModal", "EconomySettingsModal", "LimitSettingsModal"):
            self.assertIn(token, self.cog)

    def test_schema_and_runtime_are_loaded(self) -> None:
        for table in ("business_licenses", "business_properties", "business_workers", "business_offers", "business_transactions"):
            self.assertIn(table, self.database)
        self.assertIn("BusinessService", self.main)
        self.assertIn("BusinessCog", self.main)

    def test_help_and_analytics_integrations(self) -> None:
        self.assertIn('("business", "Biznisz", "🏢"', self.help_ui)
        self.assertIn('return "Biznisz Empire"', self.social_service)

    def test_version_and_changelog(self) -> None:
        version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
        self.assertGreaterEqual(version, (3, 15, 0))
        self.assertTrue((ROOT / "CHANGELOG_3.15.0.txt").exists())


if __name__ == "__main__":
    unittest.main()
