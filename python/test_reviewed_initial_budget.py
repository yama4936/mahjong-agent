"""The reviewed 300+0 first action has distinct global/processing clocks."""
import argparse
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

import friend_start
from auto_operator import PythonAutoOperator, RetryableSafetyAbort


class ReviewedInitialBudgetTest(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        clock = patch("auto_operator.time.monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        # Only the already reviewed time-label pixels are needed by this
        # eligibility test. Actual room/control binding is separately covered
        # by test_friend_start; run's room verifier is mocked below.
        image = Image.new("RGB", (1920, 1080), (20, 40, 70))
        native_room = Path(__file__).resolve().parents[1] / "artifacts/live/300-fixed-125bd6d-room-settings-20260928.png"
        with Image.open(native_room) as native:
            image.paste(native.crop((1670, 260, 1810, 290)), (1670, 260))
        encoded = io.BytesIO()
        image.save(encoded, "PNG")
        self.reviewed = encoded.getvalue()
        self.assertTrue(friend_start.reviewed_friend_clock_is_300_plus_zero(self.reviewed))
        self.preflight = self.directory / "reviewed.png"
        self.preflight.write_bytes(self.reviewed)
        op = self.operator = PythonAutoOperator.__new__(PythonAutoOperator)
        op.args = argparse.Namespace(mode="force-auto", ranked_loop=False, board_metadata=False,
                                    action_deadline_ms=300000, force_auto_click_budget_ms=2600,
                                    start_reviewed_friend_room=str(self.preflight),
                                    max_iterations=2, poll=0, stop_on_error=False)
        op.log = Mock()
        op.action_evidence_started_at = None
        op.action_budget_started_at = None
        op.action_evidence_kind = None

    def origin(self, anchor=0, captured=15.7, processing=15.9, reviewed=None):
        return self.operator.reviewed_friend_initial_budget_origin(
            self.reviewed if reviewed is None else reviewed, initial_anchor=anchor,
            original_gate_captured_at=captured, gate_processing_started_at=processing,
        )

    def run_to_evidence(self, *, receipt=15.7, processing=15.9, prewarm_cost=0,
                        replacement_capture_cost=0, classification_cost=0, repeats=2,
                        draw_frames=None, frame_step=.4):
        """Exercise real run/StartupTurnGuard up to each evidence latch.

        A local probe exception advances the loop before recognition, so this
        checks the real eligibility/one-shot wiring without model/browser work.
        """
        op = self.operator
        op.args.max_iterations = repeats
        op.layout = {"viewport": {"width": 1920, "height": 1080}, "drawSlot": {"x": 1500}}
        op.frames = self.directory
        op.screen_references = {}
        op.cached_public_observation = None
        op.previous_public_observation = None
        op.cached_open_melds = 0
        op.pending_post_call_discard = False
        op.restart_open_hand_probe_hash = None
        op.screencast_session = Mock()
        op.screencast_sequence = 0
        op.screencast_draw_generation = 1
        op.screencast_draw_occupied = True
        op.latest_screencast_frame = b"frame"
        op.latest_screencast_captured_at = receipt
        op.ensure_viewport = Mock()
        op.poll_public_recognition = Mock()
        op.start_screencast_gate = Mock(side_effect=lambda _page: setattr(self, "now", processing))
        op.warm_reviewed_friend_board_ocr = Mock(return_value=False)
        op.should_reset_open_hand_state = Mock(return_value=False)
        op.verified_visible_open_melds = Mock(return_value=None)
        op.stable_open_meld_count = Mock(return_value=None)
        op.restart_open_hand_probe_needed = Mock(return_value=False)
        op.quick_draw_occupied = Mock(return_value=True, side_effect=draw_frames)
        op.handle_early_non_gameplay_screen = Mock(return_value=False)
        op.bound_initial_action_from_dealing = Mock(return_value=False)
        op.resume_startup_away = Mock(return_value=False)
        op.try_startup_terminal_win = Mock(return_value=False)

        iteration = [0]
        def next_frame(_page):
            if iteration[0]:
                self.now += frame_step
                op.latest_screencast_captured_at = self.now - .1
            iteration[0] += 1
            op.screencast_sequence += 1
            return False
        op.capture_self_win_result = Mock(side_effect=next_frame)

        def verify(_page, state, confidence, frame):
            if replacement_capture_cost:
                self.now += replacement_capture_cost
                return "match", 1.0, b"replacement", True
            return state, confidence, frame, False
        op.verify_screencast_non_gameplay_state = Mock(side_effect=verify)

        def prewarm(*_args, **_kwargs):
            self.now += prewarm_cost
        op.prewarm_startup_context = Mock(side_effect=prewarm)
        recorded = []
        def mark(kind, **kwargs):
            PythonAutoOperator.mark_action_evidence(op, kind, **kwargs)
            recorded.append((op.action_evidence_started_at, op.action_budget_started_at, self.now))
            raise RuntimeError("evidence probe: skip recognition")
        op.mark_action_evidence = Mock(side_effect=mark)
        page = Mock()
        page.url = "https://game.mahjongsoul.com/index.html"
        def classify(*_args):
            self.now += classification_cost
            return "match", 1
        with patch("auto_operator.await_reviewed_friend_room", return_value=2) as verifier, \
                patch("auto_operator.classify_screen", side_effect=classify), \
                patch("auto_operator.perceptual_hash", return_value="same-frame"), \
                patch("auto_operator.geometric_open_meld_count", return_value=None), \
                patch("auto_operator.open_hand_draw_slot", return_value=None), \
                patch("auto_operator.time.sleep"):
            op.run(page)
        for event in op.log.call_args_list:
            if event.args[0] == "safety_stop":
                self.assertEqual(event.kwargs["error"], "evidence probe: skip recognition")
        return recorded, page, verifier

    def test_real_run_2600_regression_keeps_original_deadline_and_first_receipt_once(self):
        recorded, page, verifier = self.run_to_evidence(receipt=15.760, processing=16.212)
        self.assertEqual(len(recorded), 2)
        self.assertEqual([entry[:2] for entry in recorded], [(0, 15.760)] * 2)
        self.assertEqual(page.mouse.click.call_count, 1)  # Only the reviewed room start.
        verifier.assert_called_once()
        events = [event for event in self.operator.log.call_args_list
                  if event.args[0] == "friend_initial_budget_clock_separated"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kwargs["originalActionStartedAt"], 0)
        self.assertAlmostEqual(self.operator.action_deadline_remaining_ms(), 283388)
        self.assertEqual(self.operator.force_auto_action_evidence_age_ms(), 852)
        self.operator.require_force_auto_click_budget(self.now - .1, phase="before_recognition")

    def test_real_run_existing_8000_separation_is_preserved(self):
        self.operator.args.force_auto_click_budget_ms = 8000
        recorded, _, _ = self.run_to_evidence()
        self.assertEqual([entry[:2] for entry in recorded], [(0, 15.7)] * 2)

    def test_real_run_charges_prewarm_and_synchronous_replacement_capture(self):
        recorded, _, _ = self.run_to_evidence(prewarm_cost=.5, replacement_capture_cost=.7,
                                            classification_cost=.2, repeats=1)
        self.assertEqual(recorded[0][:2], (0, 15.7))
        # The charged work leaves exactly the normal self-turn's 1000ms
        # two-click admission reserve; one more millisecond must reject.
        self.assertAlmostEqual(recorded[0][2], 17.3)
        self.assertEqual(self.operator.force_auto_action_evidence_age_ms(), 1600)
        self.operator.require_force_auto_discard_selection_window(15.7)
        self.now += .051
        with self.assertRaisesRegex(RetryableSafetyAbort, "lacks time"):
            self.operator.require_force_auto_discard_selection_window(15.7)
        # Independently exercise the unchanged 2600ms image-freshness guard.
        self.now += .950
        with self.assertRaises(RetryableSafetyAbort):
            self.operator.require_force_auto_click_budget(15.7, phase="before_recognition")

    def test_processing_start_before_refreshed_receipt_is_the_conservative_origin(self):
        self.now = 20
        self.assertEqual(self.origin(captured=16.9, processing=15.9), 15.9)

    def test_real_run_never_separates_unverified_short_clock_or_short_deadline(self):
        for short_clock, deadline in ((True, 300000), (False, 5000)):
            with self.subTest(short_clock=short_clock):
                self.operator.action_evidence_started_at = None
                self.operator.action_budget_started_at = None
                self.operator.action_evidence_kind = None
                self.operator.args.action_deadline_ms = deadline
                self.now = 0
                self.preflight.write_bytes(b"not a verified 300+0 label" if short_clock else self.reviewed)
                recorded, _, _ = self.run_to_evidence(repeats=1)
                self.assertEqual(recorded[0][:2], (0, 0))

    def test_ranked_or_missing_verified_start_cannot_use_initial_separation(self):
        self.now = 20
        self.operator.args.ranked_loop = True
        self.assertIsNone(self.origin())
        self.operator.args.ranked_loop = False
        self.assertIsNone(self.operator.reviewed_friend_initial_budget_origin(
            None, initial_anchor=0, original_gate_captured_at=15.7, gate_processing_started_at=15.9))
        self.assertIsNone(self.origin(anchor=None))  # Later turn or inactive startup boundary.

    def test_other_modes_budgets_and_ranked_actual_run_remain_disallowed(self):
        self.now = 20
        for mode in ("observer", "advisor", "auto"):
            self.operator.args.mode = mode
            self.assertIsNone(self.origin())
        self.operator.args.mode = "force-auto"
        for budget in (None, 0, 2000, 5000, 8001):
            self.operator.args.force_auto_click_budget_ms = budget
            self.assertIsNone(self.origin())
        self.operator.args.force_auto_click_budget_ms = 2600
        self.operator.args.ranked_loop = True
        with self.assertRaisesRegex(RuntimeError, "requires non-ranked"):
            self.run_to_evidence()

    def test_inactive_startup_boundary_does_not_separate_or_backdate_later_turn(self):
        recorded, _, _ = self.run_to_evidence(repeats=3, draw_frames=[False, False, True],
                                            frame_step=1.1)
        self.assertEqual(len(recorded), 1)
        self.assertAlmostEqual(recorded[0][0], 18.1)
        self.assertAlmostEqual(recorded[0][1], 18.1)
        self.assertFalse(any(event.args[0] == "friend_initial_budget_clock_separated"
                             for event in self.operator.log.call_args_list))

    def test_actual_restart_does_not_invent_a_reviewed_start_or_clock(self):
        self.operator.args.start_reviewed_friend_room = None
        recorded, page, verifier = self.run_to_evidence()
        self.assertEqual(recorded, [])
        page.mouse.click.assert_not_called()
        verifier.assert_not_called()
        self.assertIsNone(self.operator.action_evidence_started_at)

    def test_stale_verified_start_is_still_quarantined_by_real_guard(self):
        recorded, _, _ = self.run_to_evidence(receipt=31, processing=31.1)
        self.assertEqual(recorded, [])
        self.assertIsNone(self.operator.action_budget_started_at)

    def test_unknown_invalid_future_or_pre_anchor_timestamps_never_separate(self):
        self.now = 20
        for name in ("anchor", "captured", "processing"):
            for value in (None, float("nan"), float("inf"), True, "15", -1, 21):
                with self.subTest(name=name, value=value):
                    self.assertIsNone(self.origin(**{name: value}))
        self.assertIsNone(self.origin(anchor=16, captured=15.9, processing=17))
        self.assertIsNone(self.origin(anchor=16, captured=17, processing=15.9))

    def test_newer_frames_cannot_refresh_budget_and_original_global_deadline_still_expires(self):
        self.run_to_evidence(repeats=1)
        for now in (26, 103.424):
            self.now = now
            self.operator.mark_action_evidence.side_effect = None
            # Exercise the actual original latch, not the run probe wrapper.
            PythonAutoOperator.mark_action_evidence(self.operator, "discard")
            self.assertEqual(self.operator.action_budget_started_at, 15.7)
            with self.assertRaises(RetryableSafetyAbort):
                self.operator.require_force_auto_click_budget(now - .1, phase="before_recognition")
        self.now = 299.999
        self.operator.require_action_deadline()
        self.now = 300
        for _phase in ("first_click", "second_click"):
            with self.assertRaisesRegex(RetryableSafetyAbort, "deadline expired"):
                self.operator.require_action_deadline()


if __name__ == "__main__":
    unittest.main()
