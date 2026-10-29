"""The resident self-turn solver never borrows a fresh original turn clock."""
import argparse
import io
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from auto_operator import PythonAutoOperator, RetryableSafetyAbort, load_json


class ResidentSelfTurnBudgetTest(unittest.TestCase):
    def setUp(self):
        self.now = 101.377
        clock = patch("auto_operator.time.monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        wall = patch("auto_operator.time.time", return_value=1000)
        wall.start()
        self.addCleanup(wall.stop)
        op = self.operator = PythonAutoOperator.__new__(PythonAutoOperator)
        op.args = argparse.Namespace(mode="force-auto", force_auto_click_budget_ms=2600,
                                    action_deadline_ms=300000, board_metadata=False)
        op.action_evidence_started_at = 100.0
        op.action_budget_started_at = 100.0
        op.action_evidence_kind = "discard"
        op.action_budget_draw_generation = 4
        op.screencast_draw_generation = 4
        op.screencast_draw_occupied = True
        op.selection_uncertainty_latch = None
        op.recognition_request_id = 0
        op.recognition_server = Mock()
        op.recognition_server.poll.return_value = None
        op.public_state = {}
        op.log = Mock()

    def payload(self, captured=101.1, **kwargs):
        self.operator.recognition_request_id = 0
        self.operator.recognition_server.stdin = io.StringIO()
        self.operator.recognition_server.stdout = io.StringIO('{"id":1,"result":{}}\n')
        self.operator.recognize_resident(Path("immutable-frame.jpg"), captured_at=captured, **kwargs)
        return json.loads(self.operator.recognition_server.stdin.getvalue())

    def test_actual_resident_payload_binds_same_draw_budget_and_original_global_deadline(self):
        request = self.payload(evaluate_force_auto=True)
        self.assertEqual(request["actionBudgetRemainingMs"], 8623)
        self.assertEqual(request["actionDeadlineRemainingMs"], 298623)
        self.assertEqual(request["discardSelectionReserveMs"], 650)
        self.assertAlmostEqual(request["frameCapturedAtMs"], 999723)
        self.assertEqual(self.operator.action_evidence_started_at, 100)
        self.assertEqual(self.operator.action_budget_started_at, 100)

    def test_only_existing_verified_same_draw_grace_can_increase_action_remaining(self):
        self.operator.screencast_draw_generation = 5
        self.assertEqual(self.payload(evaluate_force_auto=True)["actionBudgetRemainingMs"], 1223)
        self.operator.screencast_draw_generation = 4
        self.operator.selection_uncertainty_latch = {"pending": True}
        self.assertEqual(self.payload(evaluate_force_auto=True)["actionBudgetRemainingMs"], 1223)
        self.operator.selection_uncertainty_latch = None
        self.operator.args.force_auto_click_budget_ms = 8000
        self.assertEqual(self.payload(evaluate_force_auto=True)["actionBudgetRemainingMs"], 6623)

    def test_repeated_fresh_receipts_reduce_not_reset_original_remaining(self):
        self.assertEqual(self.payload(evaluate_force_auto=True)["actionBudgetRemainingMs"], 8623)
        self.now += 1
        self.assertEqual(self.payload(captured=self.now - .1,
                                      evaluate_force_auto=True)["actionBudgetRemainingMs"], 7623)
        self.operator.action_budget_started_at = None
        self.assertEqual(self.payload(captured=self.now - .1,
                                      evaluate_force_auto=True)["actionBudgetRemainingMs"], 7623)
        self.assertEqual(self.operator.action_evidence_started_at, 100)
        self.assertIsNone(self.operator.action_budget_started_at)

    def test_expired_original_is_sent_as_expired_and_final_click_guard_still_rejects(self):
        self.now = 111
        request = self.payload(captured=110.9, evaluate_force_auto=True)
        self.assertEqual(request["actionBudgetRemainingMs"], -1000)
        with self.assertRaisesRegex(RetryableSafetyAbort, "click budget expired"):
            self.operator.require_force_auto_click_budget(110.9, phase="before_discard_click")
        self.assertEqual(self.operator.action_budget_started_at, 100)

    def test_global_2500_and_5000_deadlines_stay_on_the_original_clock(self):
        self.now = 102
        for deadline, remaining in ((2500, 500), (5000, 3000)):
            self.operator.args.action_deadline_ms = deadline
            self.operator.args.force_auto_click_budget_ms = min(2600, deadline)
            with self.subTest(deadline=deadline):
                self.assertEqual(self.payload(captured=101.9, evaluate_force_auto=True)
                                 ["actionDeadlineRemainingMs"], remaining)
        self.now = 105.001
        self.assertEqual(self.payload(captured=105, evaluate_force_auto=True)
                         ["actionDeadlineRemainingMs"], 0)
        with self.assertRaises(RetryableSafetyAbort):
            self.operator.require_action_deadline()

    def test_metadata_cost_before_resident_request_is_charged_without_changing_capture_origin(self):
        self.operator.args.board_metadata = True
        def metadata(*_args, **_kwargs):
            self.now += 1.3
            return {}, None, None
        self.operator.frame_metadata_state = Mock(side_effect=metadata)
        request = self.payload(evaluate_force_auto=True)
        self.assertEqual(request["actionBudgetRemainingMs"], 7323)
        self.assertEqual(request["actionDeadlineRemainingMs"], 297323)
        self.assertAlmostEqual(request["frameCapturedAtMs"], 998423)

    def test_unknown_invalid_future_or_reversed_original_clocks_never_start_resident(self):
        for name in ("captured", "action_evidence_started_at", "action_budget_started_at"):
            for bad in (float("nan"), float("inf"), True, "100", 102):
                self.operator.action_evidence_started_at = 100
                self.operator.action_budget_started_at = 100
                captured = 101.1
                if name == "captured":
                    captured = bad
                else:
                    setattr(self.operator, name, bad)
                self.operator.recognition_server.stdin = io.StringIO()
                with self.subTest(name=name, bad=bad), self.assertRaises(RetryableSafetyAbort):
                    self.payload(captured=captured, evaluate_force_auto=True)
                self.assertEqual(self.operator.recognition_server.stdin.getvalue(), "")
        self.operator.action_evidence_started_at = None
        self.operator.action_budget_started_at = None
        with self.assertRaises(RetryableSafetyAbort):
            self.payload(evaluate_force_auto=True)
        self.operator.action_evidence_started_at = 100
        self.operator.action_budget_started_at = 99
        with self.assertRaises(RetryableSafetyAbort):
            self.payload(evaluate_force_auto=True)
        self.operator.action_budget_started_at = 100
        with self.assertRaises(RetryableSafetyAbort):
            self.payload(captured=None, evaluate_force_auto=True)

    def test_wrong_kind_or_invalid_global_deadline_does_not_create_allowance(self):
        self.operator.action_evidence_kind = "reaction"
        with self.assertRaises(RetryableSafetyAbort):
            self.payload(evaluate_force_auto=True)
        self.operator.action_evidence_kind = "discard"
        for deadline in (None, 0, float("nan"), True):
            self.operator.args.action_deadline_ms = deadline
            with self.subTest(deadline=deadline), self.assertRaises(RetryableSafetyAbort):
                self.payload(evaluate_force_auto=True)

    def test_legacy_non_force_and_recognition_staging_payloads_are_unchanged(self):
        for mode in ("observer", "advisor", "auto"):
            self.operator.args.mode = mode
            request = self.payload(evaluate_force_auto=True)
            self.assertNotIn("actionBudgetRemainingMs", request)
            self.assertNotIn("discardSelectionReserveMs", request)
        self.operator.args.mode = "force-auto"
        for kwargs in ({}, {"stage_force_auto_recognition": True}, {"concealed_only": True}):
            request = self.payload(captured=None, **kwargs)
            self.assertNotIn("actionBudgetRemainingMs", request)
            self.assertNotIn("discardSelectionReserveMs", request)
        self.operator.args.force_auto_click_budget_ms = None
        self.assertNotIn("discardSelectionReserveMs", self.payload(evaluate_force_auto=True))

    def test_raw_failed_reserve_can_finish_with_earlier_local_without_any_clock_reset(self):
        root = Path(__file__).resolve().parents[1]
        raw = load_json(root / "test/fixtures/self-turn-reserve-overrun-20261030.json")["cases"][0]
        self.now = 100 + raw["actionEvidenceAgeBeforeClickMs"] / 1000
        old_capture = self.now - raw["imageAgeBeforeClickMs"] / 1000
        with self.assertRaisesRegex(RetryableSafetyAbort, "lacks time"):
            self.operator.require_force_auto_discard_selection_window(old_capture)
        # Alternative earlier completion, using the *same* original image.
        # Neither its receipt nor the original action clock gets refreshed.
        self.now -= .650
        self.operator.require_force_auto_discard_selection_window(old_capture)
        self.assertEqual(self.operator.action_evidence_started_at, 100)
        self.assertEqual(self.operator.action_budget_started_at, 100)
        self.now = 110.001
        with self.assertRaises(RetryableSafetyAbort):
            self.operator.require_force_auto_discard_selection_window(self.now - .1)


if __name__ == "__main__":
    unittest.main()
