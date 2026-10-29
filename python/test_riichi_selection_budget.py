"""A confirmed riichi selection keeps its original turn's bounded budget."""
import argparse
import io
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from auto_operator import PythonAutoOperator, RetryableSafetyAbort, SelectionStateUncertainAbort
from auto_operator import crop_screenshot, load_json
from auto_operator import mean_pixel_delta, river_structure_delta


class RiichiSelectionBudgetTest(unittest.TestCase):
    def make(self, *, deadline=300000, action_age_before_selection=3.0):
        root = Path(__file__).resolve().parents[1]
        op = PythonAutoOperator.__new__(PythonAutoOperator)
        op.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
            stability_pixel_delta=1.5, river_pixel_delta=1.0,
            force_auto_click_budget_ms=2600, ranked_loop=True, action_deadline_ms=deadline)
        op.layout = load_json(root / "config/layout-300-regression.json")
        op.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        op.river_clip = op.layout["publicTileRegions"]["ownDiscards"]
        before = (root / "test/fixtures/riichi-before-selection-20261020.jpg").read_bytes()
        selection = (root / "test/fixtures/riichi-two-candidates-selection-20261020.jpg").read_bytes()
        op.screencast_session = Mock()
        op.latest_screencast_frame = before
        op.latest_screencast_captured_at = 11.8
        op.screencast_draw_generation = 4
        op.screencast_draw_occupied = True
        op.cached_open_melds = 0
        op.action_evidence_started_at = 10.0
        op.action_budget_started_at = 10.0
        op.action_budget_draw_generation = 4
        op.action_evidence_kind = "discard"
        op.confirm_discard = Mock(return_value={"confirmation": "hand_and_own_river_changed"})
        op.refresh_discard_reconciliation_before_click = Mock(return_value=False)
        op.log = Mock()
        clock = {"now": 12.0}
        page = Mock()
        button = io.BytesIO()
        Image.new("RGB", (100, 40), "orange").save(button, format="PNG")
        page.screenshot.side_effect = lambda **kwargs: button.getvalue() if "clip" in kwargs else selection
        page.wait_for_timeout.side_effect = lambda milliseconds: clock.update(now=clock["now"] + milliseconds / 1000)

        def confirm(*_args, **_kwargs):
            clock["now"] = 10 + action_age_before_selection
            # Both a dimmed draw and invalid stream dimensions close the
            # old draw-generation grace. The certificate must be independent.
            op.screencast_draw_occupied = False
            op.screencast_draw_generation = 99
            op.latest_screencast_frame = selection
            return {"confirmation": "riichi_selection_hand_changed"}

        op.confirm_action_button = Mock(side_effect=confirm)

        def capture(_page, _purpose):
            started = clock["now"]
            clock["now"] += .55
            return argparse.Namespace(png=selection, attempt_started_at=started, completed_at=clock["now"])

        op.capture_full_action_frame = Mock(side_effect=capture)
        op.fresh_screencast_selection_receipt = Mock(return_value=selection)
        evaluation = {
            "decision": {"selectedAction": {"action": "riichi", "tile": "1m"}},
            "recognition": {"tiles": ["1m", "3m", "0m", "6m", "7m", "3p", "4p", "1s", "1s", "1s", "5s", "6s", "7s", "2p"], "safe": False},
            "clickIndex": 0, "clickPoint": {"x": 269, "y": 999},
            "actionButton": {"action": "riichi", "x": 1087, "y": 788, "width": 352,
                             "height": 57, "center": {"x": 1263, "y": 816.5}},
        }
        return op, page, evaluation, before, selection, clock

    def execute(self, op, page, evaluation, before, clock, *, after_target=None):
        def stable(*_args):
            if after_target is not None and op.capture_full_action_frame.call_count == 2:
                after_target()
            return 0.0
        with patch("auto_operator.time.monotonic", side_effect=lambda: clock["now"]), \
             patch("auto_operator.stable_hand_delta", side_effect=stable), \
             patch("auto_operator.classify_screen", return_value=("match", 1)), \
             patch("auto_operator.is_away_resume_dialog", return_value=False), \
             patch("auto_operator.discard_point_in_hand_geometry", return_value=True), \
             patch("auto_operator.raised_tile_confirmation_point", return_value={"x":269,"y":971,"lift":28}):
            return op.execute(page, evaluation, crop_screenshot(before, op.hand_clip), before, 4, 10.2)

    def test_short_riichi_finishes_without_resetting_any_original_clock(self):
        op, page, evaluation, before, _, clock = self.make(action_age_before_selection=4.3)
        result = self.execute(op, page, evaluation, before, clock)
        self.assertTrue(result["clicked"])
        self.assertGreater(clock["now"] - 10, 5)
        self.assertEqual(op.action_evidence_started_at, 10)
        self.assertEqual(op.action_budget_started_at, 10)
        self.assertEqual(op.args.force_auto_click_budget_ms, 2600)
        self.assertFalse(any("certificate" in key or "riichi_selection_budget" in key for key in vars(op)))
        log = next(item for item in op.log.call_args_list if item.args[0] == "riichi_selection_budget_grace_applied")
        self.assertIsNone(log.kwargs["remainingGameExtraTimeMs"])
        self.assertLess(log.kwargs["captureAgeBeforeDecisionMs"], 2600)

    def test_ten_second_ceiling_and_original_action_deadline_still_reject(self):
        for deadline, selection_age, pattern in ((300000, 9.0, "click budget expired"),
                                                  (5000, 4.3, "action deadline expired")):
            with self.subTest(deadline=deadline):
                op, page, evaluation, before, _, clock = self.make(deadline=deadline,
                    action_age_before_selection=selection_age)
                with self.assertRaisesRegex(RetryableSafetyAbort, pattern):
                    self.execute(op, page, evaluation, before, clock)
                page.mouse.click.assert_called_once_with(1263, 816.5)
                self.assertEqual(op.action_evidence_started_at, 10)

    def test_freshness_and_650ms_reserve_are_independent_of_turn_grace(self):
        for frame_age in (1.951, 2.6):
            with self.subTest(frame_age=frame_age):
                op, page, evaluation, before, _, clock = self.make()
                def age_image():
                    clock["now"] = 13.67 + frame_age
                with self.assertRaises(RetryableSafetyAbort):
                    self.execute(op, page, evaluation, before, clock, after_target=age_image)
                page.mouse.click.assert_called_once_with(1263, 816.5)

    def test_exact_650ms_image_reserve_can_finish_but_action_deadline_also_needs_reserve(self):
        op, page, evaluation, before, _, clock = self.make()
        result = self.execute(op, page, evaluation, before, clock,
            after_target=lambda: clock.update(now=13.67 + 1.95))
        self.assertTrue(result["clicked"])
        op, page, evaluation, before, _, clock = self.make(deadline=5000, action_age_before_selection=3.3)
        # At the first tile input only 480ms remain of the original 5s
        # deadline, although image freshness and the 10s ceiling have room.
        with self.assertRaisesRegex(RetryableSafetyAbort, "lacks time for confirmed second click"):
            self.execute(op, page, evaluation, before, clock)
        page.mouse.click.assert_called_once_with(1263, 816.5)

    def test_unknown_or_future_original_budget_and_changed_turn_proof_reject(self):
        for change in ("future_budget", "nan_budget", "start", "budget", "kind", "uncertain", "post_call"):
            with self.subTest(change=change):
                op, page, evaluation, before, _, clock = self.make()
                if change == "future_budget":
                    op.action_budget_started_at = 1000
                elif change == "nan_budget":
                    op.action_budget_started_at = float("nan")
                def alter():
                    if change == "start":
                        op.action_evidence_started_at = 11
                    elif change == "budget":
                        op.action_budget_started_at = 11
                    elif change == "kind":
                        op.action_evidence_kind = "reaction"
                    elif change == "uncertain":
                        op.selection_uncertainty_latch = {"drawGeneration": 4}
                    elif change == "post_call":
                        op.pending_post_call_discard = True
                with self.assertRaises(RetryableSafetyAbort):
                    self.execute(op, page, evaluation, before, clock, after_target=alter)
                if change in {"future_budget", "nan_budget"}:
                    page.mouse.click.assert_not_called()
                else:
                    page.mouse.click.assert_called_once_with(1263, 816.5)

    def test_certificate_does_not_leak_into_another_execution_phase_or_turn(self):
        op, page, evaluation, before, _, clock = self.make()
        with patch.object(op, "require_force_auto_click_budget", wraps=op.require_force_auto_click_budget) as guard:
            self.assertTrue(self.execute(op, page, evaluation, before, clock)["clicked"])
        certificate = next(item.kwargs["riichi_selection"] for item in guard.call_args_list
                           if item.kwargs.get("riichi_selection") is not None)
        captured = certificate.captured_at
        with patch("auto_operator.time.monotonic", side_effect=lambda: clock["now"]):
            # Same original turn, but no explicit local certificate: the dim
            # draw cannot independently grant ordinary recognition a grace.
            with self.assertRaises(RetryableSafetyAbort):
                op.require_force_auto_click_budget(captured, phase="before_pre_click_validation")
            with self.assertRaises(RetryableSafetyAbort):
                op.require_force_auto_click_budget(captured, phase="before_action_button_click",
                                                   riichi_selection=certificate)
            with self.assertRaises(RetryableSafetyAbort):
                op.require_force_auto_click_budget(captured, phase="before_discard_click",
                    riichi_selection=certificate, include_action_evidence=False)
            op.action_evidence_started_at = op.action_budget_started_at = 11
            with self.assertRaises(RetryableSafetyAbort):
                op.require_force_auto_click_budget(captured, phase="before_discard_click",
                                                   riichi_selection=certificate)

    def test_river_codec_change_preserves_structure_but_tile_changes_do_not(self):
        root = Path(__file__).resolve().parents[1]
        frame = (root / "artifacts/live/red-ron-prompt-20260928.png").read_bytes()
        image = Image.open(io.BytesIO(frame)).convert("RGB")
        jpeg = io.BytesIO()
        image.save(jpeg, format="JPEG", quality=55)
        river = load_json(root / "config/layout-runtime.json")["publicTileRegions"]["ownDiscards"]
        native = crop_screenshot(frame, river)
        compressed = crop_screenshot(jpeg.getvalue(), river)
        self.assertGreater(mean_pixel_delta(native, compressed), 1)
        self.assertLessEqual(river_structure_delta(native, compressed), .1)
        self.assertLessEqual(river_structure_delta(compressed, native), .1)
        baseline = Image.new("RGB", (410, 225), (35, 65, 90))
        ImageDraw.Draw(baseline).rectangle((20, 20, 78, 90), fill=(235, 230, 215))
        def png(value):
            encoded = io.BytesIO()
            value.save(encoded, format="PNG")
            return encoded.getvalue()
        for change in ("append", "remove", "glyph"):
            with self.subTest(change=change):
                altered = baseline.copy()
                if change == "append":
                    ImageDraw.Draw(altered).rectangle((80, 20, 138, 90), fill=(235, 230, 215))
                elif change == "remove":
                    ImageDraw.Draw(altered).rectangle((20, 20, 78, 90), fill=(35, 65, 90))
                else:
                    ImageDraw.Draw(altered).rectangle((38, 35, 60, 75), fill=(20, 20, 20))
                self.assertGreater(river_structure_delta(png(baseline), png(altered)), .1)

    def test_saved_real_white_river_append_rejects_certificate_comparison(self):
        root = Path(__file__).resolve().parents[1]
        directory = root / "artifacts/practice-5plus20-c611120-20261030/frames"
        before = directory / "2026-10-29T18-50-33.103624+00-00.jpg"
        after = directory / "2026-10-29T18-50-41.613972+00-00.jpg"
        if not before.exists() or not after.exists():
            self.skipTest("local c611120 white append recording is unavailable")
        river = load_json(root / "config/layout-runtime.json")["publicTileRegions"]["ownDiscards"]
        self.assertGreater(river_structure_delta(crop_screenshot(before.read_bytes(), river),
            crop_screenshot(after.read_bytes(), river)), .1)

    def test_changed_river_cannot_authorize_extra_time(self):
        op, page, evaluation, before, selection, clock = self.make()
        image = Image.open(io.BytesIO(selection)).convert("RGB")
        ImageDraw.Draw(image).rectangle((750, 535, 840, 600), fill="white")
        encoded = io.BytesIO()
        image.save(encoded, format="PNG")
        original = op.capture_full_action_frame.side_effect
        def changed(*args):
            receipt = original(*args)
            receipt.png = encoded.getvalue()
            return receipt
        op.capture_full_action_frame.side_effect = changed
        with self.assertRaisesRegex(RetryableSafetyAbort, "own river changed"):
            self.execute(op, page, evaluation, before, clock)
        page.mouse.click.assert_called_once_with(1263, 816.5)

    def test_selection_ui_disappearance_before_first_or_second_tile_click_rejects(self):
        for before_second in (False, True):
            with self.subTest(before_second=before_second):
                op, page, evaluation, before, _, clock = self.make()
                values = [True, True, False] if before_second else [False]
                with patch("auto_operator.riichi_selection_is_visible", side_effect=values):
                    with self.assertRaises(SelectionStateUncertainAbort if before_second else RetryableSafetyAbort):
                        self.execute(op, page, evaluation, before, clock)
                self.assertEqual(page.mouse.click.call_count, 2 if before_second else 1)

    def test_unknown_or_nonincreasing_capture_times_cannot_authorize_extra_time(self):
        for invalid in (None, float("nan"), float("inf"), 9, 999):
            with self.subTest(invalid=invalid):
                op, page, evaluation, before, _, clock = self.make()
                original = op.capture_full_action_frame.side_effect
                def broken(*args):
                    receipt = original(*args)
                    receipt.attempt_started_at = invalid
                    return receipt
                op.capture_full_action_frame.side_effect = broken
                with self.assertRaisesRegex(RetryableSafetyAbort, "capture timestamps"):
                    self.execute(op, page, evaluation, before, clock)
                page.mouse.click.assert_called_once_with(1263, 816.5)

    def test_changed_river_or_expired_deadline_before_second_click_never_confirms(self):
        for change in ("river", "deadline"):
            with self.subTest(change=change):
                op, page, evaluation, before, selection, clock = self.make(deadline=5000 if change == "deadline" else 300000)
                def receipt(*_args):
                    if change == "deadline":
                        clock["now"] = 15.01
                        return selection
                    image = Image.open(io.BytesIO(selection)).convert("RGB")
                    ImageDraw.Draw(image).rectangle((750, 535, 840, 600), fill="white")
                    encoded = io.BytesIO()
                    image.save(encoded, format="PNG")
                    return encoded.getvalue()
                op.fresh_screencast_selection_receipt.side_effect = receipt
                with self.assertRaises(SelectionStateUncertainAbort):
                    self.execute(op, page, evaluation, before, clock)
                # Declaration and first tile selection only, no raised hitbox confirmation.
                self.assertEqual(page.mouse.click.call_count, 2)


if __name__ == "__main__":
    unittest.main()
