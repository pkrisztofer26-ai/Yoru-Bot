from __future__ import annotations

from datetime import datetime, timezone
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
            self._cursor = cursor; self.rowcount = cursor.rowcount; self.lastrowid = cursor.lastrowid
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
    _module.Connection = _Connection; _module.Row = sqlite3.Row; _module.connect = lambda path: _Connection(path)
    sys.modules["aiosqlite"] = _module

import aiosqlite

from app.database import Database
from app.services.statistics import StatisticsService
from app.services.prestige import PrestigeService
from app.services.activity import ActivityService
from app.services.crew import CrewService
from app.services.faction import FactionService
from app.services.heist import HeistService

ROOT = Path(__file__).resolve().parents[1]


class HeistBackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "yoru.db"), 2_000_000_000)
        await self.db.initialize()
        self.stats = StatisticsService(self.db)
        self.prestige = PrestigeService(self.db, self.stats)
        self.activity = ActivityService(self.db)
        self.crew = CrewService(self.db, self.stats)
        self.factions = FactionService(self.db, self.stats, self.crew)
        self.heist = HeistService(self.db, self.stats, self.prestige, self.activity, self.crew, self.factions)
        for user_id in (10, 20, 30, 40):
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
                "INSERT OR REPLACE INTO user_prestige (guild_id,user_id,prestige_rank,total_wealth_sacrificed) VALUES(?,?,5,0)",
                (1, user_id),
            )
            await conn.commit()

    async def _two_person_ready_lobby(self) -> int:
        lobby = await self.heist.create_lobby(1, 10, "miskolc_hollo")
        lobby_id = int(lobby["lobby_id"])
        await self.heist.invite_member(1, lobby_id, 10, 20)
        await self.heist.respond_invite(1, lobby_id, 20, accept=True)
        await self.heist.accept_cut(1, lobby_id, 10)
        await self.heist.accept_cut(1, lobby_id, 20)
        return lobby_id

    async def test_schema_and_settings_roundtrip(self) -> None:
        await self.heist.set_unlock_settings(1, activity_level=40, prestige=2)
        await self.heist.set_risk_settings(1, cooldown_hours=12, jail_minutes=60, fine_percent=15, gear_loss_percent=25, reward_multiplier_percent=125)
        settings = await self.heist.get_settings(1)
        self.assertEqual(settings.required_activity_level, 40)
        self.assertEqual(settings.required_prestige, 2)
        self.assertEqual(settings.cooldown_hours, 12)
        self.assertEqual(settings.reward_multiplier_percent, 125)
        async with aiosqlite.connect(self.db.path) as conn:
            for table in ("heist_lobbies", "heist_lobby_members", "heist_runs", "heist_gear", "heist_cooldowns"):
                cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
                self.assertIsNotNone(await cur.fetchone())

    async def test_invite_accept_equal_cut_requires_explicit_approval(self) -> None:
        lobby = await self.heist.create_lobby(1, 10, "miskolc_hollo")
        lobby_id = int(lobby["lobby_id"])
        await self.heist.invite_member(1, lobby_id, 10, 20)
        pending = await self.heist.pending_invites(1, 20)
        self.assertEqual(int(pending[0]["lobby_id"]), lobby_id)
        await self.heist.respond_invite(1, lobby_id, 20, accept=True)
        members = [m for m in await self.heist.lobby_members(1, lobby_id) if m["status"] == "accepted"]
        self.assertEqual(sorted(int(m["cut_percent"]) for m in members), [50, 50])
        self.assertFalse(any(bool(m["cut_accepted"]) for m in members))
        with self.assertRaises(ValueError):
            await self.heist.start_heist(1, lobby_id, 10)

    async def test_custom_cut_resets_all_approvals(self) -> None:
        lobby_id = await self._two_person_ready_lobby()
        await self.heist.set_cut(1, lobby_id, 10, 10, 60)
        await self.heist.set_cut(1, lobby_id, 10, 20, 40)
        members = [m for m in await self.heist.lobby_members(1, lobby_id) if m["status"] == "accepted"]
        self.assertEqual(sum(int(m["cut_percent"]) for m in members), 100)
        self.assertTrue(all(not bool(m["cut_accepted"]) for m in members))

    async def test_gear_shop_and_own_loadout(self) -> None:
        lobby_id = await self._two_person_ready_lobby()
        wallet_before, _ = await self.db.get_balance(1, 10)
        spent = await self.heist.buy_gear(1, 10, "intel_pack")
        wallet_after, _ = await self.db.get_balance(1, 10)
        self.assertEqual(wallet_before - wallet_after, spent)
        self.assertEqual((await self.heist.gear_inventory(1, 10))["intel_pack"], 1)
        await self.heist.set_gear(1, lobby_id, 10, "intel_pack")
        mine = next(m for m in await self.heist.lobby_members(1, lobby_id) if int(m["user_id"]) == 10)
        self.assertEqual(mine["gear_key"], "intel_pack")

    async def test_three_persisted_phases_resolve_and_set_cooldown(self) -> None:
        lobby_id = await self._two_person_ready_lobby()
        run = await self.heist.start_heist(1, lobby_id, 10)
        self.assertEqual(run["phase"], 0)
        run = await self.heist.advance_phase(1, lobby_id, 10)
        self.assertEqual(run["phase"], 1)
        run = await self.heist.advance_phase(1, lobby_id, 10)
        self.assertEqual(run["phase"], 2)
        run = await self.heist.advance_phase(1, lobby_id, 10)
        self.assertIn(run["status"], {"success", "failed"})
        self.assertEqual(len(run["phase_results"]), 3)
        self.assertIsNotNone(await self.heist.cooldown_until(1, 10))
        self.assertIsNone(await self.heist.active_lobby_for_user(1, 10))

    async def test_failure_applies_jail_fine_and_guaranteed_gear_loss(self) -> None:
        await self.heist.set_risk_settings(1, cooldown_hours=8, jail_minutes=45, fine_percent=10, gear_loss_percent=100, reward_multiplier_percent=100)
        lobby_id = await self._two_person_ready_lobby()
        await self.heist.buy_gear(1, 10, "toolkit")
        await self.heist.set_gear(1, lobby_id, 10, "toolkit")
        run = await self.heist.start_heist(1, lobby_id, 10)
        phases = [
            {"phase": 1, "key": "prep", "label": "🧠 Felkészülés", "chance": 10, "roll": 99, "passed": False},
            {"phase": 2, "key": "execution", "label": "⚙️ Végrehajtás", "chance": 10, "roll": 99, "passed": False},
            {"phase": 3, "key": "escape", "label": "🏁 Kijutás", "chance": 10, "roll": 99, "passed": False},
        ]
        result = await self.heist._resolve_run(1, lobby_id, run, phases)
        self.assertEqual(result["status"], "failed")
        self.assertIsNotNone(await self.db.get_jail_until(1, 10))
        self.assertEqual((await self.heist.gear_inventory(1, 10)).get("toolkit", 0), 0)
        with self.assertRaises(ValueError):
            await self.heist._resolve_run(1, lobby_id, run, phases)

    async def test_leaderboard_uses_heist_stats(self) -> None:
        await self.stats.add(1, 10, "heist.earned", 123_000_000)
        await self.stats.increment(1, 10, "heist.successes", 3)
        rows = await self.heist.leaderboard(1)
        self.assertEqual(rows[0], (10, 123_000_000, 3))


class HeistSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cog = (ROOT / "app" / "cogs" / "heist.py").read_text(encoding="utf-8")
        cls.service = (ROOT / "app" / "services" / "heist.py").read_text(encoding="utf-8")
        cls.database = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
        cls.main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        cls.settings = (ROOT / "app" / "cogs" / "settings.py").read_text(encoding="utf-8")
        cls.help_ui = (ROOT / "app" / "help_ui.py").read_text(encoding="utf-8")
        cls.analytics = (ROOT / "app" / "services" / "social_economy.py").read_text(encoding="utf-8")

    def test_interaction_first_ui_and_participant_acceptance(self) -> None:
        for token in ("HeistPlayerView", "TargetSelect", "InviteUserView", "RoleSelect", "LoadoutSelect", "CutModal", 'label="Részesedés OK"', 'label="Következő fázis"'):
            self.assertIn(token, self.cog)
        self.assertIn("Minden résztvevőnek el kell fogadnia", self.service)

    def test_settings_help_runtime_and_analytics_integrations(self) -> None:
        self.assertIn('label="Nagy Meló"', self.settings)
        self.assertIn('self.cog.bot.get_cog("HeistCog")', self.settings)
        self.assertIn("HeistService", self.main)
        self.assertIn("HeistCog", self.main)
        self.assertIn('(\"heist\", \"Nagy Meló\", \"🎯\"', self.help_ui)
        self.assertIn('return "Nagy Meló"', self.analytics)

    def test_schema_is_restart_safe_and_reset_aware(self) -> None:
        for table in ("heist_lobbies", "heist_lobby_members", "heist_runs", "heist_gear", "heist_cooldowns"):
            self.assertIn(table, self.database)
        self.assertIn("status='resolving'", self.service)

    def test_fictional_abstract_design(self) -> None:
        config = (ROOT / "app" / "heist_config.py").read_text(encoding="utf-8")
        self.assertIn("teljesen fikciósak", config)
        for real_brand in ("OTP", "K&H", "Erste", "Raiffeisen", "UniCredit", "MBH"):
            self.assertNotIn(real_brand, config)

    def test_version_and_changelog(self) -> None:
        version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
        self.assertGreaterEqual(version, (3, 16, 0))
        self.assertTrue((ROOT / "CHANGELOG_3.16.0.txt").exists())


if __name__ == "__main__":
    unittest.main()
