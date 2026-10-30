import io
import unittest
from pathlib import Path
from unittest.mock import Mock
from PIL import Image, ImageDraw
from sanma_friend_navigation import inspect_sanma_friend_start


class SanmaFriendNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = (Path(__file__).resolve().parents[1] / "test/fixtures/sanma-friend-preflight.png").read_bytes()

    def test_matching_reviewed_room_requires_two_frames_but_never_clicks(self):
        page = Mock()
        page.screenshot.return_value = self.frame
        result = inspect_sanma_friend_start(page, self.frame, action_deadline_ms=300000)
        self.assertEqual(result["actionDeadlineMs"], 300000)
        self.assertEqual(result["clock"], "300+0")
        self.assertEqual([c["matched"] for c in result["captures"]], [True, True])
        self.assertFalse(result["operationAuthorized"])
        page.mouse.click.assert_not_called()

    def test_bad_or_missing_deadline_is_rejected_before_browser_read(self):
        for deadline in [None, True, 8000, 2600, "300000"]:
            page = Mock()
            with self.subTest(deadline=deadline), self.assertRaises(ValueError):
                inspect_sanma_friend_start(page, self.frame, action_deadline_ms=deadline)
            page.screenshot.assert_not_called()
        with self.assertRaises(TypeError):
            inspect_sanma_friend_start(Mock(), self.frame)

    def test_changed_room_or_short_clock_is_rejected_without_click(self):
        page = Mock()
        image = Image.open(io.BytesIO(self.frame)).convert("RGB")
        ImageDraw.Draw(image).rectangle((1700, 267, 1714, 285), fill="black")
        changed = io.BytesIO()
        image.save(changed, format="PNG")
        page.screenshot.return_value = changed.getvalue()
        with self.assertRaises(RuntimeError):
            inspect_sanma_friend_start(page, self.frame, action_deadline_ms=300000, attempts=2)
        with self.assertRaises(ValueError):
            inspect_sanma_friend_start(page, changed.getvalue(), action_deadline_ms=300000)
        page.mouse.click.assert_not_called()

    def test_one_good_capture_is_not_enough(self):
        page = Mock()
        page.screenshot.side_effect = [self.frame, b"invalid"]
        with self.assertRaises(RuntimeError):
            inspect_sanma_friend_start(page, self.frame, action_deadline_ms=300000, attempts=2)
        page.mouse.click.assert_not_called()


class SanmaFriendOperatorIntegrationTests(unittest.TestCase):
    def operator(self, preflight, deadline):
        import argparse
        from auto_operator import PythonAutoOperator
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", ranked_loop=False, rules="sanma",
                                           start_reviewed_friend_room=str(preflight), action_deadline_ms=deadline)
        operator.ensure_viewport = Mock()
        operator.log = Mock()
        operator.frames = preflight.parent
        return operator

    def test_direct_operator_inspects_same_room_and_never_clicks(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            preflight = Path(directory) / "preflight.png"
            frame = (Path(__file__).resolve().parents[1] / "test/fixtures/sanma-friend-preflight.png").read_bytes()
            preflight.write_bytes(frame)
            page = Mock()
            page.screenshot.return_value = frame
            operator = self.operator(preflight, 300000)
            with self.assertRaisesRegex(RuntimeError, "sanma automatic decisions"):
                operator.run(page)
            page.mouse.click.assert_not_called()
            calls = [call for call in operator.log.call_args_list if call.args[0] == "sanma_friend_start_inspection"]
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0].kwargs["actionDeadlineMs"], 300000)
            self.assertEqual(calls[0].kwargs["clock"], "300+0")
            self.assertFalse(calls[0].kwargs["operationAuthorized"])

    def test_direct_operator_rejects_bad_deadline_or_different_room_before_click(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            preflight = Path(directory) / "preflight.png"
            frame = (Path(__file__).resolve().parents[1] / "test/fixtures/sanma-friend-preflight.png").read_bytes()
            preflight.write_bytes(frame)
            page = Mock()
            bad_deadline_operator = self.operator(preflight, 5000)
            with self.assertRaises(ValueError):
                bad_deadline_operator.run(page)
            page.screenshot.assert_not_called()
            page.mouse.click.assert_not_called()
            failure = [c for c in bad_deadline_operator.log.call_args_list if c.args[0] == "sanma_friend_start_inspection_failed"]
            self.assertEqual(len(failure), 1)
            self.assertEqual(failure[0].kwargs["actionDeadlineMs"], 5000)
            self.assertFalse(failure[0].kwargs["operationAuthorized"])
            page.screenshot.return_value = b"invalid"
            changed_room_operator = self.operator(preflight, 300000)
            with self.assertRaises(RuntimeError):
                changed_room_operator.run(page)
            failure = [c for c in changed_room_operator.log.call_args_list if c.args[0] == "sanma_friend_start_inspection_failed"]
            self.assertEqual(len(failure), 1)
            self.assertEqual(failure[0].kwargs["actionDeadlineMs"], 300000)
            self.assertEqual(len(failure[0].kwargs["preflightSha256"]), 64)
            self.assertFalse(failure[0].kwargs["operationAuthorized"])
            page.mouse.click.assert_not_called()
