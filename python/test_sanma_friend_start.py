import io
import unittest
from pathlib import Path
from unittest.mock import Mock

from PIL import Image, ImageDraw

from friend_start import await_reviewed_friend_room, reviewed_sanma_300_plus_zero, verified_friend_room


class SanmaFriendPreflightTests(unittest.TestCase):
    """Test label and reviewed-image binding, not independent CPU/ready OCR.

    These isolated helper tests neither exercise operator startup nor prove
    sanma gameplay is ready for use.
    """
    @classmethod
    def setUpClass(cls):
        cls.frame = (Path(__file__).resolve().parents[1] / 'test/fixtures/sanma-friend-preflight.png').read_bytes()

    def changed(self, box):
        image = Image.open(io.BytesIO(self.frame)).convert('RGB')
        ImageDraw.Draw(image).rectangle(box, fill='black')
        result = io.BytesIO()
        image.save(result, format='PNG')
        return result.getvalue()

    def test_native_sanma_count_and_clock_and_existing_room_binding(self):
        self.assertTrue(reviewed_sanma_300_plus_zero(self.frame))
        self.assertTrue(verified_friend_room(self.frame, self.frame, sanma=True))
        for box in ((1670, 187, 1805, 218), (1670, 260, 1810, 290),
                    (975, 77, 988, 100), (1730, 355, 1744, 375),
                    (310, 700, 325, 720), (500, 700, 515, 720), (900, 700, 915, 720)):
            with self.subTest(box=box):
                self.assertFalse(verified_friend_room(self.changed(box), self.frame, sanma=True))

    def test_default_start_path_rejects_identified_sanma_room(self):
        self.assertFalse(verified_friend_room(self.frame, self.frame))
        page = Mock()
        page.screenshot.return_value = self.frame
        with self.assertRaises(RuntimeError):
            await_reviewed_friend_room(page, self.frame, attempts=2)
        page.mouse.click.assert_not_called()
        self.assertTrue(verified_friend_room(self.frame, self.frame, sanma=True))

    def test_both_current_and_reviewed_must_identify_count_and_clock(self):
        for box in ((1670, 187, 1805, 218), (1670, 260, 1810, 290)):
            altered = self.changed(box)
            self.assertFalse(reviewed_sanma_300_plus_zero(altered))
            self.assertFalse(verified_friend_room(altered, altered, sanma=True))
        self.assertFalse(reviewed_sanma_300_plus_zero(b'invalid'))

    def test_consecutive_captures_and_no_start_click(self):
        page = Mock()
        changed = self.changed((1670, 187, 1805, 218))
        page.screenshot.side_effect = [self.frame, changed, self.frame, self.frame]
        self.assertEqual(await_reviewed_friend_room(page, self.frame, attempts=4, sanma=True), 4)
        page.mouse.click.assert_not_called()
        page.screenshot.side_effect = [changed] * 3
        with self.assertRaises(RuntimeError):
            await_reviewed_friend_room(page, self.frame, attempts=3, sanma=True)
        page.mouse.click.assert_not_called()

    def test_native_yonma_label_is_rejected_as_sanma(self):
        image = Image.open(io.BytesIO(self.frame)).convert('RGB')
        fixture = Path(__file__).resolve().parents[1] / 'test/fixtures/yonma-friend-label.png'
        image.paste(Image.open(fixture), (1670, 187))
        out = io.BytesIO()
        image.save(out, format='PNG')
        self.assertFalse(reviewed_sanma_300_plus_zero(out.getvalue()))
        self.assertFalse(verified_friend_room(out.getvalue(), out.getvalue(), sanma=True))
