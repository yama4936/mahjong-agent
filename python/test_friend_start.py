import io
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from friend_start import await_reviewed_friend_room, reviewed_friend_clock_is_300_plus_zero, verified_friend_room


class FriendStartRetryTests(unittest.TestCase):
    def test_transient_mismatch_requires_fresh_consecutive_matches(self):
        page = Mock()
        page.screenshot.side_effect = [b"1", b"2", b"3", b"4", b"5"]
        with patch("friend_start.verified_friend_room", side_effect=[True, False, True, True]) as verify:
            self.assertEqual(await_reviewed_friend_room(page, b"reviewed"), 4)
        self.assertEqual(verify.call_count, 4)
        page.mouse.click.assert_not_called()

    def test_intermittent_matches_or_persistent_change_never_authorize(self):
        for checks in ([True, False] * 4, [False] * 8):
            page = Mock()
            with patch("friend_start.verified_friend_room", side_effect=checks):
                with self.assertRaises(RuntimeError):
                    await_reviewed_friend_room(page, b"reviewed")
            page.mouse.click.assert_not_called()

    def test_native_overlay_sequence_recovers_without_relaxing_match(self):
        directory = Path(__file__).resolve().parents[1] / "artifacts/friend-300-b864bfc-20261028"
        paths = [directory / f"analysis-frame-{i}.png" for i in range(4)]
        preflight = directory / "preflight-room.png"
        if not preflight.exists() or not all(path.exists() for path in paths):
            self.skipTest("native overlay sequence unavailable")
        page = Mock()
        page.screenshot.side_effect = [path.read_bytes() for path in paths]
        self.assertEqual(await_reviewed_friend_room(page, preflight.read_bytes(), attempts=4), 4)
        page.mouse.click.assert_not_called()

    def test_native_preflight_particle_above_id_does_not_block(self):
        directory = Path(__file__).resolve().parents[1] / "artifacts/friend-300-f6aa509-20261028"
        paths = [directory / f"analysis-frame-{i}.png" for i in range(2)]
        preflight = directory / "preflight-room.png"
        if not preflight.exists() or not all(path.exists() for path in paths):
            self.skipTest("native preflight particle sequence unavailable")
        page = Mock()
        page.screenshot.side_effect = [path.read_bytes() for path in paths]
        self.assertEqual(await_reviewed_friend_room(page, preflight.read_bytes(), attempts=2), 2)
        page.mouse.click.assert_not_called()

    def test_native_settings_particle_and_capture_evidence(self):
        directory = Path(__file__).resolve().parents[1] / "artifacts/friend-300-bd8724f-20261028"
        paths = [directory / f"analysis-frame-{i}.png" for i in (2, 3)]
        preflight = directory / "preflight-room.png"
        if not preflight.exists() or not all(path.exists() for path in paths):
            self.skipTest("native settings-particle sequence unavailable")
        page, recorder = Mock(), Mock()
        frames = [path.read_bytes() for path in paths]
        page.screenshot.side_effect = frames
        self.assertEqual(await_reviewed_friend_room(page, preflight.read_bytes(), attempts=2,
                                                    on_capture=recorder), 2)
        self.assertEqual(recorder.call_args_list[0].args, (1, frames[0], True))
        self.assertEqual(recorder.call_args_list[1].args, (2, frames[1], True))

    def test_failed_capture_is_recorded_without_click(self):
        page, recorder = Mock(), Mock()
        page.screenshot.return_value = b"not an image"
        with self.assertRaises(RuntimeError):
            await_reviewed_friend_room(page, b"reference", attempts=2, on_capture=recorder)
        self.assertEqual(recorder.call_count, 2)
        self.assertTrue(all(not call.args[2] for call in recorder.call_args_list))
        page.mouse.click.assert_not_called()


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

    def test_small_changes_to_id_and_settings_remain_rejected(self):
        for box in ((975, 77, 988, 100), (1065, 77, 1080, 100),
                    (1700, 267, 1714, 285), (1730, 355, 1744, 375),
                    (310, 700, 325, 720)):
            with self.subTest(box=box):
                self.assertFalse(verified_friend_room(self.changed(box), self.frame))

    def test_faint_settings_difference_cannot_change_glyph_bitmap(self):
        directory = Path(__file__).resolve().parents[1] / "artifacts/friend-300-bd8724f-20261028"
        original = directory / "preflight-room.png"
        if not original.exists():
            self.skipTest("native preflight unavailable")
        frame = original.read_bytes()
        image = Image.open(io.BytesIO(frame)).convert("RGB")
        # Four changed pixels are small enough that a whole-panel average
        # would hide them; place them in a settings-tile glyph mask.
        for x in range(1706, 1710):
            image.putpixel((x, 720), (255, 255, 255))
        out = io.BytesIO()
        image.save(out, format="PNG")
        self.assertFalse(verified_friend_room(out.getvalue(), frame))

    def test_long_clock_does_not_match_short_clock(self):
        root = Path(__file__).resolve().parents[1] / "artifacts"
        long_room = root / "friend-300-669cd6e-20261028/preflight-room.png"
        short_room = root / "friend-5plus20-e16c0dd-20261028/preflight-room.png"
        if not long_room.exists() or not short_room.exists():
            self.skipTest("native room clock frames unavailable")
        self.assertTrue(reviewed_friend_clock_is_300_plus_zero(long_room.read_bytes()))
        self.assertFalse(reviewed_friend_clock_is_300_plus_zero(short_room.read_bytes()))
