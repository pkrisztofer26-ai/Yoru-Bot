from io import BytesIO
from pathlib import Path
import unittest
from PIL import Image
from app import casino_pvp_visuals as pvp

ROOT = Path(__file__).resolve().parents[1]

class PvpLayoutRebuildTests(unittest.TestCase):
    def test_release(self):
        self.assertGreaterEqual(tuple(map(int, (ROOT/'VERSION').read_text(encoding='utf-8').strip().split('.'))), (3, 21, 2))
        self.assertTrue((ROOT/'CHANGELOG_3.21.2.txt').exists())

    def test_renderer_uses_bbox_optical_centering_and_three_cards(self):
        src=(ROOT/'app'/'casino_pvp_visuals.py').read_text(encoding='utf-8')
        self.assertIn('draw.textbbox((0, 0), text, font=font)', src)
        self.assertIn('cards = ((54, 548, 326, 622), (344, 548, 616, 622), (634, 548, 906, 622))', src)
        self.assertIn('_winner_banner(draw, winner_name)', src)
        self.assertIn('_draw_centered(draw, (cx, score_y), str(score)', src)

    def test_static_samples_render(self):
        payloads=[
            pvp.render_pvp_dice('Pajkos Paripa','Styuvless',100_000,72,88,'Pajkos Paripa'),
            pvp.render_pvp_coinflip('Pajkos Paripa','Styuvless',100_000,'Pajkos Paripa'),
            pvp.render_pvp_rps('Pajkos Paripa','Styuvless',100_000,'rock','scissors','Pajkos Paripa'),
        ]
        for payload in payloads:
            with Image.open(BytesIO(payload.getvalue())) as im:
                self.assertEqual(im.size,(960,640))
                self.assertEqual(im.format,'PNG')

if __name__=='__main__':
    unittest.main()
