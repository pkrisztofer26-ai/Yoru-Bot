from __future__ import annotations

import ast
from pathlib import Path
import unittest

from app import casino_config as cfg
from app.casino_games import (
    RouletteBet,
    evaluate_roulette_bets,
    evaluate_slot_grid,
    parse_roulette_choice,
    roulette_bet_wins,
    simulate_slots_rtp,
)


ROOT = Path(__file__).resolve().parents[1]


class CasinoMainReworkEngineTests(unittest.TestCase):
    def test_blackjack_v2_balance_constants(self) -> None:
        self.assertEqual(cfg.BLACKJACK_WIN_TOTAL_PAYOUT, 2.0)
        self.assertEqual(cfg.BLACKJACK_NATURAL_TOTAL_PAYOUT, 2.5)
        self.assertEqual(cfg.BLACKJACK_INSURANCE_TOTAL_PAYOUT, 3.0)

    def test_slots_v2_shape_features_and_rtp(self) -> None:
        self.assertEqual(len(cfg.SLOTS_V2_PAYLINES), 20)
        self.assertEqual(len(cfg.SLOTS_V2_SYMBOLS), 8)
        self.assertIn(cfg.SLOTS_V2_WILD, cfg.SLOTS_V2_SYMBOLS)
        self.assertIn(cfg.SLOTS_V2_SCATTER, cfg.SLOTS_V2_SYMBOLS)
        rtp = simulate_slots_rtp(50_000, seed=3190)
        self.assertGreaterEqual(rtp, 0.92)
        self.assertLessEqual(rtp, 0.97)

    def test_slots_wild_substitutes_and_scatter_awards_free_spins(self) -> None:
        # Top line is cherry/wild/cherry/cherry/cherry; three scatters elsewhere.
        grid = [
            ["🍒", "⭐", "🍒", "🍒", "🍒"],
            ["💰", "🍋", "🍇", "🔔", "💎"],
            ["🍇", "💰", "🔔", "💰", "7️⃣"],
        ]
        line_wins, scatter_count, multiplier, free_spins = evaluate_slot_grid(grid)
        self.assertEqual(scatter_count, 3)
        self.assertEqual(free_spins, 5)
        self.assertGreater(multiplier, 0)
        self.assertTrue(any(win.symbol == "🍒" and win.count == 5 for win in line_wins))

    def test_roulette_v2_all_first_release_bet_types(self) -> None:
        values = [
            "red", "black", "even", "odd", "low", "high",
            "dozen1", "dozen2", "dozen3", "column1", "column2", "column3", "0", "36",
        ]
        for value in values:
            with self.subTest(value=value):
                kind, number = parse_roulette_choice(value)
                self.assertTrue(kind)
                if value.isdigit():
                    self.assertEqual(kind, "number")
                    self.assertEqual(number, int(value))

    def test_roulette_classic_v2_payouts(self) -> None:
        bets = [
            RouletteBet("red", 100_000),
            RouletteBet("dozen1", 50_000),
            RouletteBet("number", 10_000, 9),
        ]
        payout, wins = evaluate_roulette_bets(bets, 9)
        self.assertEqual(payout, 100_000 * 2 + 50_000 * 3 + 10_000 * 36)
        self.assertEqual(len(wins), 3)
        self.assertFalse(roulette_bet_wins(RouletteBet("even", 1), 0))


class CasinoMainReworkSourceTests(unittest.TestCase):
    def test_blackjack_v2_ui_and_extra_reservations_exist(self) -> None:
        source = (ROOT / "app/cogs/gambling.py").read_text(encoding="utf-8")
        for token in ["BLACKJACK", "Double", "Split", "Insurance", "BLACKJACK_NATURAL_TOTAL_PAYOUT", "reserve_blackjack_extra"]:
            self.assertIn(token, source)
        self.assertIn("dealer", source.lower())
        self.assertIn("BLACKJACK_DEALER_FRAME_DELAY", source)

    def test_slots_v2_uses_animated_5x3_engine(self) -> None:
        source = (ROOT / "app/cogs/gambling.py").read_text(encoding="utf-8")
        service = (ROOT / "app/services/gambling.py").read_text(encoding="utf-8")
        self.assertIn("🎰 SLOTS", source)
        self.assertIn("stopped_columns", source)
        self.assertIn("slots_v2", service)
        self.assertIn("run_slots_feature", service)

    def test_roulette_engine_keeps_full_bet_math_for_compatibility(self) -> None:
        # v3.19.2 moved the player UX from the temporary shared table to an
        # individual wheel. The broad bet parser/math remains backwards
        # compatible so old integrations and stored analytics still work.
        source = (ROOT / "app/services/gambling.py").read_text(encoding="utf-8")
        ui = (ROOT / "app/cogs/gambling.py").read_text(encoding="utf-8")
        self.assertIn("async def roulette(", source)
        self.assertIn("evaluate_roulette_bets", source)
        self.assertIn("RouletteView", ui)
        self.assertIn("render_roulette", ui)
        self.assertNotIn("ROULETTE • KÖZÖS ASZTAL", ui)

    def test_casino_group_has_main_game_entrypoints_without_new_top_level_group(self) -> None:
        source = (ROOT / "app/cogs/casino.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        funcs = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertTrue({"blackjack", "slots", "roulette", "lobby", "stats", "history", "jackpot"}.issubset(funcs))
        self.assertIn('group_name="casino"', source)

    def test_prefix_shortcuts_use_v2_shared_entrypoints(self) -> None:
        source = (ROOT / "app/cogs/prefix.py").read_text(encoding="utf-8")
        self.assertIn("run_slots_prefix", source)
        self.assertIn("open_roulette_prefix", source)
        self.assertIn("start_blackjack", source)

    def test_release_metadata_and_animation_budget(self) -> None:
        self.assertGreaterEqual(tuple(map(int, (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))), (3, 19, 0))
        self.assertTrue((ROOT / "CHANGELOG_3.19.0.txt").exists())
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        tutorial = (ROOT / "app/cogs/tutorial.py").read_text(encoding="utf-8")
        self.assertIn("Casino • Main Rework", readme)
        self.assertIn("Blackjack", tutorial)
        self.assertLessEqual(cfg.BLACKJACK_DEALER_MAX_FRAMES, 6)
        self.assertLessEqual(cfg.ROULETTE_V2_SPIN_FRAMES, 20)


if __name__ == "__main__":
    unittest.main()
