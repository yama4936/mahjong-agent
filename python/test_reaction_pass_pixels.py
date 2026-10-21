import io
import unittest
from pathlib import Path

from PIL import Image
from auto_operator import pass_button_color_fractions, is_force_auto_pass_clip, is_contextual_reaction_pass


class ReactionPassPixelTests(unittest.TestCase):
    def test_native_masks_preserve_strict_color_boundaries(self):
        # Every red/green pair, with blue on both sides of each actual cutoff.
        for blue in [0, 99, 100, 119, 120, 124, 125, 255]:
            colors = [(red, green, blue) for red in range(256) for green in range(256)]
            image = Image.new('RGB', (256, 256))
            image.putdata(colors)
            dark = sum(r < 80 and g < 90 and b < 100 for r, g, b in colors) / len(colors)
            warm = sum(r > 120 and g > 95 and b < 100 for r, g, b in colors) / len(colors)
            for contextual, tolerance, blue_limit in [(False, 25, 120), (True, 30, 125)]:
                neutral = sum(abs(r - g) < tolerance and r > 110 and b < blue_limit
                              for r, g, b in colors) / len(colors)
                self.assertEqual(pass_button_color_fractions(image, contextual=contextual),
                                 (dark, warm, neutral), (blue, contextual))
        for color in [(111, 87, 119), (111, 86, 119), (111, 140, 124),
                      (111, 141, 124), (110, 110, 119), (111, 111, 125)]:
            r, g, b = color
            for contextual, tolerance, blue_limit in [(False, 25, 120), (True, 30, 125)]:
                actual = pass_button_color_fractions(Image.new('RGB', (1, 1), color), contextual=contextual)
                self.assertEqual(actual[2], float(abs(r-g) < tolerance and r > 110 and b < blue_limit))

    def test_actual_ranked_call_skip_crops_keep_context_requirement(self):
        # Lossless crops of sample18 18:14:21.474951 and sample19
        # 18:27:41.179743, using config/layout.json's pass rectangle.
        root = Path(__file__).resolve().parents[1] / 'test' / 'fixtures'
        for name in ['reaction-pass-pon7p-20261021.png', 'reaction-pass-white-20261021.png']:
            frame = (root / name).read_bytes()
            with Image.open(io.BytesIO(frame)) as image:
                region = {'x': 0, 'y': 0, 'width': image.width, 'height': image.height}
            self.assertFalse(is_force_auto_pass_clip(frame), name)
            self.assertTrue(is_contextual_reaction_pass(frame, region, 1), name)
            self.assertFalse(is_contextual_reaction_pass(frame, region, 0), name)


if __name__ == '__main__':
    unittest.main()
