"""Reaction solver time must fit the original opportunity, not each image."""
import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from auto_operator import PythonAutoOperator, RetryableSafetyAbort


class ReactionDecisionBudgetTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.operator = PythonAutoOperator.__new__(PythonAutoOperator)
        self.operator.args = argparse.Namespace(
            mode="force-auto", board_metadata=False, action_templates=None,
            evaluation_timeout=5, force_auto_click_budget_ms=2600,
            action_deadline_ms=300000,
        )
        self.operator.frames = Path(temporary.name)
        self.operator.root = self.operator.frames
        self.operator.state_path = self.operator.frames / "state.json"
        self.operator.layout_path = self.operator.frames / "layout.json"
        self.operator.templates = self.operator.frames
        self.operator.evaluator_env = {"JEV_FORCE_AUTO_DEADLINE_MS": "2300"}
        self.operator.action_evidence_started_at = 100.0
        self.operator.action_budget_started_at = 100.0
        self.operator.action_evidence_kind = "reaction"
        self.operator.log = Mock()
        self.now = 101.827
        clock = patch("auto_operator.time.monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        runner = patch("auto_operator.subprocess.run", return_value=argparse.Namespace(
            returncode=0, stdout='{"status":"decision"}',
        ))
        self.run = runner.start()
        self.addCleanup(runner.stop)

    def evaluate(self, captured=100.322):
        return self.operator.evaluate(
            self.operator.frames / "prompt.png", {"tile": "1m", "fromSeat": "south"},
            {"ownDiscards": []}, {"tiles": ["1m"] * 13}, ["pon", "pass"],
            captured_at=captured,
        )

    def budget(self):
        return self.run.call_args.kwargs["env"]["JEV_FORCE_AUTO_DEADLINE_MS"]

    def test_773ms_original_remaining_not_1095ms_new_image_leaves_123ms_solver(self):
        self.evaluate()
        self.assertEqual(self.budget(), "123")
        event = next(call for call in self.operator.log.call_args_list
                     if call.args[0] == "reaction_decision_budget")
        self.assertEqual(event.kwargs["captureRemainingMs"], 1095)
        self.assertEqual(event.kwargs["actionBudgetRemainingMs"], 773)
        self.assertEqual(event.kwargs["remainingMs"], 773)
        self.assertEqual(self.operator.evaluator_env["JEV_FORCE_AUTO_DEADLINE_MS"], "2300")

    def test_223ms_original_remaining_does_not_launch_one_ms_solver(self):
        self.now = 102.377
        with self.assertRaisesRegex(RetryableSafetyAbort, "reserve"):
            self.evaluate(100.067)  # New frame had 290ms, original only 223ms.
        self.run.assert_not_called()

    def test_fresh_repeated_frames_do_not_relend_expired_original_clock(self):
        for elapsed, frame_age in ((5.052, 1.229), (7.251, 1.281)):
            self.now = 100 + elapsed
            with self.subTest(elapsed=elapsed), self.assertRaises(RetryableSafetyAbort):
                self.evaluate(self.now - frame_age)
        self.run.assert_not_called()
        self.assertEqual(self.operator.action_evidence_started_at, 100)
        self.assertEqual(self.operator.action_budget_started_at, 100)
        self.assertEqual(self.operator.action_evidence_kind, "reaction")

    def test_each_of_capture_original_budget_and_action_deadline_can_limit(self):
        self.now = 101
        for captured, budget_started, deadline, expected in (
            (99.8, 100.5, 300000, "750"),  # image: 1400ms left
            (100.8, 99.8, 300000, "750"),  # original budget: 1400ms left
            (100.8, 100.5, 2000, "350"),  # whole action: 1000ms left
        ):
            self.operator.action_budget_started_at = budget_started
            self.operator.args.action_deadline_ms = deadline
            with self.subTest(expected=expected, captured=captured):
                self.evaluate(captured)
                self.assertEqual(self.budget(), expected)

    def test_original_deadline_expired_or_reserve_boundary_suppresses_model(self):
        self.now = 101
        for deadline in (500, 1000, 1650):
            self.operator.args.action_deadline_ms = deadline
            with self.subTest(deadline=deadline), self.assertRaises(RetryableSafetyAbort):
                self.evaluate(100.9)
        self.run.assert_not_called()

    def test_evaluator_environment_cap_and_original_start_fallback_are_preserved(self):
        self.operator.action_budget_started_at = None
        self.operator.evaluator_env["JEV_FORCE_AUTO_DEADLINE_MS"] = "100"
        self.evaluate()
        self.assertEqual(self.budget(), "100")
        self.assertIsNone(self.operator.action_budget_started_at)

    def test_nonpositive_environment_cap_keeps_legacy_one_ms_floor(self):
        for configured in ("0", "-1", "-2300"):
            self.operator.evaluator_env["JEV_FORCE_AUTO_DEADLINE_MS"] = configured
            with self.subTest(configured=configured):
                self.evaluate()
                self.assertEqual(self.budget(), "1")
        self.run.reset_mock()
        self.now = 102.377
        with self.assertRaisesRegex(RetryableSafetyAbort, "reserve"):
            self.evaluate(100.067)
        self.run.assert_not_called()

    def test_unknown_original_or_capture_clock_in_short_mode_fails_closed(self):
        for captured, action, budget in ((None, 100, 100), (100, None, None)):
            self.operator.action_evidence_started_at = action
            self.operator.action_budget_started_at = budget
            with self.subTest(captured=captured), self.assertRaises(RetryableSafetyAbort):
                self.evaluate(captured)
        self.run.assert_not_called()

    def test_known_budget_clock_without_action_origin_does_not_invent_deadline(self):
        self.operator.action_evidence_started_at = None
        self.operator.args.action_deadline_ms = 1
        self.evaluate()
        self.assertEqual(self.budget(), "123")

    def test_expired_image_and_invalid_known_deadline_do_not_launch_model(self):
        with self.assertRaises(RetryableSafetyAbort):
            self.evaluate(99)
        for deadline in (0, -1, float("nan"), float("inf"), "300000", True):
            self.operator.args.action_deadline_ms = deadline
            with self.subTest(deadline=deadline), self.assertRaises(RetryableSafetyAbort):
                self.evaluate()
        self.run.assert_not_called()

    def test_invalid_or_future_clocks_cannot_create_budget(self):
        for name in ("captured", "action_evidence_started_at", "action_budget_started_at"):
            for value in (float("nan"), float("inf"), "100", True, 102):
                self.operator.action_evidence_started_at = 100
                self.operator.action_budget_started_at = 100
                captured = 100.322
                if name == "captured":
                    captured = value
                else:
                    setattr(self.operator, name, value)
                with self.subTest(name=name, value=value), self.assertRaises(RetryableSafetyAbort):
                    self.evaluate(captured)
        self.run.assert_not_called()

    def test_without_optional_click_budget_known_overall_deadline_still_limits(self):
        self.operator.args.force_auto_click_budget_ms = None
        self.operator.args.action_deadline_ms = 3000
        self.evaluate(None)
        self.assertEqual(self.budget(), "523")

    def test_no_configured_timing_limits_keeps_env_cap_without_fabricated_deadline(self):
        self.operator.args.force_auto_click_budget_ms = None
        self.operator.args.action_deadline_ms = None
        self.operator.action_evidence_started_at = None
        self.operator.action_budget_started_at = None
        self.evaluate(None)
        self.assertEqual(self.budget(), "2300")

    def test_self_turn_path_is_not_changed_by_reaction_clock_constraints(self):
        self.operator.action_evidence_started_at = 0
        self.operator.action_budget_started_at = 0
        self.operator.args.action_deadline_ms = 1
        self.now = 11.9
        self.operator.evaluate(self.operator.frames / "self.png", captured_at=10)
        self.assertEqual(self.budget(), "50")

    def test_rejected_call_does_not_poison_independently_established_new_win(self):
        self.now = 106
        with self.assertRaises(RetryableSafetyAbort):
            self.evaluate(105.9)
        self.run.assert_not_called()
        # A new independently confirmed action may supersede the old clock.
        # The solver rejection is local, not a global stop/new-action guard.
        self.operator.mark_action_evidence("win", observed_at=106, supersede=True)
        for phase in ("before_reaction_win_click", "before_tsumo_click"):
            self.operator.require_force_auto_click_budget(106, phase=phase)
            self.operator.require_action_deadline()
        self.assertEqual(self.operator.action_evidence_started_at, 106)


if __name__ == "__main__":
    unittest.main()
