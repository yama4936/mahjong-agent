"""An exhausted optional call must still reach independently checked skip UI."""
import argparse
import base64
import hashlib
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from auto_operator import (
    OptionalReactionBudgetExhausted, PythonAutoOperator, RetryableSafetyAbort,
    force_auto_call_buttons, force_auto_self_action_buttons,
    load_json, should_retry_call_policy,
)
from synchronous_capture import CaptureReceipt


ROOT = Path(__file__).resolve().parents[1]


class OptionalReactionBudgetPassTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.now = 103.0
        clock = patch("auto_operator.time.monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.operator = op = PythonAutoOperator.__new__(PythonAutoOperator)
        op.args = argparse.Namespace(
            mode="force-auto", max_iterations=2, poll=0, stop_on_error=True,
            accept_single_call=True, action_templates=None, board_metadata=False,
            stability_pixel_delta=1.5, action_deadline_ms=300000,
            force_auto_click_budget_ms=2600, evaluation_timeout=5,
        )
        op.layout = load_json(ROOT / "config/layout.json")
        op.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        op.action_clip = None
        op.frames = self.directory
        op.root = ROOT
        op.state_path = self.directory / "state.json"
        op.layout_path = ROOT / "config/layout.json"
        op.templates = ROOT / "templates"
        op.evaluator_env = {"JEV_FORCE_AUTO_DEADLINE_MS": "2300"}
        op.screen_references = {}
        op.screencast_session = Mock()
        op.screencast_sequence = 1
        op.screencast_draw_occupied = False
        op.screencast_draw_generation = 0
        op.rejected_screencast_size = None
        op.cached_public_observation = None
        op.previous_public_observation = None
        op.cached_concealed_tiles = None
        op.cached_open_melds = 0
        op.dynamic_layout_required = False
        op.pending_post_call_discard = False
        op.pending_post_call_started_at = None
        op.restart_open_hand_probe_hash = None
        op.open_meld_candidate = None
        op.open_meld_candidate_frames = set()
        op.last_processed_hand = None
        op.armed = True
        op.last_shanten = 1
        op.round_terminal_latched = False
        op.action_evidence_started_at = 100.0
        op.action_budget_started_at = 100.0
        op.action_evidence_last_seen_at = 102.9
        op.action_evidence_kind = "reaction"
        op.last_action_clicked_at = None
        op.login_button_clicked_at = None
        for method in ("poll_public_recognition", "ensure_viewport", "start_screencast_gate",
                       "schedule_periodic_public_recognition"):
            setattr(op, method, Mock())
        op.resume_if_away = Mock(return_value=False)
        op.advance_ranked_loop = Mock(return_value=False)
        def next_frame(_page):
            op.screencast_sequence += 1
            return False
        op.capture_self_win_result = Mock(side_effect=next_frame)
        op.execute_force_auto_call = Mock()
        op.execute_force_auto_reaction_win = Mock(return_value={"clicked": True, "action": "ron"})
        op.recognize_reaction_hand = Mock(return_value={"tiles": ["1m"] * 13, "safe": False})
        op.confirm_action_button = Mock(return_value={"confirmation": "action_button_region_changed"})
        op.log = Mock()
        self.pass_pixels = (ROOT / "test/fixtures/reaction-pass-pon7p-20261021.png").read_bytes()
        image = Image.new("RGB", (1920, 1080), (20, 40, 70))
        image.paste(Image.open(io.BytesIO(self.pass_pixels)), (1170, 775))
        encoded = io.BytesIO()
        image.save(encoded, "PNG")
        op.latest_screencast_frame = encoded.getvalue()
        op.latest_screencast_captured_at = 102.99
        self.full = op.latest_screencast_frame
        self.capture_images = []
        self.capture_cost = .1
        def capture(_page, _purpose):
            self.now += .01
            started = self.now
            self.now += self.capture_cost
            image = self.capture_images.pop(0) if self.capture_images else self.full
            return CaptureReceipt(image, started, started, self.now, 1920, 1080, "mock_sync")
        op.capture_full_action_frame = Mock(side_effect=capture)
        self.page = Mock()
        self.page.url = "https://game.mahjongsoul.com/index.html"
        self.page.screenshot.return_value = self.pass_pixels
        self.page.wait_for_timeout.side_effect = lambda ms: setattr(self, "now", self.now + ms / 1000)
        self.original_clock_at_click = []
        self.page.mouse.click.side_effect = lambda *_: self.original_clock_at_click.append((
            op.action_evidence_started_at, op.action_budget_started_at,
        ))
        self.solver = Mock()

        def exhausted_policy(screenshot, _action, *, captured_at):
            # Use the real evaluate guard, not a hand-built exception: fresh
            # receipts must not lend the expired reaction another solver run.
            return op.evaluate(screenshot, {"tile": "9p", "fromSeat": "north"},
                               {"ownDiscards": []}, {"tiles": ["1m"] * 13},
                               ["chi", "pass"], captured_at=captured_at)
        op.evaluate_force_auto_call_policy = Mock(side_effect=exhausted_policy)

    def run_frame(self, *, win=False, green_call=True):
        with patch("auto_operator.classify_screen", return_value=("match", 1)), \
                patch("auto_operator.StartupTurnGuard") as startup, \
                patch("auto_operator.force_auto_call_buttons", return_value=([{
                    "action": "chi", "center": {"x": 1000, "y": 820},
                }] if green_call else [])), \
                patch("auto_operator.force_auto_self_action_buttons", return_value=(
                    [{"action": "ron", "center": {"x": 1000, "y": 820}}] if win else [])), \
                patch("auto_operator.force_auto_reaction_win_button", return_value=(
                    {"action": "ron", "center": {"x": 1000, "y": 820}} if win else None)), \
                patch("auto_operator.subprocess.run", self.solver):
            startup.return_value.ready = True
            startup.return_value.quarantined = False
            startup.return_value.initial_action_anchor = None
            startup.return_value.observe.return_value = "ready"
            self.operator.run(self.page)

    def test_expired_call_reaches_real_fresh_two_capture_pass_without_model_or_clock_reset(self):
        self.run_frame()
        self.operator.evaluate_force_auto_call_policy.assert_called_once()
        self.solver.assert_not_called()
        self.operator.execute_force_auto_call.assert_not_called()
        self.page.screenshot.assert_not_called()
        self.assertEqual(self.operator.capture_full_action_frame.call_count, 2)
        self.page.mouse.click.assert_called_once_with(1307.5, 827.5)
        self.assertEqual(self.original_clock_at_click, [(100.0, 100.0)])
        event = next(call for call in self.operator.log.call_args_list
                     if call.args[0] == "reaction_call_policy_rejected")
        self.assertEqual(event.kwargs["reason"], "optional_call_budget_exhausted_safe_pass")

    def test_reserve_shortfall_before_expiry_also_passes_without_model(self):
        # Native 3465c5a 9p chi: elapsed2152ms =>448ms remaining.
        self.now = 102.152
        self.operator.latest_screencast_captured_at = 102.1
        self.run_frame()
        self.solver.assert_not_called()
        self.page.mouse.click.assert_called_once()
        self.assertEqual(self.original_clock_at_click, [(100.0, 100.0)])

    def test_changed_current_pass_never_clicks_or_clears_original_clock(self):
        changed = io.BytesIO()
        Image.new("RGB", (275, 105), "white").save(changed, "PNG")
        second = Image.open(io.BytesIO(self.full)).convert("RGB")
        second.paste(Image.open(io.BytesIO(changed.getvalue())), (1170, 775))
        out = io.BytesIO()
        second.save(out, "PNG")
        self.capture_images = [self.full, out.getvalue()]
        # Keep prompt semantics true so only the unchanged 1.5 pixel guard
        # determines this negative, not a missing-call/skip semantic guard.
        with patch("auto_operator.is_contextual_reaction_pass", return_value=True):
            self.run_frame()
        self.solver.assert_not_called()
        self.page.mouse.click.assert_not_called()
        self.assertEqual(self.operator.action_evidence_started_at, 100.0)
        self.assertEqual(self.operator.action_budget_started_at, 100.0)
        self.assertTrue(any(call.args[0] == "reaction_pass_deferred"
                            for call in self.operator.log.call_args_list))
        event = next(call for call in self.operator.log.call_args_list
                     if call.args[0] == "reaction_pass_stability_rejected")
        self.assertGreater(event.kwargs["buttonPixelDelta"], 1.5)
        self.assertEqual(event.kwargs["verificationSource"], "expired_optional_full_pair")
        self.assertEqual(Path(event.kwargs["beforeScreenshot"]).read_bytes(), self.pass_pixels)
        self.assertEqual(Path(event.kwargs["confirmedScreenshot"]).read_bytes(), changed.getvalue())

    def test_evidence_write_failure_still_aborts_without_click(self):
        changed = io.BytesIO()
        Image.new("RGB", (275, 105), "white").save(changed, "PNG")
        second = Image.open(io.BytesIO(self.full)).convert("RGB")
        second.paste(Image.open(io.BytesIO(changed.getvalue())), (1170, 775))
        out = io.BytesIO()
        second.save(out, "PNG")
        self.capture_images = [self.full, out.getvalue()]
        write = Path.write_bytes
        def fail_diagnostic(path, data):
            if ".pass-" in path.name:
                raise OSError("diagnostic disk full")
            return write(path, data)
        with patch.object(Path, "write_bytes", fail_diagnostic), \
                patch("auto_operator.is_contextual_reaction_pass", return_value=True):
            self.run_frame()
        self.page.mouse.click.assert_not_called()
        event = next(call for call in self.operator.log.call_args_list
                     if call.args[0] == "reaction_pass_stability_rejected")
        self.assertEqual(set(event.kwargs["evidenceSaveErrors"]), {"before", "confirmed"})
        self.assertTrue(any(call.args[0] == "reaction_pass_deferred"
                            for call in self.operator.log.call_args_list))

    def test_changed_pass_can_recover_on_next_frame_without_restarting_model_or_clock(self):
        changed = io.BytesIO()
        Image.new("RGB", (275, 105), "white").save(changed, "PNG")
        second = Image.open(io.BytesIO(self.full)).convert("RGB")
        second.paste(Image.open(io.BytesIO(changed.getvalue())), (1170, 775))
        out = io.BytesIO()
        second.save(out, "PNG")
        self.capture_images = [self.full, out.getvalue(), self.full, self.full]
        self.operator.args.max_iterations = 3
        with patch("auto_operator.is_contextual_reaction_pass", return_value=True):
            self.run_frame()
        self.assertEqual(self.operator.evaluate_force_auto_call_policy.call_count, 2)
        self.solver.assert_not_called()
        self.assertEqual(self.operator.capture_full_action_frame.call_count, 4)
        self.page.mouse.click.assert_called_once_with(1307.5, 827.5)
        self.assertEqual(self.original_clock_at_click, [(100.0, 100.0)])

    def test_unknown_timing_or_metadata_error_still_defers_without_pass(self):
        self.operator.evaluate_force_auto_call_policy.side_effect = RetryableSafetyAbort(
            "reaction decision has no valid timing evidence")
        self.run_frame()
        self.solver.assert_not_called()
        self.page.screenshot.assert_not_called()
        self.page.mouse.click.assert_not_called()
        self.assertEqual(self.operator.action_budget_started_at, 100.0)

    def test_unexpected_evaluator_error_is_not_swallowed(self):
        self.operator.evaluate_force_auto_call_policy.side_effect = RuntimeError("unexpected evaluator failure")
        with self.assertRaisesRegex(RuntimeError, "unexpected evaluator failure"):
            self.run_frame()
        self.page.screenshot.assert_not_called()
        self.page.mouse.click.assert_not_called()

    def test_tenpai_guard_still_forbids_blind_pass_without_visible_green_call(self):
        self.operator.last_shanten = 0
        # A pass-like affordance without an independently identified green
        # call must still be guarded. This is the existing guard's precise
        # scope, not an extension to explicit chi/pon/kan prompts.
        with patch("auto_operator.is_force_auto_pass_clip", return_value=True), \
                patch("auto_operator.is_force_auto_pass_prompt", return_value=True):
            self.run_frame(green_call=False)
        self.solver.assert_not_called()
        self.page.screenshot.assert_not_called()
        self.page.mouse.click.assert_not_called()
        self.assertEqual(self.operator.action_evidence_started_at, 100.0)
        self.assertTrue(any(call.args[0] == "tenpai_reaction_guard"
                            for call in self.operator.log.call_args_list))

    def test_tenpai_with_explicit_green_call_keeps_existing_verified_pass_permission(self):
        self.operator.last_shanten = 0
        self.run_frame()
        self.solver.assert_not_called()
        self.page.mouse.click.assert_called_once()

    def test_original_global_deadline_still_forbids_pass(self):
        self.operator.args.action_deadline_ms = 2500
        self.run_frame()
        self.solver.assert_not_called()
        self.page.mouse.click.assert_not_called()
        self.assertEqual(self.operator.action_evidence_started_at, 100.0)
        event = next(call for call in self.operator.log.call_args_list
                     if call.args[0] == "reaction_pass_deferred")
        self.assertIn("deadline", event.kwargs["error"])

    def test_named_win_branch_remains_before_optional_call_budget(self):
        self.run_frame(win=True)
        self.operator.execute_force_auto_reaction_win.assert_called_once()
        self.operator.evaluate_force_auto_call_policy.assert_not_called()
        self.page.screenshot.assert_not_called()
        self.page.mouse.click.assert_not_called()

    def test_only_budget_exhaustion_changes_retry_policy(self):
        self.assertFalse(should_retry_call_policy(OptionalReactionBudgetExhausted("reserve"), 0))
        for error in (RetryableSafetyAbort("reaction decision has no valid timing evidence"),
                      RetryableSafetyAbort("metadata not verified"),
                      RetryableSafetyAbort("reaction decision budget lacks launch and click reserve"),
                      RuntimeError("unknown failure")):
            with self.subTest(error=error):
                self.assertTrue(should_retry_call_policy(error, 90000))
        conflict = RetryableSafetyAbort("reaction_tile_count_conflict")
        self.assertTrue(should_retry_call_policy(conflict, 19999))
        self.assertFalse(should_retry_call_policy(conflict, 20000))

    def native_frame(self, name):
        fixture = load_json(ROOT / "test/fixtures/optional-call-pass-controls-20261030.json")
        item = next(frame for frame in fixture["frames"] if frame["name"] == name)
        image = Image.new("RGB", tuple(fixture["size"]), (20, 40, 70))
        image.paste(Image.open(io.BytesIO(self.pass_pixels)), (1170, 775))
        for part in item["parts"]:
            raw = base64.b64decode(part["pngBase64"], validate=True)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), part["sha256"])
            image.paste(Image.open(io.BytesIO(raw)), tuple(part["box"][:2]))
        result = io.BytesIO()
        image.save(result, "PNG")
        return result.getvalue()

    def execute_native_pair(self, second=None):
        # Pixel classifiers for call/skip/orange/draw are real here. Only
        # match classification is injected: omitted private/board pixels in
        # these ROI composites cannot attest the full table foreground.
        first = self.native_frame("chi")
        calls = force_auto_call_buttons(first, self.operator.layout["viewport"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["action"], "chi")
        self.assertFalse(force_auto_self_action_buttons(first, self.operator.layout["viewport"]))
        self.capture_images = [first, first if second is None else second]
        evaluation = {"actionButton": {"action": "pass", "center": {"x": 1307.5, "y": 827.5}}}
        with patch("auto_operator.classify_screen", return_value=("match", 1)):
            return self.operator.execute_reaction_pass(
                self.page, evaluation, evaluated_captured_at=100.0, expired_optional_call=calls[0],
            )

    def test_native_green_chi_and_identical_skip_confirm_twice_and_click(self):
        receipt = self.execute_native_pair()
        self.assertTrue(receipt["clicked"])
        self.assertEqual(self.operator.capture_full_action_frame.call_count, 2)
        self.page.wait_for_timeout.assert_any_call(120)
        self.assertGreaterEqual(self.now, 103.32)  # both captures +120ms charged
        self.page.mouse.click.assert_called_once_with(1307.5, 827.5)
        self.assertEqual(self.original_clock_at_click, [(100.0, 100.0)])

    def test_native_second_frame_ron_with_identical_skip_never_passes(self):
        ron = self.native_frame("ron")
        self.assertTrue(force_auto_self_action_buttons(ron, self.operator.layout["viewport"]))
        with self.assertRaisesRegex(RetryableSafetyAbort, "win or changed screen"):
            self.execute_native_pair(ron)
        self.page.mouse.click.assert_not_called()
        self.assertEqual(self.operator.action_evidence_started_at, 100.0)

    def test_current_draw_or_missing_moved_green_or_partial_frame_never_passes(self):
        native = self.native_frame("chi")
        for case in ("draw", "missing", "moved", "partial", "skip_missing"):
            with self.subTest(case=case):
                image = Image.open(io.BytesIO(native)).convert("RGB")
                if case == "draw":
                    image.paste((255, 255, 255), (1486, 926, 1578, 1072))
                elif case in {"missing", "moved"}:
                    call = image.crop((875, 775, 1145, 880))
                    image.paste((20, 40, 70), (875, 775, 1145, 880))
                    if case == "moved":
                        image.paste(call, (925, 775))
                elif case == "skip_missing":
                    image.paste((20, 40, 70), (1170, 775, 1445, 880))
                else:
                    image = image.crop((0, 0, 1500, 1000))
                changed = io.BytesIO()
                image.save(changed, "PNG")
                with self.assertRaises(RetryableSafetyAbort):
                    self.execute_native_pair(changed.getvalue())
                self.page.mouse.click.assert_not_called()
                self.assertEqual(self.operator.action_budget_started_at, 100.0)

    def test_capture_cost_cannot_exceed_freshness_or_original_global_deadline(self):
        for case in ("freshness", "global"):
            with self.subTest(case=case):
                self.now = 103.0
                self.capture_cost = 1.4 if case == "freshness" else .1
                self.operator.args.action_deadline_ms = 300000 if case == "freshness" else 3300
                with self.assertRaisesRegex(RetryableSafetyAbort, "budget|deadline"):
                    self.execute_native_pair()
                self.page.mouse.click.assert_not_called()
                self.assertEqual(self.operator.action_evidence_started_at, 100.0)

    def test_unknown_future_or_wrong_kind_original_clock_cannot_certify_pass(self):
        for started, budget, kind in ((None, 100, "reaction"), (float("nan"), 100, "reaction"),
                                      (100, 104, "reaction"), (100, 99, "reaction"),
                                      (100, 100, "discard")):
            with self.subTest(started=started, budget=budget, kind=kind):
                self.operator.action_evidence_started_at = started
                self.operator.action_budget_started_at = budget
                self.operator.action_evidence_kind = kind
                with self.assertRaisesRegex(RetryableSafetyAbort, "original reaction clock"):
                    self.execute_native_pair()
                self.page.mouse.click.assert_not_called()
        self.operator.capture_full_action_frame.assert_not_called()

    def test_invalid_capture_times_or_reused_second_timestamp_never_certify_pass(self):
        capture = self.operator.capture_full_action_frame.side_effect
        for case in ("nan", "future", "overlap"):
            with self.subTest(case=case):
                receipts = []
                def invalid_capture(*args):
                    receipt = capture(*args)
                    if case == "nan":
                        return replace(receipt, attempt_started_at=float("nan"))
                    if case == "future":
                        return replace(receipt, completed_at=self.now + 1)
                    if receipts:
                        return replace(receipt, attempt_started_at=receipts[0].completed_at,
                                       started_at=receipts[0].completed_at)
                    receipts.append(receipt)
                    return receipt
                self.operator.capture_full_action_frame.side_effect = invalid_capture
                with self.assertRaisesRegex(RetryableSafetyAbort, "capture times"):
                    self.execute_native_pair()
                self.page.mouse.click.assert_not_called()

    def test_clock_change_during_capture_cannot_leak_certificate_into_another_action(self):
        capture = self.operator.capture_full_action_frame.side_effect
        def changed_clock(*args):
            receipt = capture(*args)
            self.operator.action_budget_started_at = 100.1
            return receipt
        self.operator.capture_full_action_frame.side_effect = changed_clock
        with self.assertRaisesRegex(RetryableSafetyAbort, "original clock changed"):
            self.execute_native_pair()
        self.page.mouse.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
