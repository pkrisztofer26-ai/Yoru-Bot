from __future__ import annotations

import asyncio
import importlib.util
from io import BytesIO
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest

# Keep this release test runnable in the lightweight artifact environment.
if "aiosqlite" not in sys.modules and importlib.util.find_spec("aiosqlite") is None:
    class _Cursor:
        def __init__(self, cursor):
            self._cursor = cursor
            self.rowcount = cursor.rowcount
            self.lastrowid = cursor.lastrowid
        async def fetchone(self): return self._cursor.fetchone()
        async def fetchall(self): return self._cursor.fetchall()

    class _Connection:
        def __init__(self, path):
            self._path = path
            self._conn = None
            self._row_factory = None
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

    module = types.ModuleType("aiosqlite")
    module.Connection = _Connection
    module.Row = sqlite3.Row
    module.connect = lambda path: _Connection(path)
    sys.modules["aiosqlite"] = module

from PIL import Image

from app import jobs_config as cfg
from app.activity_visuals import (
    render_borsod,
    render_job_final,
    render_job_lobby,
    render_route_animation,
    render_warehouse_transition,
)
from app.database import Database
from app.services.jobs import BORSOD_LOOT, JobBusyError, JobsService
from app.job_framework import GridGame, PerformanceRating, RiskCashout, SequenceGame
from app.services.statistics import StatisticsService

ROOT = Path(__file__).resolve().parents[1]


class InteractiveJobsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "jobs.db")
        self.db = Database(self.path, 0)
        await self.db.initialize()
        self.stats = StatisticsService(self.db)
        class _Economy:
            async def apply_prestige_bonus(self, guild_id, user_id, amount, source):
                return int(amount)
        self.economy = _Economy()
        self.jobs = JobsService(self.db, self.economy, self.stats)

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_one_active_job_per_player_per_guild(self) -> None:
        first = await self.jobs.start_warehouse(1, 100)
        self.assertEqual(first["status"], "active")
        with self.assertRaises(JobBusyError):
            await self.jobs.start_borsod(1, 100)
        other_user = await self.jobs.start_borsod(1, 101)
        self.assertEqual(other_user["status"], "active")
        other_guild = await self.jobs.start_borsod(2, 100)
        self.assertEqual(other_guild["status"], "active")

    async def test_warehouse_full_shift_pays_once_and_levels_mastery(self) -> None:
        session = await self.jobs.start_warehouse(1, 200)
        for _ in range(5):
            current = await self.jobs.get_session(session["session_id"])
            session, correct, done = await self.jobs.warehouse_answer(session["session_id"], int(current["data"]["answer"]))
            self.assertTrue(correct)
            if done:
                break
        result = await self.jobs.finish(session["session_id"])
        self.assertEqual(result.rating, "S")
        self.assertGreater(result.reward, 0)
        wallet, _ = await self.db.get_balance(1, 200)
        self.assertEqual(wallet, result.reward)
        mastery = await self.jobs.get_mastery(1, 200, "warehouse")
        self.assertEqual(int(mastery["shifts"]), 1)
        self.assertGreater(int(mastery["xp"]), 0)
        with self.assertRaises(ValueError):
            await self.jobs.finish(session["session_id"])
        wallet2, _ = await self.db.get_balance(1, 200)
        self.assertEqual(wallet2, result.reward)

    async def test_borsod_safe_run_uses_seven_unique_picks(self) -> None:
        session = await self.jobs.start_borsod(1, 300)
        safe = [i for i, cell in enumerate(session["data"]["cells"]) if not cell["hazard"]][:7]
        self.assertEqual(len(safe), 7)
        done = False
        for index in safe:
            session, cell, done = await self.jobs.borsod_pick(session["session_id"], index)
            self.assertFalse(cell["hazard"])
        self.assertTrue(done)
        self.assertEqual(int(session["data"]["attempts_left"]), 0)
        result = await self.jobs.finish(session["session_id"])
        self.assertGreater(result.reward, 0)

    async def test_transport_is_four_decisions_then_finish(self) -> None:
        session = await self.jobs.start_transport(1, 400, "courier")
        for turn in range(4):
            session, event, done = await self.jobs.transport_choose(session["session_id"], "safe")
            self.assertIn("event", event)
            self.assertEqual(done, turn == 3)
        result = await self.jobs.finish(session["session_id"])
        self.assertIn(result.rating, cfg.RATING_ORDER)
        self.assertGreater(result.reward, 0)

    async def test_restart_recovery_clears_active_lock(self) -> None:
        await self.jobs.start_transport(1, 500, "taxi")
        recovered = await self.jobs.recover_after_restart()
        self.assertEqual(recovered, 1)
        session = await self.jobs.start_warehouse(1, 500)
        self.assertEqual(session["status"], "active")


    def test_borsod_default_reward_calibration_band(self) -> None:
        import random
        rng = random.Random(3220)
        population: list[int] = []
        for _token, value, weight in BORSOD_LOOT:
            population.extend([int(value)] * int(weight))
        payouts: list[int] = []
        for _ in range(20_000):
            cells = [rng.choice(population) for _ in range(25)]
            hazards = set(rng.sample(range(25), 3))
            reward = 0
            for idx in rng.sample(range(25), 7):
                if idx in hazards:
                    reward = round(reward * 0.70)
                    break
                reward += cells[idx]
            payouts.append(reward)
        average = sum(payouts) / len(payouts)
        self.assertGreater(average, 235_000)
        self.assertLess(average, 265_000)

    async def test_server_settings_are_database_driven(self) -> None:
        self.assertTrue(await self.jobs.is_enabled(10))
        await self.jobs.settings.set_bool(10, cfg.JOBS_ENABLED_KEY, False)
        self.assertFalse(await self.jobs.is_enabled(10))
        await self.jobs.settings.set_bool(10, cfg.JOBS_ENABLED_KEY, True)
        await self.jobs.settings.set_bool(10, f"{cfg.JOB_ENABLED_PREFIX}taxi", False)
        self.assertFalse(await self.jobs.job_enabled(10, "taxi"))
        await self.jobs.settings.set_int(10, cfg.JOB_REWARD_MULTIPLIER_KEY, 12500)
        self.assertAlmostEqual(await self.jobs.reward_multiplier(10), 1.25)


class InteractiveJobsFrameworkTests(unittest.TestCase):
    def test_sequence_grid_rating_and_risk_primitives(self) -> None:
        round_ = SequenceGame.build_round(("A", "B", "C", "D", "E", "F"), rng=__import__("random").Random(42))
        self.assertEqual(len(round_.sequence), 4)
        self.assertEqual(len(set(round_.candidates)), 4)
        self.assertEqual(round_.candidates[round_.answer_index], round_.sequence)
        self.assertEqual(GridGame.validate_pick(3, cell_count=25, revealed=[1, 2]), 3)
        with self.assertRaises(ValueError):
            GridGame.validate_pick(2, cell_count=25, revealed=[1, 2])
        self.assertEqual(PerformanceRating.from_score(93).grade, "S")
        risk = RiskCashout(at_risk=100_000).fail(keep_fraction=0.70)
        self.assertEqual(risk.banked, 70_000)
        self.assertEqual(risk.at_risk, 0)


class InteractiveJobsVisualTests(unittest.TestCase):
    def _assert_image(self, fp: BytesIO, expected_format: str) -> None:
        fp.seek(0)
        image = Image.open(fp)
        self.assertEqual(image.format, expected_format)
        self.assertEqual(image.size, (960, 620))

    def test_lobby_and_final_are_static_pngs(self) -> None:
        lobby = render_job_lobby("Pajkos Paripa", [
            ("📦 Raktáros", "2 műszak • rekord A", "Mastery Lv.3 • 20/100 XP"),
            ("🔌 Borsodi Lopkodás", "1 műszak • rekord B", "Mastery Lv.2 • 10/100 XP"),
            ("🚚 Futár", "0 műszak • rekord D", "Mastery Lv.1 • 0/90 XP"),
            ("🚕 Taxi", "0 műszak • rekord D", "Mastery Lv.1 • 0/90 XP"),
        ])
        self._assert_image(lobby, "PNG")
        final = render_job_final("Pajkos Paripa", "Raktáros", accent=(84,120,255), rating="S", score=96, reward=450000, mastery_level=4, mastery_xp=60)
        self._assert_image(final, "PNG")

    def test_job_transitions_are_real_gifs(self) -> None:
        warehouse = render_warehouse_transition("Pajkos Paripa", ["A12", "C04", "B17", "A08"], 1)
        self._assert_image(warehouse, "GIF")
        warehouse.seek(0); self.assertGreater(getattr(Image.open(warehouse), "n_frames", 1), 3)
        route = render_route_animation("Pajkos Paripa", "Futár", "🚚", accent=(81,190,145), event="Zöld hullám", success=True)
        self._assert_image(route, "GIF")
        route.seek(0); self.assertGreater(getattr(Image.open(route), "n_frames", 1), 5)

    def test_borsod_grid_is_5x5_visual(self) -> None:
        board = ["?"] * 25
        fp = render_borsod("Pajkos Paripa", board, 7, 0)
        self._assert_image(fp, "PNG")


class InteractiveJobsReleaseWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.main = (ROOT / "app/main.py").read_text(encoding="utf-8")
        cls.cog = (ROOT / "app/cogs/jobs.py").read_text(encoding="utf-8")
        cls.settings = (ROOT / "app/cogs/settings.py").read_text(encoding="utf-8")
        cls.tutorial = (ROOT / "app/cogs/tutorial.py").read_text(encoding="utf-8")
        cls.database = (ROOT / "app/database.py").read_text(encoding="utf-8")

    def test_group_and_prefix_backend_are_wired(self) -> None:
        self.assertIn('group_name="jobs"', self.cog)
        self.assertIn('@commands.command(name="jobs"', self.cog)
        self.assertIn('await self.add_cog(JobsCog(self, self.jobs))', self.main)
        self.assertIn('self.jobs = JobsService', self.main)

    def test_settings_and_tutorial_integration_exist(self) -> None:
        self.assertIn('label="Jobs"', self.settings)
        self.assertIn('Interactive Jobs', self.tutorial)
        self.assertIn('JOB_REWARD_MULTIPLIER_KEY', (ROOT / "app/jobs_config.py").read_text(encoding="utf-8"))

    def test_database_has_restart_safe_session_lock(self) -> None:
        self.assertIn('CREATE TABLE IF NOT EXISTS job_sessions', self.database)
        self.assertIn("WHERE status='active'", self.database)
        self.assertIn('CREATE TABLE IF NOT EXISTS job_mastery', self.database)
        self.assertIn('CREATE TABLE IF NOT EXISTS job_history', self.database)

    def test_release_metadata(self) -> None:
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "3.22.0")
        self.assertTrue((ROOT / "CHANGELOG_3.22.0.txt").exists())
        self.assertTrue((ROOT / "JOBS_BALANCE_AUDIT.md").exists())
        self.assertTrue((ROOT / "GAMES_V2_ROADMAP.md").exists())
        self.assertTrue((ROOT / "app/job_framework.py").exists())


if __name__ == "__main__":
    unittest.main()
