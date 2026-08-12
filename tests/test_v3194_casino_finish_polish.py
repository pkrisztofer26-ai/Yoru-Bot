from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest

from PIL import Image

# Keep the release suite runnable in stripped artifact environments.
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
            self._path = path; self._conn = None; self._row_factory = None
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

from app import casino_config as cfg
from app.casino_games import run_slot_spin
from app.casino_visuals import render_roulette_animation, render_slots_animation
from app.database import Database
from app.services.casino import CasinoService

ROOT = Path(__file__).resolve().parents[1]


class _FakeGuildSettings:
    async def prepare_currency(self, guild_id): return None
    async def require_feature(self, guild_id, feature): return None
    async def get_gambling_payout_multiplier(self, guild_id): return 1.0


class Casino3194LockTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "casino.db"), 0)
        await self.db.initialize()
        self.casino = CasinoService(self.db, _FakeGuildSettings())
        await self.db.ensure_user(1, 10)
        await self.db.set_wallet(1, 10, 10_000_000, "seed")

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_one_active_game_per_player_and_release(self) -> None:
        first = await self.casino.begin(1, 10, "blackjack", 100_000)
        with self.assertRaisesRegex(ValueError, "Már fut egy Casino játékod"):
            await self.casino.begin(1, 10, "coinflip", 100_000)
        await self.casino.refund(first, "test")
        second = await self.casino.begin(1, 10, "coinflip", 100_000)
        await self.casino.settle(second, 0, result="lose")

    async def test_deferred_visual_lock_survives_settlement(self) -> None:
        slots = await self.casino.begin(
            1, 10, "slots", 100_000,
            config={"defer_player_lock_release": True},
        )
        await self.casino.settle(slots, 0, result="lose")
        with self.assertRaisesRegex(ValueError, "Már fut egy Casino játékod"):
            await self.casino.begin(1, 10, "dice", 100_000)
        await self.casino.release_player_game(slots.game_id)
        dice = await self.casino.begin(1, 10, "dice", 100_000)
        await self.casino.refund(dice, "test")


class Casino3194VisualTests(unittest.TestCase):
    @staticmethod
    def _gif_duration_ms(fp) -> tuple[int, int]:
        image = Image.open(fp)
        durations = []
        for index in range(image.n_frames):
            image.seek(index)
            durations.append(int(image.info.get("duration", 0)))
        return image.n_frames, sum(durations)

    def test_gifs_are_slower_and_roulette_has_more_frames(self) -> None:
        spin = run_slot_spin(100_000)
        slots_frames, slots_ms = self._gif_duration_ms(render_slots_animation(spin.grid, player_name="Krisz"))
        roulette_frames, roulette_ms = self._gif_duration_ms(
            render_roulette_animation(18, frame_count=cfg.ROULETTE_V2_SPIN_FRAMES, player_name="Krisz")
        )
        self.assertGreaterEqual(slots_frames, 7)
        self.assertGreaterEqual(slots_ms, 1950)  # ~30% slower than the old 1.55 s animation
        self.assertGreaterEqual(roulette_frames, 14)
        self.assertGreaterEqual(roulette_ms, 3000)

    def test_final_results_replace_gifs_with_static_png(self) -> None:
        source = (ROOT / "app/cogs/gambling.py").read_text(encoding="utf-8")
        self.assertIn('final=True, image_filename="slots.png"', source)
        self.assertIn('attachments=[final_file]', source)
        self.assertIn('image_filename="roulette.png"', source)
        self.assertIn('filename="roulette.png"', source)

    def test_player_branding_is_wired_into_both_gifs(self) -> None:
        visual = (ROOT / "app/casino_visuals.py").read_text(encoding="utf-8")
        cog = (ROOT / "app/cogs/gambling.py").read_text(encoding="utf-8")
        self.assertIn("'S GAME", visual)
        self.assertIn("player_name=user.display_name", cog)
        self.assertIn("player_name=self.owner.display_name", cog)

    def test_database_has_transaction_level_active_session_guard(self) -> None:
        source = (ROOT / "app/database.py").read_text(encoding="utf-8")
        self.assertIn("status IN ('ACTIVE','WAITING_INPUT','SETTLING')", source)
        self.assertIn("Már fut egy Casino játékod", source)

    def test_release_metadata(self) -> None:
        version = tuple(map(int, (ROOT / "VERSION").read_text(encoding="utf-8").strip().split(".")))
        self.assertGreaterEqual(version, (3, 19, 4))
        self.assertTrue((ROOT / "CHANGELOG_3.19.4.txt").exists())


if __name__ == "__main__":
    unittest.main()
