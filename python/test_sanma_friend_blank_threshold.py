"""Tests use the repository blank-row template, not a natural animation corpus."""
import unittest
from PIL import Image
from sanma_friend_discard_experiment import friend_empty_first_two_pixels

class FriendBlankThresholdTests(unittest.TestCase):
    def setUp(self):
        self.empty = Image.open('test/fixtures/sanma-button-rows/empty.png').convert('RGB')

    def frame(self):
        frame = Image.new('RGB', (1920, 1080))
        frame.paste(self.empty, (600, 785))
        return frame

    def test_single_pixel_boundary_in_each_slot(self):
        for x in (610, 900):
            for delta, expected in ((30, True), (31, True), (40, True), (41, False)):
                with self.subTest(x=x, delta=delta):
                    image = self.frame()
                    pixel = image.getpixel((x, 800))
                    channel = next(i for i, value in enumerate(pixel) if value <= 255 - delta)
                    changed = list(pixel)
                    changed[channel] += delta
                    image.putpixel((x, 800), tuple(changed))
                    self.assertEqual(friend_empty_first_two_pixels(image), expected)

    def test_rendered_buttons_in_first_two_slots_rejected(self):
        for name in ('pon-kan', 'kita2', 'tsumo', 'riichi', 'kita'):
            row = Image.open('test/fixtures/sanma-button-rows/' + name + '.png').convert('RGB')
            frame = Image.new('RGB', (1920, 1080))
            frame.paste(row, (600, 785))
            with self.subTest(name=name):
                self.assertFalse(friend_empty_first_two_pixels(frame))

if __name__ == '__main__':
    unittest.main()
