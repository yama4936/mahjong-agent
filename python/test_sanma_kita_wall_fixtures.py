"""Portable wall-color veto checks using anonymized real image crops."""
import io
import unittest
from pathlib import Path
from PIL import Image
from auto_operator import experimental_kita_wall_color_stable

FIXTURES = Path(__file__).parent / 'fixtures' / 'sanma-wall-color'

def frame(name, *, gray=False):
    crop = Image.open(FIXTURES / name).convert('RGB')
    if crop.size != (240, 620):
        raise ValueError('unexpected fixture dimensions')
    if gray:
        crop = crop.convert('L').convert('RGB')
    image = Image.new('RGB', (1920, 1080), (25, 35, 55))
    image.paste(crop, (150, 80))
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()

class WallColorFixtureTest(unittest.TestCase):
    def test_recorded_lighting_pairs_pass_color_guard(self):
        for i in range(5):
            with self.subTest(pair=i):
                self.assertTrue(experimental_kita_wall_color_stable(frame(f'light-{i}.png'),frame(f'light-{i+1}.png')))

    def test_recorded_opponent_change_rejected(self):
        self.assertFalse(experimental_kita_wall_color_stable(frame('opponent-before.png'), frame('opponent-after.png')))

    def test_synthetic_equal_luminance_grayscale_rejected(self):
        self.assertFalse(experimental_kita_wall_color_stable(frame('light-3.png'),frame('light-3.png',gray=True)))
