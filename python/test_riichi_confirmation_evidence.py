"""A failed second-click guard must preserve its exact image and reason.

The native river crops reproduce a same-match waits-preview rejection. They
are not the missing 21:35:49 abort receipt and do not authorize popup masking.
"""
import argparse
import base64
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from auto_operator import PythonAutoOperator, RetryableSafetyAbort, SelectionStateUncertainAbort
from auto_operator import _RiichiSelectionBudget, load_json, river_structure_delta, send_discard_click


ROOT = Path(__file__).resolve().parents[1]


class RiichiConfirmationEvidenceTest(unittest.TestCase):
    def setUp(self):
        fixture = load_json(ROOT / "test/fixtures/riichi-north-waits-river-20261030.json")
        self.frames = {}
        for part in fixture["parts"]:
            png = base64.b64decode(part["pngBase64"], validate=True)
            self.assertEqual(hashlib.sha256(png).hexdigest(), part["sha256"])
            with Image.open(io.BytesIO(png)) as image:
                self.assertEqual(image.size, tuple(fixture["size"]))
            self.frames[part["name"]] = png
        self.before = self.frames["baseline"]
        self.popup = self.frames["popup"]
        self.certificate = _RiichiSelectionBudget(10, 10, 14, self.before)
        self.operator = PythonAutoOperator.__new__(PythonAutoOperator)
        self.operator.log = Mock()
        self.operator.screen_references = {}
        self.operator.hand_clip = {"x": 0, "y": 0, "width": 410, "height": 225}
        self.operator.river_clip = dict(self.operator.hand_clip)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.operator.frames = Path(temporary.name)
        self.mouse = Mock()

    def guard(self, receipt):
        # These sanitized crops retain only the native river evidence. Match
        # and hand-UI checks are independently selected by each guard test.
        return self.operator.require_riichi_confirmation_receipt(self.certificate, receipt)

    def send(self, callback, recorder=None, receipt=None):
        with patch("auto_operator.raised_tile_confirmation_point", return_value={
                "x": 1122.5, "y": 948.5, "lift": 48}):
            return send_discard_click(
                self.mouse, {"x": 1122.5, "y": 996.5}, {"width": 1920, "height": 1080},
                Mock(), self.before, lambda _: self.popup if receipt is None else receipt,
                {}, 9, 1.5, callback, recorder,
            )

    def test_four_guard_failures_log_distinct_reasons_and_available_measurements(self):
        for reason, receipt, state, visible, delta in (
            ("receipt_missing", None, "match", True, 0),
            ("non_match", self.before, "round_result", True, 0),
            ("selection_ui_missing", self.before, "match", False, 0),
            ("river_changed", self.popup, "match", True, 8.518157181571816),
        ):
            with self.subTest(reason=reason), \
                    patch("auto_operator.classify_screen", return_value=(state, .99)), \
                    patch("auto_operator.riichi_selection_is_visible", return_value=visible), \
                    patch("auto_operator.river_structure_delta", return_value=delta), \
                    self.assertRaisesRegex(RetryableSafetyAbort, reason):
                self.guard(receipt)
            event = self.operator.log.call_args
            self.assertEqual(event.args[0], "riichi_discard_confirmation_rejected")
            self.assertEqual(event.kwargs["reason"], reason)
            self.assertEqual(event.kwargs["riverStructureLimitPercent"], .1)
            if reason == "river_changed":
                self.assertEqual(event.kwargs["riverStructureDeltaPercent"], delta)
                self.assertTrue(event.kwargs["riverStructureDeltaFinite"])

    def test_native_waits_popup_is_reproduced_but_not_silently_exempted(self):
        self.assertAlmostEqual(river_structure_delta(self.before, self.popup), 8.518157181571816)
        with patch("auto_operator.classify_screen", return_value=("match", 1)), \
                patch("auto_operator.riichi_selection_is_visible", return_value=True), \
                self.assertRaisesRegex(SelectionStateUncertainAbort, "river_changed"):
            self.send(lambda: self.guard(self.popup), self.operator.record_unverified_selection)
        self.mouse.click.assert_called_once_with(1122.5, 996.5)
        paths = self.operator.log.call_args.kwargs
        self.assertEqual(Path(paths["baseline"]).read_bytes(), self.before)
        self.assertEqual(Path(paths["receipt"]).read_bytes(), self.popup)
        self.assertEqual(Path(paths["baseline"]).stat().st_mode & 0o777, 0o600)
        self.assertEqual(Path(paths["receipt"]).stat().st_mode & 0o777, 0o600)

    def test_all_four_callback_rejections_save_exact_receipt_once_and_never_confirm(self):
        for reason in ("receipt_missing", "non_match", "selection_ui_missing", "river_changed"):
            self.mouse.reset_mock()
            recorder = Mock()
            cause = RetryableSafetyAbort(reason)
            with self.subTest(reason=reason), self.assertRaises(SelectionStateUncertainAbort) as raised:
                self.send(Mock(side_effect=cause), recorder)
            recorder.assert_called_once_with(self.before, self.popup)
            self.mouse.click.assert_called_once_with(1122.5, 996.5)
            self.assertIs(raised.exception.__cause__, cause)

    def test_budget_and_global_deadline_rejections_also_preserve_receipt_and_cause(self):
        for message in ("force-auto click budget expired", "five-second action deadline expired"):
            self.mouse.reset_mock()
            recorder = Mock()
            cause = RetryableSafetyAbort(message)
            with self.subTest(message=message), self.assertRaises(SelectionStateUncertainAbort) as raised:
                self.send(Mock(side_effect=cause), recorder)
            recorder.assert_called_once_with(self.before, self.popup)
            self.mouse.click.assert_called_once_with(1122.5, 996.5)
            self.assertIs(raised.exception.__cause__, cause)

    def test_evidence_write_failure_does_not_replace_guard_cause_or_send_second_click(self):
        cause = RetryableSafetyAbort("river_changed")
        recorder = Mock(side_effect=OSError("disk full"))
        with self.assertRaises(SelectionStateUncertainAbort) as raised:
            self.send(Mock(side_effect=cause), recorder)
        recorder.assert_called_once_with(self.before, self.popup)
        self.mouse.click.assert_called_once_with(1122.5, 996.5)
        self.assertIs(raised.exception.__cause__, cause)

    def test_jpeg_receipt_is_preserved_without_transcoding(self):
        encoded = io.BytesIO()
        Image.open(io.BytesIO(self.popup)).save(encoded, "JPEG", quality=55)
        jpeg = encoded.getvalue()
        with self.assertRaises(SelectionStateUncertainAbort):
            self.send(Mock(side_effect=RetryableSafetyAbort("river_changed")),
                      self.operator.record_unverified_selection, jpeg)
        saved = Path(self.operator.log.call_args.kwargs["receipt"]).read_bytes()
        self.assertEqual(saved, jpeg)
        self.assertEqual(Image.open(io.BytesIO(saved)).format, "JPEG")

    def test_native_unchanged_and_same_frame_jpeg55_pass_but_real_discard_still_fails(self):
        encoded = io.BytesIO()
        Image.open(io.BytesIO(self.before)).save(encoded, "JPEG", quality=55)
        with patch("auto_operator.classify_screen", return_value=("match", 1)), \
                patch("auto_operator.riichi_selection_is_visible", return_value=True):
            self.guard(self.before)
            self.guard(encoded.getvalue())
            with self.assertRaisesRegex(RetryableSafetyAbort, "river_changed"):
                self.guard(self.frames["confirmed"])
        self.assertAlmostEqual(river_structure_delta(self.before, self.frames["confirmed"]),
                               3.827642276422764)

    def test_nonfinite_river_measurement_fails_closed_with_json_safe_evidence(self):
        with patch("auto_operator.classify_screen", return_value=("match", 1)), \
                patch("auto_operator.riichi_selection_is_visible", return_value=True), \
                patch("auto_operator.river_structure_delta", return_value=float("inf")), \
                self.assertRaisesRegex(RetryableSafetyAbort, "river_changed"):
            self.guard(self.before)
        self.assertIsNone(self.operator.log.call_args.kwargs["riverStructureDeltaPercent"])
        self.assertFalse(self.operator.log.call_args.kwargs["riverStructureDeltaFinite"])

    def test_successful_confirmation_does_not_write_unverified_evidence(self):
        recorder = Mock()
        result = self.send(Mock(), recorder)
        self.assertEqual(result["lift"], 48)
        self.assertEqual(self.mouse.click.call_count, 2)
        recorder.assert_not_called()

    def test_existing_lift_failure_still_saves_its_last_receipt(self):
        recorder = Mock()
        with patch("auto_operator.raised_tile_confirmation_point", return_value=None), \
                self.assertRaisesRegex(SelectionStateUncertainAbort, "lift or identity"):
            send_discard_click(
                self.mouse, {"x": 1122.5, "y": 996.5}, {"width": 1920, "height": 1080},
                Mock(), self.before, lambda _: self.popup, {}, 9, 1.5, Mock(), recorder,
            )
        self.mouse.click.assert_called_once_with(1122.5, 996.5)
        recorder.assert_called_once_with(self.before, self.popup)

    def test_actual_execute_callback_wires_rejection_to_exact_evidence(self):
        import test_riichi_selection_budget as fixture
        case = fixture.RiichiSelectionBudgetTest()
        op, page, evaluation, before, selection, clock = case.make()
        op.frames = self.operator.frames
        op.require_riichi_confirmation_receipt = Mock(side_effect=RetryableSafetyAbort("river_changed"))
        with self.assertRaisesRegex(SelectionStateUncertainAbort, "river_changed"):
            case.execute(op, page, evaluation, before, clock)
        op.require_riichi_confirmation_receipt.assert_called_once()
        self.assertEqual(page.mouse.click.call_count, 2)  # declaration and first tile click only
        event = next(event for event in op.log.call_args_list
                     if event.args[0] == "unverified_selection_evidence")
        self.assertEqual(Path(event.kwargs["baseline"]).read_bytes(), selection)
        self.assertEqual(Path(event.kwargs["receipt"]).read_bytes(), selection)


if __name__ == "__main__":
    unittest.main()
