from __future__ import annotations

import ast
import asyncio
from pathlib import Path
import unittest

from PIL import Image

from app.casino_visuals import EUROPEAN_WHEEL, render_roulette, render_roulette_animation, render_slots, render_slots_animation

ROOT = Path(__file__).resolve().parents[1]


class CasinoVisual3192Tests(unittest.TestCase):
    def test_slots_renderer_is_large_png_and_5x3_game_first(self) -> None:
        grid = [
            ["🍒", "🍋", "💎", "🔔", "7️⃣"],
            ["🍋", "⭐", "🍒", "💰", "🍇"],
            ["🔔", "🍇", "💎", "🍋", "🍒"],
        ]
        fp = render_slots(grid, stopped_columns=5, winning_positions={(1, 0), (1, 1), (1, 2)})
        image = Image.open(fp)
        self.assertGreaterEqual(image.width, 900)
        self.assertGreaterEqual(image.height, 500)
        self.assertEqual(image.format, "PNG")

    def test_roulette_renderer_is_european_wheel_with_37_pockets(self) -> None:
        self.assertEqual(len(EUROPEAN_WHEEL), 37)
        self.assertEqual(set(EUROPEAN_WHEEL), set(range(37)))
        fp = render_roulette(ball_number=18, result_number=18, phase="RESULT")
        image = Image.open(fp)
        self.assertGreaterEqual(image.width, 900)
        self.assertGreaterEqual(image.height, 600)
        self.assertEqual(image.format, "PNG")

    def test_blackjack_shows_dealer_upcard_value_and_hides_internal_id(self) -> None:
        source = (ROOT / "app/cogs/gambling.py").read_text(encoding="utf-8")
        self.assertIn("hand_value(self.dealer[:1])", source)
        self.assertIn('embed.set_footer(text="Yoru • Ász: 1 vagy 11 • Natural: 3:2")', source)
        self.assertNotIn('Natural: 3:2 • {self.session.game_id}', source)

    def test_slots_and_roulette_use_visual_attachments(self) -> None:
        source = (ROOT / "app/cogs/gambling.py").read_text(encoding="utf-8")
        self.assertIn('attachment://roulette.png', source)
        self.assertIn('slots.gif', source)
        self.assertIn('roulette.gif', source)
        self.assertIn('render_slots_animation', source)
        self.assertIn('render_roulette_animation', source)

    def test_roulette_player_ui_is_individual_and_has_requested_bets(self) -> None:
        source = (ROOT / "app/cogs/gambling.py").read_text(encoding="utf-8")
        self.assertIn("class RouletteView", source)
        for token in ['label="Piros"', 'label="Fekete"', 'label="Zöld / 0"', 'label="Páros"', 'label="Páratlan"', 'label="Konkrét szám"']:
            self.assertIn(token, source)
        self.assertNotIn("ROULETTE • KÖZÖS ASZTAL", source)
        self.assertNotIn("RouletteBetSelect", source)
        self.assertIn("egyéni kör", source)

    def test_player_displays_do_not_expose_game_ids(self) -> None:
        gambling = (ROOT / "app/cogs/gambling.py").read_text(encoding="utf-8")
        prefix = (ROOT / "app/cogs/prefix.py").read_text(encoding="utf-8")
        casino = (ROOT / "app/cogs/casino.py").read_text(encoding="utf-8")
        self.assertNotIn("game_id=result.game_id", gambling)
        self.assertNotIn('game_id=getattr(result, "game_id"', prefix)
        # Game IDs are intentionally present only in the admin settlement logger,
        # not the player history row.
        self.assertNotIn("`{row['game_id']}`", casino)
        self.assertIn('embed.add_field(name="Game ID"', casino)
        self.assertIn("CASINO_LOG_CHANNEL_KEY", casino)

    def test_settings_home_exposes_casino_log_configuration(self) -> None:
        settings = (ROOT / "app/cogs/settings.py").read_text(encoding="utf-8")
        casino = (ROOT / "app/cogs/casino.py").read_text(encoding="utf-8")
        self.assertIn('label="Casino"', settings)
        self.assertIn('CasinoSettingsView', casino)
        self.assertIn('PagedGuildChannelSelect', casino)
        self.assertIn('set_settlement_listener', casino)

    def test_player_facing_modules_have_no_v2_marketing_literal(self) -> None:
        for path in [ROOT / "app/cogs/gambling.py", ROOT / "app/cogs/casino.py", ROOT / "app/cogs/tutorial.py", ROOT / "app/help_ui.py"]:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            literals = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
            self.assertFalse([v for v in literals if "V2" in v], path)

    def test_release_metadata(self) -> None:
        self.assertGreaterEqual(tuple(map(int, (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))), (3, 19, 2))
        self.assertTrue((ROOT / "CHANGELOG_3.19.2.txt").exists())


if __name__ == "__main__":
    unittest.main()
