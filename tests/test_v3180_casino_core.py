from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest

# Lightweight aiosqlite shim for the artifact test environment.
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

    _module = types.ModuleType("aiosqlite")
    _module.Connection = _Connection
    _module.Row = sqlite3.Row
    _module.connect = lambda path: _Connection(path)
    sys.modules["aiosqlite"] = _module

from app import casino_config as cfg
from app import economy_config as eco
from app.database import Database
from app.services.casino import CasinoService

ROOT = Path(__file__).resolve().parents[1]

class _FakeGuildSettings:
    async def prepare_currency(self, guild_id): return None
    async def require_feature(self, guild_id, feature): return None
    async def get_gambling_payout_multiplier(self, guild_id): return 1.0



class CasinoCoreDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "casino.db")
        self.db = Database(self.path, 0)
        await self.db.initialize()
        self.casino = CasinoService(self.db, _FakeGuildSettings())
        await self.db.ensure_user(1, 100)
        await self.db.set_wallet(1, 100, 10_000_000, "test_seed")

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_reservation_and_idempotent_settlement(self) -> None:
        session = await self.casino.begin(1, 100, "coinflip", 1_000_000)
        wallet, _ = await self.db.get_balance(1, 100)
        self.assertEqual(wallet, 9_000_000)

        first = await self.casino.settle(session, 1_900_000, result="win")
        self.assertEqual(first.profit, 900_000)
        self.assertEqual(first.wallet, 10_900_000)
        second = await self.casino.settle(session, 1_900_000, result="win")
        self.assertTrue(second.idempotent)
        self.assertEqual(second.wallet, 10_900_000)
        wallet, _ = await self.db.get_balance(1, 100)
        self.assertEqual(wallet, 10_900_000)

        con = sqlite3.connect(self.path)
        try:
            payout_rows = con.execute(
                "SELECT COUNT(*) FROM casino_ledger WHERE game_id=? AND entry_key='settlement'",
                (session.game_id,),
            ).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(payout_rows, 1)

    async def test_reserved_money_cannot_be_spent_twice_and_supports_billions(self) -> None:
        await self.db.set_wallet(1, 100, 2_500_000_000, "large_seed")
        session = await self.casino.begin(1, 100, "blackjack", 2_500_000_000)
        with self.assertRaisesRegex(ValueError, "Már fut egy Casino játékod"):
            await self.casino.begin(1, 100, "coinflip", cfg.MIN_BET)
        refunded = await self.casino.refund(session, "test")
        self.assertEqual(refunded["wallet_after"], 2_500_000_000)

    async def test_monthly_jackpot_gets_only_real_house_loss(self) -> None:
        loss = await self.casino.begin(1, 100, "dice", 1_000_000)
        settled = await self.casino.settle(loss, 0, result="lose")
        self.assertEqual(settled.jackpot_contribution, 20_000)
        jackpot = await self.casino.monthly_jackpot(1, 100)
        self.assertEqual(jackpot["pool"], 20_000)
        self.assertEqual(jackpot["user_contributed"], 20_000)

        # PvP/escrow-like settlement explicitly opts out of the house-loss hook.
        await self.db.set_wallet(1, 100, 2_000_000, "pvp_seed")
        pvp = await self.casino.begin(1, 100, "coinflip", 1_000_000)
        await self.casino.settle(pvp, 0, result="pvp_loss", house_loss_eligible=False)
        jackpot2 = await self.casino.monthly_jackpot(1, 100)
        self.assertEqual(jackpot2["pool"], 20_000)

    async def test_restart_recovery_refunds_open_session_once(self) -> None:
        session = await self.casino.begin(1, 100, "blackjack", 2_000_000)
        await self.casino.mark_waiting(session.game_id)
        recovered = await self.casino.recover_after_restart()
        self.assertEqual(len(recovered), 1)
        wallet, _ = await self.db.get_balance(1, 100)
        self.assertEqual(wallet, 10_000_000)
        recovered_again = await self.casino.recover_after_restart()
        self.assertEqual(recovered_again, [])

    async def test_summary_history_and_required_stats(self) -> None:
        a = await self.casino.begin(1, 100, "coinflip", 1_000_000)
        await self.casino.settle(a, 1_900_000, result="heads", multiplier=1.9)
        b = await self.casino.begin(1, 100, "dice", 500_000)
        await self.casino.settle(b, 0, result="lose", multiplier=0.0)
        summary = await self.casino.summary(1, 100)
        self.assertEqual(summary["games"], 2)
        self.assertEqual(summary["wins"], 1)
        self.assertEqual(summary["losses"], 1)
        self.assertEqual(summary["wagered"], 1_500_000)
        self.assertEqual(summary["payout"], 1_900_000)
        self.assertEqual(summary["profit"], 400_000)
        self.assertEqual(summary["biggest_bet"], 1_000_000)
        self.assertAlmostEqual(summary["highest_multiplier"], 1.9)
        history = await self.casino.history(1, 100)
        self.assertEqual(len(history), 2)
        self.assertTrue(history[0]["game_id"])

        stats = await self.db.get_user_statistics(1, 100, prefix="gambling")
        self.assertEqual(stats["gambling.plays"], 2)
        self.assertEqual(stats["gambling.wagered"], 1_500_000)
        self.assertEqual(stats["gambling.payout"], 1_900_000)
        self.assertEqual(stats["gambling.biggest_bet"], 1_000_000)
        self.assertEqual(stats["gambling.highest_multiplier_x1000"], 1900)

    async def test_payout_config_is_snapshotted_per_session(self) -> None:
        session = await self.casino.begin(1, 100, "coinflip", 1_000_000)
        original = self.casino.scaled_total_payout(2.0, session)
        session.config["payout_scale"] = 0.5
        changed = self.casino.scaled_total_payout(2.0, session)
        self.assertNotEqual(original, changed)
        # Reloading from DB restores the immutable start snapshot, not the local mutation.
        row = await self.db.get_casino_session(session.game_id)
        self.assertEqual(self.casino.scaled_total_payout(2.0, row), original)
        await self.casino.refund(session, "test")


class CasinoCoreSourceTests(unittest.TestCase):
    def test_central_config_and_compatibility_aliases(self) -> None:
        self.assertEqual(eco.GAMBLING_MIN_BET, cfg.MIN_BET)
        self.assertEqual(eco.COINFLIP_TOTAL_PAYOUT, cfg.COINFLIP_TOTAL_PAYOUT)
        gambling = (ROOT / "app/services/gambling.py").read_text(encoding="utf-8")
        extras = (ROOT / "app/services/extras.py").read_text(encoding="utf-8")
        self.assertIn("casino_cfg.COINFLIP_TOTAL_PAYOUT", gambling)
        self.assertIn("self.casino.begin", gambling)
        self.assertIn("self.casino.begin", extras)

    def test_restart_recovery_and_casino_group_are_loaded(self) -> None:
        main = (ROOT / "app/main.py").read_text(encoding="utf-8")
        casino_cog = (ROOT / "app/cogs/casino.py").read_text(encoding="utf-8")
        self.assertIn("recover_after_restart", main)
        self.assertIn("CasinoCog(self, self.casino", main)
        self.assertIn('group_name="casino"', casino_cog)
        self.assertIn("CasinoLobbyView", casino_cog)

    def test_release_metadata(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertGreaterEqual(tuple(map(int, version.split("."))), (3, 18, 0))
        changelog = (ROOT / "CHANGELOG_3.18.0.txt").read_text(encoding="utf-8")
        roadmap = (ROOT / "CASINO_ROADMAP.md").read_text(encoding="utf-8")
        self.assertIn("Casino V2 Phase 1", changelog)
        self.assertIn("Casino Core", changelog)
        self.assertIn("Yoru Casino", roadmap)

    def test_database_uses_immediate_transactions_and_unique_settlement_key(self) -> None:
        source = (ROOT / "app/database.py").read_text(encoding="utf-8")
        self.assertIn('await db.execute("BEGIN IMMEDIATE")', source)
        self.assertIn("UNIQUE(game_id, entry_key)", source)
        self.assertIn("casino_monthly_jackpot", source)


if __name__ == "__main__":
    unittest.main()
