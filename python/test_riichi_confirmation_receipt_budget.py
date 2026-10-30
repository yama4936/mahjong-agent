"""Only the exact raised receipt can renew second-click image freshness.

Native ROIs retain the no-hint 9m hand, full own river, HUD and return control.
Filled pixels are not game evidence. The calibrated match reference is the
separate native pre-selection receipt reconstructed by the same ROI method.
Live metadata was discarded by the old code: event times below are modeled.
"""
import argparse
import base64
import hashlib
import io
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from auto_operator import PythonAutoOperator, RetryableSafetyAbort, SelectionStateUncertainAbort
from auto_operator import _RiichiSelectionBudget, _SelectionStreamReceipt
from auto_operator import crop_screenshot, load_json, raised_tile_confirmation_point, send_discard_click
import test_riichi_selection_budget as selection_budget_tests


ROOT = Path(__file__).resolve().parents[1]


def native_frames():
    fixture = load_json(ROOT / "test/fixtures/riichi-9m-raised-receipt-20261030.json")
    frames = {}
    for part in fixture["parts"]:
        image = Image.new("RGB", tuple(fixture["size"]), (22, 45, 65))
        for region in part["regions"]:
            png = base64.b64decode(region["pngBase64"], validate=True)
            assert hashlib.sha256(png).hexdigest() == region["sha256"]
            with Image.open(io.BytesIO(png)) as pixels:
                box = region["box"]
                assert pixels.size == (box[2] - box[0], box[3] - box[1])
                image.paste(pixels, tuple(box[:2]))
        output = io.BytesIO()
        image.save(output, format="PNG")
        frames[part["name"]] = output.getvalue()
    return frames


class RiichiConfirmationReceiptBudgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = native_frames()

    def setUp(self):
        self.clock = {"now": 106.783}
        self.time = patch("auto_operator.time.monotonic", side_effect=lambda: self.clock["now"])
        self.time.start()
        self.addCleanup(self.time.stop)
        self.op = PythonAutoOperator.__new__(PythonAutoOperator)
        self.op.args = argparse.Namespace(mode="force-auto", force_auto_click_budget_ms=2600,
                                         action_deadline_ms=300000, ranked_loop=True)
        self.op.action_evidence_started_at = 100.0
        self.op.action_budget_started_at = 100.0
        self.op.action_evidence_kind = "discard"
        self.op.screencast_draw_occupied = False
        self.op.layout = load_json(ROOT / "config/layout-300-regression.json")
        self.op.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        self.op.river_clip = self.op.layout["publicTileRegions"]["ownDiscards"]
        self.op.screen_references = {"native-selection": ("match", Image.open(io.BytesIO(self.native["before"])))}
        self.op.log = Mock()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.op.frames = Path(temporary.name)
        self.base = _RiichiSelectionBudget(100, 100, 104,
            crop_screenshot(self.native["before"], self.op.river_clip), 300000, 2600)
        self.receipt = _SelectionStreamReceipt(self.native["raised"], 106.4, 11)

    def certify(self, receipt=None, base=None, **kwargs):
        return self.op.certify_riichi_confirmation_budget(
            self.base if base is None else base, self.receipt if receipt is None else receipt,
            raised_frame=kwargs.pop("raised_frame", self.native["raised"]),
            first_click_at=kwargs.pop("first_click_at", 105.3),
            sequence_before=kwargs.pop("sequence_before", 10), **kwargs)

    def test_native_no_hint_raised_receipt_refreshes_only_second_click_image(self):
        point = raised_tile_confirmation_point(self.native["before"], self.native["raised"],
            self.op.layout, 7, {"x": 933, "y": 996.5}, 1.5)
        self.assertEqual({key: point[key] for key in ("x", "y", "lift")},
                         {"x": 933, "y": 948.5, "lift": 48})
        with self.assertRaises(RetryableSafetyAbort):
            self.op.require_force_auto_click_budget(104, phase="before_discard_confirmation_click",
                                                    riichi_selection=self.base)
        cert = self.certify()
        self.assertIs(cert.receipt.frame, self.native["raised"])
        self.assertEqual((cert.action_started_at, cert.budget_started_at, cert.captured_at),
                         (100, 100, 106.4))
        self.assertEqual((self.op.action_evidence_started_at, self.op.action_budget_started_at), (100, 100))
        self.assertFalse(any(isinstance(value, type(cert)) for value in vars(self.op).values()))
        path = next(self.op.frames.glob("*.riichi-confirmation-receipt.png"))
        self.assertEqual(path.read_bytes(), self.native["raised"])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FrozenInstanceError):
            cert.receipt.captured_at = self.clock["now"]

    def test_real_send_uses_native_unique_raised_hitbox_and_same_receipt(self):
        mouse = Mock()
        self.clock["now"] = 105.3
        result = send_discard_click(mouse, {"x": 933, "y": 996.5}, self.op.layout["viewport"],
            lambda _: self.clock.update(now=106.783), self.native["before"],
            lambda _: self.receipt.frame, self.op.layout, 7, 1.5,
            lambda: self.certify(first_click_at=105.3), self.op.record_unverified_selection)
        self.assertEqual(result["y"], 948.5)
        self.assertEqual(mouse.click.call_args_list[-1].args, (933, 948.5))

    def test_certificate_rejects_first_phase_other_phase_and_missing_evidence(self):
        cert = self.certify()
        for phase in ("before_discard_click", "before_recognition", "before_action_button_click"):
            with self.subTest(phase=phase), self.assertRaises(RetryableSafetyAbort):
                self.op.require_force_auto_click_budget(cert.captured_at, phase=phase, riichi_selection=cert)
        with self.assertRaises(RetryableSafetyAbort):
            self.op.require_force_auto_click_budget(cert.captured_at, phase="before_discard_confirmation_click",
                                                    riichi_selection=cert, include_action_evidence=False)

    def test_exact_pixels_cannot_be_relabelled_from_another_receipt(self):
        copied = bytes(bytearray(self.native["raised"]))
        self.assertIsNot(copied, self.receipt.frame)
        with self.assertRaisesRegex(RetryableSafetyAbort, "coupled"):
            self.certify(raised_frame=copied)
        with self.assertRaisesRegex(RetryableSafetyAbort, "coupled"):
            self.certify(receipt=argparse.Namespace(frame=self.native["raised"], captured_at=106.4, sequence=11))

    def test_unknown_future_nan_and_reversed_receipt_metadata_reject(self):
        for stamp in (None, True, float("nan"), float("inf"), -1, 105.2, 106.9):
            with self.subTest(stamp=stamp), self.assertRaises(RetryableSafetyAbort):
                self.certify(receipt=replace(self.receipt, captured_at=stamp))
        for sequence in (None, True, 10.5, -1, 9, 10):
            with self.subTest(sequence=sequence), self.assertRaises(RetryableSafetyAbort):
                self.certify(receipt=replace(self.receipt, sequence=sequence))
        for first in (None, True, float("nan"), 103.9, 106.5):
            with self.subTest(first=first), self.assertRaises(RetryableSafetyAbort):
                self.certify(first_click_at=first)
        for before in (None, True, -1, 11):
            with self.subTest(before=before), self.assertRaises(RetryableSafetyAbort):
                self.certify(sequence_before=before)

    def test_original_clock_configuration_and_other_turn_binding_reject(self):
        for field, value in (("action_started_at", None), ("action_started_at", -1),
                             ("budget_started_at", float("nan")), ("budget_started_at", 104.1),
                             ("captured_at", None), ("captured_at", 106),
                             ("deadline_ms", None), ("deadline_ms", True), ("click_budget_ms", None)):
            with self.subTest(field=field, value=value), self.assertRaises(RetryableSafetyAbort):
                self.certify(base=replace(self.base, **{field: value}))
        for field, value in (("action_evidence_started_at", 101), ("action_budget_started_at", 101),
                             ("action_evidence_kind", "reaction"), ("selection_uncertainty_latch", {"x": 1}),
                             ("pending_post_call_discard", True)):
            old = getattr(self.op, field, None)
            setattr(self.op, field, value)
            with self.subTest(field=field), self.assertRaises(RetryableSafetyAbort):
                self.certify()
            setattr(self.op, field, old)
        for field, value in (("action_deadline_ms", 300001), ("force_auto_click_budget_ms", 2601)):
            old = getattr(self.op.args, field)
            setattr(self.op.args, field, value)
            with self.subTest(field=field), self.assertRaises(RetryableSafetyAbort):
                self.certify()
            setattr(self.op.args, field, old)

    def test_original_ten_second_ceiling_global_deadline_and_650_reserve(self):
        for now, stamp, deadline in ((110, 109.9, 300000), (109.351, 109.3, 300000),
                                      (106.783, 106.4, 7000), (106.783, 104.8, 300000)):
            self.clock["now"] = now
            self.op.args.action_deadline_ms = deadline
            with self.subTest(now=now, stamp=stamp, deadline=deadline), self.assertRaises(RetryableSafetyAbort):
                self.certify(base=replace(self.base, deadline_ms=deadline),
                             receipt=replace(self.receipt, captured_at=stamp), first_click_at=104.5)
        self.clock["now"] = 106.783
        self.op.args.action_deadline_ms = 300000
        # Exactly 650ms image reserve remains admissible; the next millisecond does not.
        self.certify(receipt=replace(self.receipt, captured_at=104.833), first_click_at=104.5)
        with self.assertRaises(RetryableSafetyAbort):
            self.certify(receipt=replace(self.receipt, captured_at=104.832), first_click_at=104.5)

    def test_validation_time_is_charged_to_receipt_without_renewing_clocks(self):
        real = self.op.require_riichi_confirmation_receipt
        def slow(*args):
            real(*args)
            self.clock["now"] += 1.7
        with patch.object(self.op, "require_riichi_confirmation_receipt", side_effect=slow), \
                self.assertRaises(RetryableSafetyAbort):
            self.certify()
        self.assertEqual(self.op.action_budget_started_at, 100)

    def test_real_river_append_popup_missing_ui_and_non_match_still_reject(self):
        append = replace(self.receipt, frame=self.native["confirmed"])
        # The confirmed image contains only the actual appended river, not a
        # fake positive screen; isolate its native river guard in this negative.
        with patch("auto_operator.classify_screen", return_value=("match", 1)), \
                patch("auto_operator.riichi_selection_is_visible", return_value=True), \
                self.assertRaisesRegex(RetryableSafetyAbort, "river_changed"):
            self.certify(receipt=append, raised_frame=append.frame)
        for state, visible, reason in (("match_result", True, "non_match"),
                                        ("match", False, "selection_ui_missing")):
            with self.subTest(reason=reason), patch("auto_operator.classify_screen", return_value=(state, 1)), \
                    patch("auto_operator.riichi_selection_is_visible", return_value=visible), \
                    self.assertRaisesRegex(RetryableSafetyAbort, reason):
                self.certify()
        # Existing real waits-preview crop remains forbidden, never masked.
        popup = load_json(ROOT / "test/fixtures/riichi-north-waits-river-20261030.json")
        parts = {part["name"]: base64.b64decode(part["pngBase64"]) for part in popup["parts"]}
        self.op.river_clip = {"x": 0, "y": 0, "width": 410, "height": 225}
        base = replace(self.base, own_river=parts["baseline"])
        receipt = replace(self.receipt, frame=parts["popup"])
        with patch("auto_operator.classify_screen", return_value=("match", 1)), \
                patch("auto_operator.riichi_selection_is_visible", return_value=True), \
                self.assertRaisesRegex(RetryableSafetyAbort, "river_changed"):
            self.certify(base=base, receipt=receipt, raised_frame=receipt.frame)

    def test_publisher_freezes_one_coupled_receipt_and_invalid_capture_clears_it(self):
        self.op.screencast_sequence = 10
        self.op.screencast_draw_generation = 2
        self.op.cached_open_melds = 0
        self.op.rejected_screencast_size = None
        self.clock["now"] = 106.4
        self.assertTrue(self.op.accept_screencast_frame(self.native["raised"]))
        self.clock["now"] = 106.783
        receipt = self.op.frozen_selection_stream_receipt(10, 105.3)
        self.assertIs(receipt.frame, self.native["raised"])
        self.assertEqual((receipt.captured_at, receipt.sequence), (106.4, 11))
        # A subsequent publication or mutable convenience fields cannot relabel
        # the locally held raised pixels with the later timestamp/sequence.
        self.op.latest_screencast_captured_at = 106.7
        self.op.latest_screencast_frame = self.native["before"]
        self.op.screencast_sequence = 500
        self.assertIs(self.op.frozen_selection_stream_receipt(10, 105.3), receipt)
        self.assertTrue(self.op.accept_screencast_frame(self.native["before"]))
        self.assertIsNot(self.op.frozen_selection_stream_receipt(10, 105.3), receipt)
        self.assertEqual(receipt.captured_at, 106.4)
        self.assertFalse(self.op.accept_screencast_frame(b"invalid png"))
        self.assertIsNone(self.op.latest_selection_stream_receipt)

    def test_frozen_getter_refuses_missing_invalid_or_pre_click_metadata(self):
        for receipt in (None, replace(self.receipt, captured_at=None),
                        replace(self.receipt, captured_at=float("nan")),
                        replace(self.receipt, captured_at=107), replace(self.receipt, captured_at=105.2),
                        replace(self.receipt, sequence=True), replace(self.receipt, sequence=10)):
            self.op.latest_selection_stream_receipt = receipt
            with self.subTest(receipt=receipt and (receipt.captured_at, receipt.sequence)):
                self.assertIsNone(self.op.frozen_selection_stream_receipt(10, 105.3))
        self.op.latest_selection_stream_receipt = self.receipt
        for first in (None, True, float("nan"), -1, 106.5):
            self.assertIsNone(self.op.frozen_selection_stream_receipt(10, first))
        for before in (None, True, -1, 11):
            self.assertIsNone(self.op.frozen_selection_stream_receipt(before, 105.3))

    def test_execute_wiring_uses_only_local_frozen_receipt_after_raised_proof(self):
        helper = selection_budget_tests.RiichiSelectionBudgetTest()
        op, page, evaluation, before, selection, clock = helper.make()
        op.latest_selection_stream_receipt = None
        op.screencast_sequence = 10
        op.fresh_screencast_selection_receipt = Mock(side_effect=AssertionError("bytes-only path"))
        old_wait = page.wait_for_timeout.side_effect
        def wait(milliseconds):
            old_wait(milliseconds)
            # Only the post-first-tile-click event costs an extra 2.1s.
            if page.mouse.click.call_count == 2:
                clock["now"] += 2.1
                op.latest_selection_stream_receipt = _SelectionStreamReceipt(selection, clock["now"] - .02, 11)
        page.wait_for_timeout.side_effect = wait
        original_certify = op.certify_riichi_confirmation_budget
        def publish_later_during_validation(*args, **kwargs):
            # Another publication arrives after the raised proof. It must not
            # supply either pixels or a newer clock to this pending click.
            op.latest_selection_stream_receipt = _SelectionStreamReceipt(before, clock["now"], 12)
            op.latest_screencast_captured_at = clock["now"]
            op.latest_screencast_frame = before
            return original_certify(*args, **kwargs)
        with patch.object(op, "certify_riichi_confirmation_budget", side_effect=publish_later_during_validation) as certify:
            result = helper.execute(op, page, evaluation, before, clock)
        self.assertTrue(result["clicked"])
        self.assertEqual(page.mouse.click.call_count, 3)
        call = certify.call_args
        self.assertIs(call.args[1].frame, call.kwargs["raised_frame"])
        self.assertEqual(call.kwargs["sequence_before"], 10)
        self.assertIsNot(call.args[1], op.latest_selection_stream_receipt)
        self.assertEqual(call.args[1].sequence, 11)
        self.assertEqual(op.action_evidence_started_at, 10)
        self.assertEqual(op.action_budget_started_at, 10)
        self.assertGreater(clock["now"] - call.args[0].captured_at, 2.6)
        self.assertFalse(any(key == "riichi_confirmation_budget" for key in vars(op)))

    def test_execute_cannot_fall_back_to_old_bytes_when_coupled_metadata_missing(self):
        helper = selection_budget_tests.RiichiSelectionBudgetTest()
        op, page, evaluation, before, selection, clock = helper.make()
        op.latest_selection_stream_receipt = None
        op.screencast_sequence = 10
        op.fresh_screencast_selection_receipt = Mock(return_value=selection)
        op.record_unverified_selection = Mock()
        with self.assertRaises(SelectionStateUncertainAbort):
            helper.execute(op, page, evaluation, before, clock)
        self.assertEqual(page.mouse.click.call_count, 2)  # declaration + selection, never confirmation
        op.fresh_screencast_selection_receipt.assert_not_called()

    def test_execute_last_guard_rejects_changed_turn_or_expired_global_after_proof(self):
        for reason in ("turn", "global", "image"):
            with self.subTest(reason=reason):
                helper = selection_budget_tests.RiichiSelectionBudgetTest()
                op, page, evaluation, before, selection, clock = helper.make()
                op.latest_selection_stream_receipt = None
                op.screencast_sequence = 10
                op.record_unverified_selection = Mock()
                old_wait = page.wait_for_timeout.side_effect
                def wait(milliseconds):
                    old_wait(milliseconds)
                    if page.mouse.click.call_count == 2:
                        op.latest_selection_stream_receipt = _SelectionStreamReceipt(selection, clock["now"], 11)
                page.wait_for_timeout.side_effect = wait
                original_certify = op.certify_riichi_confirmation_budget
                def delay_after_certification(*args, **kwargs):
                    certificate = original_certify(*args, **kwargs)
                    if reason == "turn":
                        op.action_evidence_started_at += .1
                    else:
                        clock["now"] += 300 if reason == "global" else 2.6
                    return certificate
                with patch.object(op, "certify_riichi_confirmation_budget", side_effect=delay_after_certification), \
                        self.assertRaises(SelectionStateUncertainAbort):
                    helper.execute(op, page, evaluation, before, clock)
                self.assertEqual(page.mouse.click.call_count, 2)
                op.record_unverified_selection.assert_called_once()


if __name__ == "__main__":
    unittest.main()
