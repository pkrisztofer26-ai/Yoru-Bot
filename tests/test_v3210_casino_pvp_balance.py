from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from PIL import Image

import importlib.util
import sqlite3
import sys
import types

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
    module = types.ModuleType("aiosqlite")
    module.Connection = _Connection
    module.Row = sqlite3.Row
    module.connect = lambda path: _Connection(path)
    sys.modules["aiosqlite"] = module

from app import casino_config as cfg
from app.casino_games import simulate_slots_rtp
from app.casino_pvp_visuals import (
    render_duel_challenge,
    render_pvp_coinflip_animation, render_pvp_coinflip,
    render_pvp_dice_animation, render_pvp_dice,
    render_pvp_rps_wait, render_pvp_rps_animation, render_pvp_rps,
)
from app.database import Database
from app.services.casino import CasinoService
from app.services.social_economy import SocialEconomyService

ROOT = Path(__file__).resolve().parents[1]


class _FakeGuildSettings:
    async def prepare_currency(self, guild_id): return None
    async def require_feature(self, guild_id, feature): return None
    async def get_gambling_payout_multiplier(self, guild_id): return 1.0


class Casino3210PvPVisualTests(unittest.TestCase):
    @staticmethod
    def _asset(fp):
        im = Image.open(fp)
        frames = int(getattr(im, "n_frames", 1))
        duration = 0
        hashes = set()
        for i in range(frames):
            im.seek(i)
            duration += int(im.info.get("duration", 0))
            hashes.add(hash(im.convert("RGB").tobytes()))
        return im.format, im.size, frames, duration, len(hashes)

    def test_pvp_challenge_and_final_states_are_large_static_images(self):
        assets = [
            render_duel_challenge("coinflip", "Krisz", "Pityu", 1_000_000),
            render_pvp_coinflip("Krisz", "Pityu", 1_000_000, "Krisz"),
            render_pvp_dice("Krisz", "Pityu", 1_000_000, 88, 42, "Krisz"),
            render_pvp_rps_wait("Krisz", "Pityu", 1_000_000),
            render_pvp_rps("Krisz", "Pityu", 1_000_000, "rock", "scissors", "Krisz"),
        ]
        for fp in assets:
            fmt, size, frames, _, _ = self._asset(fp)
            self.assertEqual(fmt, "PNG")
            self.assertEqual(size, (960, 640))
            self.assertEqual(frames, 1)

    def test_pvp_games_use_real_animation_then_static_final(self):
        assets = [
            render_pvp_coinflip_animation("Krisz", "Pityu", 1_000_000, "Krisz"),
            render_pvp_dice_animation("Krisz", "Pityu", 1_000_000, 88, 42, "Krisz"),
            render_pvp_rps_animation("Krisz", "Pityu", 1_000_000, "rock", "scissors", "Krisz"),
        ]
        for fp in assets:
            fmt, size, frames, duration, unique = self._asset(fp)
            self.assertEqual(fmt, "GIF")
            self.assertEqual(size, (960, 640))
            self.assertGreater(frames, 3)
            self.assertGreater(duration, 1800)
            self.assertGreater(unique, 3)


class Casino3210CrossGameLockTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "v3210.db"), 2_000_000)
        await self.db.initialize()
        self.social = SocialEconomyService(self.db)
        await self.social.initialize()
        self.casino = CasinoService(self.db, _FakeGuildSettings())
        for uid in (10, 20):
            await self.db.ensure_user(1, uid)
            await self.db.set_wallet(1, uid, 2_000_000, "seed")

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_accepted_pvp_blocks_house_casino_for_both_players(self):
        duel = await self.social.create_duel(1, 10, 20, "coinflip", 100_000, 1)
        await self.social.accept_duel(duel.id, 20)
        for uid in (10, 20):
            with self.assertRaisesRegex(ValueError, "Már fut egy Casino játékod"):
                await self.casino.begin(1, uid, "coinflip", 10_000)
        await self.social.settle_duel(duel.id, 10)
        session = await self.casino.begin(1, 20, "coinflip", 10_000)
        await self.casino.refund(session, "test")

    async def test_house_casino_blocks_pvp_accept_atomically(self):
        duel = await self.social.create_duel(1, 10, 20, "dice", 100_000, 1)
        session = await self.casino.begin(1, 10, "coinflip", 10_000)
        with self.assertRaisesRegex(ValueError, "Valamelyik játékosnak már fut egy Casino játéka"):
            await self.social.accept_duel(duel.id, 20)
        await self.casino.refund(session, "test")
        accepted = await self.social.accept_duel(duel.id, 20)
        self.assertEqual(accepted.status, "accepted")
        await self.social.settle_duel(duel.id, 20)


class Casino3210BalanceAuditTests(unittest.TestCase):
    def test_default_quick_and_roulette_rtp_have_no_positive_ev(self):
        rtp = {
            "coinflip": 0.5 * cfg.COINFLIP_V2_TOTAL_PAYOUT,
            "dice_exact": (1/6) * cfg.DICE_V2_EXACT_TOTAL_PAYOUT,
            "dice_even": 0.5 * cfg.DICE_V2_EVEN_TOTAL_PAYOUT,
            "dice_over7": (15/36) * cfg.DICE_V2_OVER_UNDER_TOTAL_PAYOUT,
            "dice_seven": (6/36) * cfg.DICE_V2_EXACT_SEVEN_TOTAL_PAYOUT,
            "rps": (1/3) * cfg.RPS_V2_TOTAL_PAYOUT + (1/3),
            "chicken": cfg.CHICKEN_WIN_CHANCE * cfg.CHICKEN_TOTAL_PAYOUT,
            "roulette_even": (18/37) * cfg.ROULETTE_V2_EVEN_TOTAL_PAYOUT,
            "roulette_dozen": (12/37) * cfg.ROULETTE_V2_DOZEN_COLUMN_TOTAL_PAYOUT,
            "roulette_number": (1/37) * cfg.ROULETTE_V2_SINGLE_TOTAL_PAYOUT,
        }
        for name, value in rtp.items():
            self.assertLess(value, 1.0, name)
            self.assertGreaterEqual(value, 0.90, name)
        self.assertAlmostEqual(cfg.HIGHLOW_V2_HOUSE_FACTOR, 0.96, places=4)

    def test_slots_monte_carlo_stays_in_target_band(self):
        value = simulate_slots_rtp(250_000, seed=3210)
        self.assertGreaterEqual(value, cfg.SLOTS_V2_RTP_TARGET[0])
        self.assertLessEqual(value, cfg.SLOTS_V2_RTP_TARGET[1])

    def test_lottery_and_jackpot_remain_sinks_or_redistribution_not_sources(self):
        from app import economy_config as eco
        self.assertLessEqual(eco.LOTTERY_PAYOUT_SHARE, 1.0)
        self.assertLessEqual(cfg.MONTHLY_JACKPOT_PAYOUT_SHARE, 1.0)
        self.assertGreaterEqual(cfg.MONTHLY_JACKPOT_CONTRIBUTION_RATE, 0.0)
        self.assertLess(cfg.MONTHLY_JACKPOT_CONTRIBUTION_RATE, 0.10)

    def test_release_metadata(self):
        self.assertGreaterEqual(tuple(map(int, (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))), (3, 21, 2))
        self.assertTrue((ROOT / "CHANGELOG_3.21.0.txt").exists())
        self.assertTrue((ROOT / "CHANGELOG_3.21.2.txt").exists())
        self.assertTrue((ROOT / "CASINO_BALANCE_AUDIT.md").exists())


if __name__ == "__main__":
    unittest.main()
