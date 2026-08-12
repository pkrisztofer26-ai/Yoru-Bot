from __future__ import annotations

from io import BytesIO
from pathlib import Path
import unittest

from PIL import Image

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

ROOT = Path(__file__).resolve().parents[1]


class Casino3201QuickVisualTests(unittest.TestCase):
    @staticmethod
    def _gif_stats(fp: BytesIO) -> tuple[int, int, int]:
        image = Image.open(fp)
        durations = []
        hashes = set()
        for i in range(image.n_frames):
            image.seek(i)
            durations.append(int(image.info.get("duration", 0)))
            hashes.add(hash(image.convert("RGB").tobytes()))
        return image.n_frames, sum(durations), len(hashes)

    def test_static_quick_games_use_large_mobile_safe_canvas(self) -> None:
        samples = [
            render_coinflip("írás", player_name="Pajkos Paripa"),
            render_dice((5, 3), player_name="Pajkos Paripa", mode_label="OVER / UNDER 7"),
            render_rps("rock", "scissors", player_name="Pajkos Paripa"),
            render_highlow(7, 11, player_name="Pajkos Paripa", phase="REVEAL", multiplier=2.35, streak=3),
            render_chicken(64, 0, opponent="Piros Taraj", event="K.O.!", player_name="Pajkos Paripa"),
        ]
        for fp in samples:
            image = Image.open(fp)
            self.assertEqual(image.width, 960)
            self.assertGreaterEqual(image.height, 640)

    def test_animations_have_real_motion_and_suspense(self) -> None:
        coin = self._gif_stats(render_coinflip_animation("írás", player_name="Pajkos Paripa"))
        dice = self._gif_stats(render_dice_animation((5, 3), player_name="Pajkos Paripa", mode_label="OVER / UNDER 7"))
        rps = self._gif_stats(render_rps_animation("rock", "scissors", player_name="Pajkos Paripa"))
        highlow = self._gif_stats(render_highlow_animation(7, 11, player_name="Pajkos Paripa", multiplier=2.35, streak=3))
        chicken = self._gif_stats(render_chicken_animation([(100, 85, "HIT"), (88, 85, "COUNTER"), (88, 50, "CRIT"), (64, 0, "K.O.!")], opponent="Piros Taraj", player_name="Pajkos Paripa"))

        self.assertGreaterEqual(coin[0], 20)
        self.assertGreaterEqual(coin[2], 12)
        self.assertGreaterEqual(coin[1], 3000)
        self.assertGreaterEqual(dice[2], 6)
        self.assertGreaterEqual(rps[0], 5)
        self.assertGreaterEqual(highlow[0], 5)
        self.assertGreaterEqual(chicken[2], 5)

    def test_shared_header_has_dedicated_owner_badge_row(self) -> None:
        source = (ROOT / "app/casino_quick_visuals.py").read_text(encoding="utf-8")
        self.assertIn("Row 2 is exclusively the", source)
        self.assertIn("draw.line((42, 78, 918, 78)", source)
        self.assertIn("_rr(draw, (x1, 90, x1 + badge_w, 128)", source)

    def test_release_metadata(self) -> None:
        self.assertGreaterEqual(tuple(map(int, (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))), (3, 20, 1))
        self.assertTrue((ROOT / "CHANGELOG_3.20.1.txt").exists())
        self.assertIn("Quick Visual Polish (v3.20.1)", (ROOT / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
