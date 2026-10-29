import argparse
import base64
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from auto_operator import PythonAutoOperator


def frame(hand_changed=False, river_changed=False, size=(20, 10)):
    image = Image.new("RGB", size, "black")
    if hand_changed:
        image.paste("white", (0, 0, 10, 10))
    if river_changed:
        image.paste("white", (10, 0, 20, 10))
    encoded = io.BytesIO()
    image.save(encoded, "PNG")
    return encoded.getvalue()


class DiscardConfirmationCaptureTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now = 100.0
        clock = patch("auto_operator.time.monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.operator = PythonAutoOperator.__new__(PythonAutoOperator)
        self.operator.args = argparse.Namespace(mode="force-auto", confirmation_timeout=1,
                                                action_pixel_delta=1, river_pixel_delta=1)
        self.operator.frames = Path(self.directory.name)
        self.operator.layout = {"viewport": {"width": 20, "height": 10}}
        self.operator.hand_clip = {"x": 0, "y": 0, "width": 10, "height": 10}
        self.operator.river_clip = {"x": 10, "y": 0, "width": 10, "height": 10}
        self.operator.log = Mock()
        self.operator.screencast_session = Mock()
        self.operator.verify_post_discard = Mock(side_effect=AssertionError("must not recognize again"))
        self.operator.action_evidence_started_at = 97.0
        self.operator.action_evidence_kind = "discard"
        self.page = Mock()

        def wait(milliseconds):
            self.now += milliseconds / 1000
        self.page.wait_for_timeout.side_effect = wait
        self.page.screenshot.side_effect = AssertionError("fast capture must not use page.screenshot")
        baseline = io.BytesIO()
        Image.new("RGB", (10, 10), "black").save(baseline, "PNG")
        self.baseline = baseline.getvalue()

    def supply_frames(self, frames):
        self.operator.screencast_session.send.side_effect = [
            {"data": base64.b64encode(image).decode()} for image in frames
        ]

    def confirm(self):
        return self.operator.confirm_discard(self.page, self.baseline, self.baseline, ["1m"] * 14, 0)

    def captures(self):
        return [call.kwargs for call in self.operator.log.call_args_list
                if call.args[0] == "synchronous_action_capture"]

    def assert_no_gameplay_input_or_clock_reset(self):
        self.page.mouse.click.assert_not_called()
        self.operator.verify_post_discard.assert_not_called()
        self.assertEqual(self.operator.action_evidence_started_at, 97.0)
        self.assertEqual(self.operator.action_evidence_kind, "discard")

    def test_each_poll_uses_new_sync_frame_and_both_changes_from_same_image(self):
        validated = frame(True, True)
        # This old stream already shows both changes; it must not substitute
        # for any synchronous receipt or combine different poll results.
        self.operator.latest_screencast_frame = validated
        self.supply_frames([frame(), frame(True), frame(False, True), validated])
        result = self.confirm()
        self.assertEqual(result["confirmation"], "hand_and_own_river_changed")
        self.assertEqual(Path(result["screenshot"]).read_bytes(), validated)
        self.assertEqual(self.operator.screencast_session.send.call_count, 4)
        self.assertEqual(len(self.captures()), 4)
        self.assertTrue(all(c["purpose"] == "discard_confirmation" and c["method"] == "cdp_png_fast"
                            for c in self.captures()))
        self.assertEqual(len({c["attemptStartedAt"] for c in self.captures()}), 4)
        self.assertEqual(self.page.wait_for_timeout.call_args_list[-1].args, (200,))
        self.page.screenshot.assert_not_called()
        self.operator.screencast_session.detach.assert_not_called()
        self.assert_no_gameplay_input_or_clock_reset()

    def test_separate_hand_and_river_changes_never_satisfy_and_or_retry_click(self):
        self.operator.args.confirmation_timeout = 0.35
        self.supply_frames([frame(True), frame(False, True)] * 3)
        with self.assertRaisesRegex(RuntimeError, "not confirmed by both hand and own-river"):
            self.confirm()
        self.assertEqual(list(self.operator.frames.iterdir()), [])
        self.assertEqual(self.operator.screencast_session.send.call_count, 4)
        self.page.screenshot.assert_not_called()
        self.assert_no_gameplay_input_or_clock_reset()

    def test_cdp_error_falls_back_and_saves_exact_validated_fallback(self):
        self.operator.screencast_session.send.side_effect = RuntimeError("capture protocol unavailable")
        self.page.screenshot.side_effect = None
        validated = frame(True, True)
        self.page.screenshot.return_value = validated
        result = self.confirm()
        self.assertEqual(Path(result["screenshot"]).read_bytes(), validated)
        self.page.screenshot.assert_called_once_with(animations="disabled")
        self.assertEqual(self.captures()[0]["method"], "playwright_png")
        self.assertIn("capture protocol unavailable", self.captures()[0]["fallbackReason"])
        self.assert_no_gameplay_input_or_clock_reset()

    def test_partial_cdp_frame_is_rejected_before_using_validated_fallback(self):
        self.supply_frames([frame(True, True, size=(21, 10))])
        self.page.screenshot.side_effect = None
        validated = frame(True, True)
        self.page.screenshot.return_value = validated
        result = self.confirm()
        self.assertEqual(Path(result["screenshot"]).read_bytes(), validated)
        self.assertIn("does not match expected", self.captures()[0]["fallbackReason"])
        self.assert_no_gameplay_input_or_clock_reset()

    def test_capture_failure_propagates_without_saved_receipt_or_extra_click(self):
        self.operator.screencast_session.send.side_effect = RuntimeError("CDP capture failed")
        self.page.screenshot.side_effect = RuntimeError("fallback capture failed")
        with self.assertRaisesRegex(RuntimeError, "fallback capture failed"):
            self.confirm()
        self.assertEqual(list(self.operator.frames.iterdir()), [])
        self.assertEqual(self.captures(), [])
        self.page.screenshot.assert_called_once_with(animations="disabled")
        self.assert_no_gameplay_input_or_clock_reset()

    def test_invalid_fallback_size_never_confirms_or_saves_partial_frame(self):
        self.operator.screencast_session.send.side_effect = RuntimeError("CDP capture failed")
        self.page.screenshot.side_effect = None
        self.page.screenshot.return_value = frame(True, True, size=(21, 10))
        with self.assertRaisesRegex(ValueError, "does not match expected"):
            self.confirm()
        self.assertEqual(list(self.operator.frames.iterdir()), [])
        self.assertEqual(self.captures(), [])
        self.assert_no_gameplay_input_or_clock_reset()


if __name__ == "__main__":
    unittest.main()
