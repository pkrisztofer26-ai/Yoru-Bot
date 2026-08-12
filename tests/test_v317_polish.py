from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import aiosqlite

from app.database import Database

ROOT = Path(__file__).resolve().parents[1]


class PolishDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "yoru.db"), 1_000_000)
        await self.db.initialize()

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_health_report_is_safe_and_wal(self) -> None:
        report = await self.db.health_report()
        self.assertEqual(str(report["quick_check"]).lower(), "ok")
        self.assertEqual(str(report["journal_mode"]).lower(), "wal")
        self.assertGreater(int(report["file_bytes"]), 0)
        self.assertGreater(int(report["page_count"]), 0)

    async def test_hot_path_indexes_exist(self) -> None:
        expected = {
            "transactions": {"idx_transactions_guild_created", "idx_transactions_user_created"},
            "crew_invites": {"idx_crew_invites_crew"},
            "server_shop_claims": {"idx_server_shop_claims_pending"},
            "pvp_duels": {"idx_pvp_duels_resolved"},
            "business_offers": {"idx_business_offers_property", "idx_business_offers_buyer"},
            "heist_lobbies": {"idx_heist_lobbies_leader"},
            "heist_runs": {"idx_heist_runs_lobby"},
        }
        async with aiosqlite.connect(self.db.path) as conn:
            for table, names in expected.items():
                cur = await conn.execute(f"PRAGMA index_list('{table}')")
                found = {str(row[1]) for row in await cur.fetchall()}
                self.assertTrue(names.issubset(found), f"{table}: missing {names - found}")


class PolishRuntimeTests(unittest.TestCase):
    def test_prefix_runtime_cache_pruning_is_bounded(self) -> None:
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn("def _prune_prefix_runtime_cache", source)
        self.assertIn("len(self._prefix_action_times) < 2000", source)
        self.assertIn("self._prune_prefix_runtime_cache(now)", source)

    def test_settings_hub_has_current_modules_and_diagnostics(self) -> None:
        source = (ROOT / "app" / "cogs" / "settings.py").read_text(encoding="utf-8")
        self.assertIn('label="Diagnosztika"', source)
        self.assertIn('name="⚔️ Frakció"', source)
        self.assertIn('name="🏢 Biznisz"', source)
        self.assertIn('name="🎯 Nagy Meló"', source)
        self.assertNotIn('name="🔜 Következő nagy modul"', source)
        self.assertIn("health_report", source)
        self.assertIn("persistent_views", source)

    def test_business_market_selector_tracks_visible_page(self) -> None:
        source = (ROOT / "app" / "cogs" / "business.py").read_text(encoding="utf-8")
        self.assertIn("MarketPropertySelect(view, visible)", source)
        self.assertNotIn("MarketPropertySelect(view, all_props)", source)

    def test_large_server_runtime_pruning_is_present(self) -> None:
        main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        automod = (ROOT / "app" / "cogs" / "automod.py").read_text(encoding="utf-8")
        community = (ROOT / "app" / "cogs" / "community.py").read_text(encoding="utf-8")
        self.assertIn("_prune_prefix_runtime_cache", main)
        self.assertIn("_prune_runtime_state", automod)
        self.assertIn("len(self._afk_notice_times) >= 2000", community)

    def test_version_and_changelog(self) -> None:
        version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
        self.assertGreaterEqual(version, (3, 17, 0))
        self.assertTrue((ROOT / "CHANGELOG_3.17.0.txt").exists())


if __name__ == "__main__":
    unittest.main()
