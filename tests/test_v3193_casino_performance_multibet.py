from __future__ import annotations

from pathlib import Path
import unittest

from PIL import Image

from app import casino_config as cfg
from app.casino_games import run_slot_spin, simulate_slots_rtp
from app.casino_visuals import render_roulette_animation, render_slots_animation

ROOT = Path(__file__).resolve().parents[1]


class CasinoPerformance3193Tests(unittest.TestCase):
    def test_slots_has_20_unique_paylines_and_target_rtp(self) -> None:
        self.assertEqual(len(cfg.SLOTS_V2_PAYLINES), 20)
        self.assertEqual(len(set(cfg.SLOTS_V2_PAYLINES)), 20)
        rtp = simulate_slots_rtp(100_000, seed=3193)
        self.assertGreaterEqual(rtp, 0.92)
        self.assertLessEqual(rtp, 0.97)

    def test_visual_animations_are_single_gifs(self) -> None:
        spin = run_slot_spin(100_000)
        slots_fp = render_slots_animation(spin.grid)
        slots_img = Image.open(slots_fp)
        self.assertEqual(slots_img.format, "GIF")
        self.assertGreaterEqual(getattr(slots_img, "n_frames", 1), 6)

        roulette_fp = render_roulette_animation(18, frame_count=cfg.ROULETTE_V2_SPIN_FRAMES)
        roulette_img = Image.open(roulette_fp)
        self.assertEqual(roulette_img.format, "GIF")
        self.assertGreaterEqual(getattr(roulette_img, "n_frames", 1), 5)

    def test_slots_does_not_reveal_result_before_animation(self) -> None:
        source = (ROOT / "app/cogs/gambling.py").read_text(encoding="utf-8")
        self.assertIn('embed.add_field(name="💸 Win", value="**…**"', source)
        self.assertIn('embed.add_field(name="✖️ Multiplier", value="**…**"', source)
        self.assertIn('image_filename="slots.gif"', source)

    def test_render_work_is_off_event_loop_and_bounded(self) -> None:
        source = (ROOT / "app/cogs/gambling.py").read_text(encoding="utf-8")
        self.assertIn("asyncio.to_thread", source)
        self.assertIn("asyncio.Semaphore", source)
        self.assertIn("render_slots_animation", source)
        self.assertIn("render_roulette_animation", source)
        self.assertNotIn("for stopped in range(1, 6)", source)

    def test_roulette_ui_and_service_are_individual_multibet(self) -> None:
        source = (ROOT / "app/cogs/gambling.py").read_text(encoding="utf-8")
        service = (ROOT / "app/services/gambling.py").read_text(encoding="utf-8")
        self.assertIn('label="Pörgetés"', source)
        self.assertIn("reserve_roulette_bet", service)
        self.assertIn("settle_roulette_bets", service)
        self.assertIn("reserve_extra", service)
        self.assertIn("ROULETTE_V2_MAX_BETS_PER_PLAYER", source)
        self.assertIn("roulette_timeout", source)
        self.assertIn("roulette_user_cancel", source)

    def test_release_metadata(self) -> None:
        self.assertGreaterEqual(tuple(map(int, (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))), (3, 19, 3))
        self.assertTrue((ROOT / "CHANGELOG_3.19.3.txt").exists())


if __name__ == "__main__":
    unittest.main()
