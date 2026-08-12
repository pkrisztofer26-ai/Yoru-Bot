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
from app.casino_quick_visuals import (
    render_chicken,
    render_chicken_animation,
    render_coinflip,
    render_coinflip_animation,
    render_dice,
    render_dice_animation,
    render_highlow,
    render_highlow_animation,
    render_rps,
    render_rps_animation,
)
from app.database import Database
from app.services.casino import CasinoService

ROOT = Path(__file__).resolve().parents[1]


class _FakeGuildSettings:
    async def prepare_currency(self, guild_id): return None
    async def require_feature(self, guild_id, feature): return None
    async def get_gambling_payout_multiplier(self, guild_id): return 1.0


class Casino3200QuickConfigTests(unittest.TestCase):
    def test_quick_game_balance_modes_are_centralized(self) -> None:
        self.assertAlmostEqual(cfg.COINFLIP_V2_TOTAL_PAYOUT, 1.90)
        self.assertAlmostEqual(cfg.DICE_V2_EXACT_TOTAL_PAYOUT, 5.70)
        self.assertAlmostEqual(cfg.DICE_V2_EVEN_TOTAL_PAYOUT, 1.90)
        self.assertAlmostEqual(cfg.DICE_V2_OVER_UNDER_TOTAL_PAYOUT, 2.28)
        self.assertAlmostEqual(cfg.DICE_V2_EXACT_SEVEN_TOTAL_PAYOUT, 5.70)
        self.assertAlmostEqual(cfg.RPS_V2_TOTAL_PAYOUT, 1.85)
        self.assertGreater(cfg.HIGHLOW_V2_HOUSE_FACTOR, 0.0)
        self.assertLess(cfg.HIGHLOW_V2_HOUSE_FACTOR, 1.0)
        self.assertGreaterEqual(cfg.MONTHLY_JACKPOT_MIN_GAMES, 1)
        self.assertGreaterEqual(cfg.MONTHLY_JACKPOT_MIN_WAGER, 1)

    def test_quick_services_use_deferred_visual_session_lock(self) -> None:
        gambling = (ROOT / "app/services/gambling.py").read_text(encoding="utf-8")
        extras = (ROOT / "app/services/extras.py").read_text(encoding="utf-8")
        self.assertIn("coinflip_visual", gambling)
        self.assertIn("dice_visual", gambling)
        self.assertIn('"defer_player_lock_release": True', gambling)
        self.assertIn("rps_visual", extras)
        self.assertIn("chickenfight_visual", extras)
        self.assertIn('"defer_player_lock_release": True', extras)


class Casino3200CommunityDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "community3200.db")
        self.db = Database(self.path, 0)
        await self.db.initialize()
        for uid in (10, 20, 30):
            await self.db.ensure_user(1, uid)
            await self.db.set_wallet(1, uid, 1_000_000, "seed")

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    def _insert_settled_sessions(self, uid: int, month: str, *, count: int, bet: int) -> None:
        con = sqlite3.connect(self.path)
        try:
            for index in range(count):
                game_id = f"T-{uid}-{index}-{month}"
                stamp = f"{month}-15T12:{index % 60:02d}:00+00:00"
                con.execute(
                    """INSERT INTO casino_sessions
                       (game_id,guild_id,user_id,game,status,bet,payout,profit,multiplier,result,config_json,wallet_after,created_at,updated_at,settled_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (game_id, 1, uid, "coinflip", "SETTLED", bet, 0, -bet, 0.0, "lose", "{}", 0, stamp, stamp, stamp),
                )
            con.commit()
        finally:
            con.close()

    async def test_jackpot_eligibility_is_games_or_wager_and_finalize_is_idempotent(self) -> None:
        month = "2026-07"
        self._insert_settled_sessions(10, month, count=25, bet=1_000)      # qualifies by games
        self._insert_settled_sessions(20, month, count=2, bet=150_000)     # qualifies by wager
        self._insert_settled_sessions(30, month, count=2, bet=10_000)      # not eligible
        con = sqlite3.connect(self.path)
        try:
            con.execute(
                "INSERT INTO casino_monthly_jackpot (guild_id,month,pool,total_house_loss,total_contributed,updated_at) VALUES (?,?,?,?,?,?)",
                (1, month, 1_000_000, 50_000_000, 1_000_000, "2026-07-31T23:59:00+00:00"),
            )
            con.commit()
        finally:
            con.close()

        eligible = await self.db.get_casino_jackpot_eligible(1, month, min_games=25, min_wager=250_000)
        self.assertEqual([row["user_id"] for row in eligible], [10, 20])
        before, _ = await self.db.get_balance(1, 10)
        result = await self.db.finalize_monthly_casino_jackpot(
            1, month, winner_id=10, eligible_players=len(eligible), payout_share=1.0, rollover_month="2026-08",
        )
        self.assertEqual(result["outcome"], "draw")
        self.assertEqual(result["payout"], 1_000_000)
        after, _ = await self.db.get_balance(1, 10)
        self.assertEqual(after, before + 1_000_000)
        again = await self.db.finalize_monthly_casino_jackpot(
            1, month, winner_id=20, eligible_players=2, payout_share=1.0, rollover_month="2026-08",
        )
        self.assertTrue(again["idempotent"])
        after_again, _ = await self.db.get_balance(1, 10)
        self.assertEqual(after_again, after)
        history = await self.db.get_casino_jackpot_history(1, 5)
        self.assertEqual(history[0]["winner_id"], 10)
        self.assertEqual(history[0]["eligible_players"], 2)

    async def test_no_eligible_jackpot_rolls_over(self) -> None:
        con = sqlite3.connect(self.path)
        try:
            con.execute(
                "INSERT INTO casino_monthly_jackpot (guild_id,month,pool,total_house_loss,total_contributed,updated_at) VALUES (?,?,?,?,?,?)",
                (1, "2026-06", 500_000, 25_000_000, 500_000, "2026-06-30T23:59:00+00:00"),
            )
            con.commit()
        finally:
            con.close()
        result = await self.db.finalize_monthly_casino_jackpot(
            1, "2026-06", winner_id=None, eligible_players=0, payout_share=1.0, rollover_month="2026-08",
        )
        self.assertEqual(result["outcome"], "rollover")
        current = await self.db.get_monthly_casino_jackpot(1, month="2026-08")
        self.assertEqual(current["pool"], 500_000)

    async def test_lottery_history_persists(self) -> None:
        await self.db.add_lottery_history(1, 20, 77, 1_750_000)
        rows = await self.db.get_lottery_history(1, 5)
        self.assertEqual(rows[0]["winner_id"], 20)
        self.assertEqual(rows[0]["total_tickets"], 77)
        self.assertEqual(rows[0]["payout"], 1_750_000)


class Casino3200VisualTests(unittest.TestCase):
    @staticmethod
    def _inspect(fp):
        image = Image.open(fp)
        frames = int(getattr(image, "n_frames", 1))
        duration = 0
        for i in range(frames):
            image.seek(i)
            duration += int(image.info.get("duration", 0))
        return image.format, image.size, frames, duration

    def test_all_quick_games_have_large_gif_and_static_final(self) -> None:
        assets = [
            (render_coinflip_animation("fej", player_name="Krisz"), render_coinflip("fej", player_name="Krisz")),
            (render_dice_animation((4,), player_name="Krisz", mode_label="EXACT"), render_dice((4,), player_name="Krisz", mode_label="EXACT")),
            (render_rps_animation("rock", "scissors", player_name="Krisz"), render_rps("rock", "scissors", player_name="Krisz")),
            (render_highlow_animation(7, 10, player_name="Krisz", multiplier=1.0, streak=0), render_highlow(10, None, player_name="Krisz", multiplier=1.5, streak=1, reveal=False)),
            (render_chicken_animation([(100,100,"START"),(82,100,"ATTACK"),(82,56,"CRITICAL"),(50,56,"COUNTER"),(50,0,"KO")], opponent="RIVAL", player_name="Krisz"), render_chicken(50,0,opponent="RIVAL",event="WIN",player_name="Krisz")),
        ]
        for gif, png in assets:
            gif_format, size, frames, duration = self._inspect(gif)
            self.assertEqual(gif_format, "GIF")
            self.assertGreaterEqual(size[0], 900)
            self.assertGreater(frames, 1)
            self.assertGreaterEqual(duration, 1500)
            png_format, png_size, png_frames, _ = self._inspect(png)
            self.assertEqual(png_format, "PNG")
            self.assertEqual(png_size[0], size[0])
            self.assertEqual(png_frames, 1)

    def test_player_branding_is_part_of_common_renderer(self) -> None:
        source = (ROOT / "app/casino_quick_visuals.py").read_text(encoding="utf-8")
        self.assertIn("'S GAME", source)
        self.assertIn("player_name", source)


class Casino3200SourceTests(unittest.TestCase):
    def test_highlow_is_streak_cashout_probability_based(self) -> None:
        source = (ROOT / "app/cogs/extras.py").read_text(encoding="utf-8")
        self.assertIn("class HighLowView", source)
        self.assertIn("_step_factor", source)
        self.assertIn("effective_probability", source)
        self.assertIn('label="Cash Out"', source)
        self.assertIn('child.disabled = self.streak <= 0 or self.multiplier <= 1.0', source)
        self.assertIn("Cash Out csak akkor érhető el, ha már van tényleges profitod", source)
        self.assertIn("Tie — a kör ugyanonnan folytatódik", source)

    def test_casino_lobby_exposes_quick_games_and_lottery(self) -> None:
        source = (ROOT / "app/cogs/casino.py").read_text(encoding="utf-8")
        for command in ('name="coinflip"', 'name="dice"', 'name="highlow"', 'name="rps"', 'name="chicken"', 'name="lottery"'):
            self.assertIn(command, source)
        self.assertIn("MONTHLY_JACKPOT_MIN_GAMES", (ROOT / "app/casino_config.py").read_text(encoding="utf-8"))

    def test_legacy_manual_jackpot_is_not_reachable_from_commands(self) -> None:
        source = (ROOT / "app/cogs/community.py").read_text(encoding="utf-8")
        prefix_start = source.index("async def jackpot_prefix")
        prefix_end = source.index("async def _lottery_loop", prefix_start)
        command_body = source[prefix_start:prefix_end]
        self.assertNotIn("_join_jackpot", command_body)
        self.assertIn("casino.jackpot_embed", command_body)
        help_source = (ROOT / "app/help_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("!jp 25k", help_source)

    def test_new_persistence_tables_are_reset_safe(self) -> None:
        source = (ROOT / "app/database.py").read_text(encoding="utf-8")
        for table in ("casino_jackpot_history", "lottery_history", "casino_monthly_jackpot", "casino_monthly_user_contrib"):
            self.assertIn(table, source)
        reset_section = source[source.index("async def reset_guild_economy"):]
        self.assertIn('"casino_jackpot_history"', reset_section)
        self.assertIn('"lottery_history"', reset_section)

    def test_tutorial_has_current_quick_game_and_jackpot_flow(self) -> None:
        source = (ROOT / "app/cogs/tutorial.py").read_text(encoding="utf-8")
        self.assertIn("streaket építesz", source)
        self.assertIn("25 Casino game VAGY 250k", source)
        self.assertNotIn("!hl high 10k", source)
        self.assertNotIn("!jp 25k", source)

    def test_release_metadata(self) -> None:
        self.assertGreaterEqual(tuple(map(int, (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))), (3, 20, 0))
        self.assertTrue((ROOT / "CHANGELOG_3.20.0.txt").exists())
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Quick & Community Rework (v3.20.0)", readme)


if __name__ == "__main__":
    unittest.main()
