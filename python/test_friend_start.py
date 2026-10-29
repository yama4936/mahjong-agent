import io
import argparse
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from friend_start import await_reviewed_friend_room, reviewed_friend_clock_is_300_plus_zero, verified_friend_room
from auto_operator import PythonAutoOperator


class ReviewedFriendOcrWarmupTests(unittest.TestCase):
    def operator(self, path, **overrides):
        op = PythonAutoOperator.__new__(PythonAutoOperator)
        values = dict(mode="force-auto", ranked_loop=False, board_metadata=True,
                      start_reviewed_friend_room=str(path))
        values.update(overrides)
        op.args = argparse.Namespace(**values)
        op.board_metadata_ocr_lock = threading.Lock()
        op.ensure_viewport = Mock()
        op.configured_action_deadline_ms = Mock(return_value=1)
        op.force_auto_click_budget_ms = Mock(return_value=2600)
        op.log = Mock()
        op.layout = {"viewport": {"width": 1920, "height": 1080}}
        op.start_screencast_gate = Mock(side_effect=RuntimeError("stop after click"))
        return op

    def test_warmup_only_reviewed_nonranked_force_auto(self):
        for overrides in ({"start_reviewed_friend_room": None}, {"ranked_loop": True},
                          {"board_metadata": False}, {"mode": "observer"}):
            with self.subTest(overrides=overrides), patch("board_metadata.ocr_engine") as engine:
                self.assertFalse(self.operator("unused", **overrides).warm_reviewed_friend_board_ocr())
                engine.assert_not_called()

    def test_warmup_rechecks_room_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviewed.png"
            path.write_bytes(b"reviewed")
            op, page = self.operator(path), Mock()
            with patch("auto_operator.await_reviewed_friend_room", side_effect=[2, RuntimeError("changed")]) as verify, \
                    patch("board_metadata.ocr_engine") as engine:
                with self.assertRaisesRegex(RuntimeError, "changed"):
                    op.run(page)
            self.assertEqual(verify.call_count, 2)
            self.assertEqual(verify.call_args_list[0].kwargs["attempts"], 32)
            self.assertEqual(verify.call_args_list[1].kwargs["attempts"], 16)
            engine.assert_called_once()
            page.mouse.click.assert_not_called()

    def test_warmup_failure_prevents_start(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviewed.png"
            path.write_bytes(b"reviewed")
            op, page = self.operator(path), Mock()
            with patch("auto_operator.await_reviewed_friend_room", return_value=2), \
                    patch("board_metadata.ocr_engine", side_effect=RuntimeError("ocr failed")):
                with self.assertRaisesRegex(RuntimeError, "ocr failed"):
                    op.run(page)
            page.mouse.click.assert_not_called()


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

    def test_extended_attempts_still_require_two_consecutive_matches(self):
        for checks, expected in (([False] * 8 + [True, True], 10),
                                 ([True, False] * 16, None),
                                 ([False] * 32, None)):
            page = Mock()
            with patch("friend_start.verified_friend_room", side_effect=checks):
                if expected is None:
                    with self.assertRaises(RuntimeError):
                        await_reviewed_friend_room(page, b"reviewed", attempts=32)
                else:
                    self.assertEqual(await_reviewed_friend_room(page, b"reviewed", attempts=32), expected)
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

    def test_native_particle_over_room_id_colon_does_not_bind_decoration(self):
        directory = Path(__file__).resolve().parents[1] / "artifacts/friend-300-6efe75c-20261028"
        frames = sorted((directory / "frames").glob("*friend-start*.png"))
        preflight = directory / "preflight-room.png"
        if not preflight.exists() or len(frames) < 2:
            self.skipTest("native colon-particle sequence unavailable")
        page = Mock()
        page.screenshot.side_effect = [path.read_bytes() for path in frames[:2]]
        self.assertEqual(await_reviewed_friend_room(page, preflight.read_bytes(), attempts=2), 2)

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

    def test_each_room_id_digit_is_still_bound(self):
        path = Path(__file__).resolve().parents[1] / "artifacts/friend-300-6efe75c-20261028/preflight-room.png"
        if not path.exists():
            self.skipTest("native ID frame unavailable")
        frame = path.read_bytes()
        for x in (970, 995, 1019, 1043, 1067):
            image = Image.open(io.BytesIO(frame)).convert("RGB")
            ImageDraw.Draw(image).rectangle((x, 74, x + 14, 105), fill="black")
            out = io.BytesIO()
            image.save(out, format="PNG")
            with self.subTest(digit_x=x):
                self.assertFalse(verified_friend_room(out.getvalue(), frame))

    def test_long_clock_does_not_match_short_clock(self):
        root = Path(__file__).resolve().parents[1] / "artifacts"
        long_room = root / "friend-300-669cd6e-20261028/preflight-room.png"
        short_room = root / "friend-5plus20-e16c0dd-20261028/preflight-room.png"
        if not long_room.exists() or not short_room.exists():
            self.skipTest("native room clock frames unavailable")
        self.assertTrue(reviewed_friend_clock_is_300_plus_zero(long_room.read_bytes()))
        self.assertFalse(reviewed_friend_clock_is_300_plus_zero(short_room.read_bytes()))
