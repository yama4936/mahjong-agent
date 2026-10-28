import io
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from friend_start import verified_friend_room


class FriendStartTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "artifacts/friend-300-a20c2cd-20261028/preflight-room.png"
        if not path.exists():
            self.skipTest("native friend-room preflight unavailable")
        self.frame = path.read_bytes()

    def changed(self, box):
        image = Image.open(io.BytesIO(self.frame)).convert("RGB")
        ImageDraw.Draw(image).rectangle(box, fill="black")
        out = io.BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()

    def test_reviewed_room_and_controls_are_required(self):
        self.assertTrue(verified_friend_room(self.frame, self.frame))
        for box in ((190, 45, 360, 115), (1000, 955, 1280, 1040),
                    (700, 40, 1100, 120), (1610, 175, 1870, 900),
                    (470, 650, 830, 910)):
            with self.subTest(box=box):
                self.assertFalse(verified_friend_room(self.changed(box), self.frame))

    def test_invalid_reference_and_nonroom_are_rejected(self):
        self.assertFalse(verified_friend_room(self.frame, b"not an image"))
        blank = Image.new("RGB", (1920, 1080))
        out = io.BytesIO()
        blank.save(out, format="PNG")
        self.assertFalse(verified_friend_room(out.getvalue(), out.getvalue()))
