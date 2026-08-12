from __future__ import annotations

import ast
from pathlib import Path
import unittest

from app.casino_games import generate_slot_grid, run_slots_feature

ROOT = Path(__file__).resolve().parents[1]


class CasinoHotfix3191Tests(unittest.TestCase):
    def test_slots_runtime_works_without_injected_rng(self) -> None:
        grid = generate_slot_grid()
        self.assertEqual(len(grid), 3)
        self.assertTrue(all(len(row) == 5 for row in grid))
        spins = run_slots_feature(100_000)
        self.assertGreaterEqual(len(spins), 1)
        self.assertEqual(len(spins[0].grid), 3)

    def test_blackjack_uses_large_card_faces(self) -> None:
        source = (ROOT / "app/cogs/gambling.py").read_text(encoding="utf-8")
        self.assertIn("def blackjack_cards_block", source)
        self.assertIn("╭───────╮", source)
        self.assertIn('title="🃏 BLACKJACK"', source)
        self.assertIn("max_per_row: int = 4", source)

    def test_blackjack_has_opening_and_draw_animation(self) -> None:
        source = (ROOT / "app/cogs/gambling.py").read_text(encoding="utf-8")
        prefix = (ROOT / "app/cogs/prefix.py").read_text(encoding="utf-8")
        self.assertIn("animate_opening", source)
        self.assertIn("BLACKJACK_DEAL_FRAME_DELAY", source)
        self.assertIn("BLACKJACK_PLAYER_DRAW_DELAY", source)
        self.assertIn("hide_active_last=True", source)
        self.assertIn("deal_stage=0", source)
        self.assertIn("animate_opening", prefix)

    def test_player_facing_casino_strings_do_not_say_v2(self) -> None:
        targets = [
            ROOT / "app/cogs/casino.py",
            ROOT / "app/cogs/tutorial.py",
            ROOT / "app/help_ui.py",
            ROOT / "app/cogs/gambling.py",
        ]
        for path in targets:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            literals = [
                node.value
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            ]
            bad = [value for value in literals if "V2" in value]
            self.assertEqual(bad, [], f"Player-facing V2 string left in {path}: {bad}")

    def test_blackjack_old_marketing_copy_is_gone(self) -> None:
        source = (ROOT / "app/cogs/gambling.py").read_text(encoding="utf-8")
        self.assertNotIn("klasszikusabb Yoru Blackjack", source)
        self.assertNotIn("BLACKJACK V2", source)
        self.assertIn('title="🃏 BLACKJACK"', source)

    def test_release_metadata(self) -> None:
        version = tuple(map(int, (ROOT / "VERSION").read_text(encoding="utf-8").strip().split(".")))
        self.assertGreaterEqual(version, (3, 19, 1))
        self.assertTrue((ROOT / "CHANGELOG_3.19.1.txt").exists())


if __name__ == "__main__":
    unittest.main()
