"""Regressions for the 2026-10-29 16:35 HUD wait and bounded turn grace."""
import argparse
import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from auto_operator import PythonAutoOperator, RetryableSafetyAbort, board_state_signature


class BudgetGraceTest(unittest.TestCase):
    def operator(self):
        op = PythonAutoOperator.__new__(PythonAutoOperator)
        op.args = argparse.Namespace(force_auto_click_budget_ms=2600, ranked_loop=True)
        op.log = Mock()
        op.action_evidence_started_at = 10.0
        op.action_evidence_kind = "discard"
        op.action_budget_draw_generation = 7
        op.screencast_draw_generation = 7
        op.screencast_draw_occupied = True
        return op

    def test_same_draw_can_continue_into_additional_time_without_expiry_streak(self):
        op = self.operator()
        for age in (2640, 5000, 5001, 9999):
            with self.subTest(age=age), patch("auto_operator.time.monotonic", return_value=10 + age / 1000):
                op.require_force_auto_click_budget(10 + (age - 314) / 1000,
                                                  phase="before_discard_click")
        self.assertEqual(getattr(op, "ranked_click_budget_expiry_streak", 0), 0)
        applied = [call for call in op.log.call_args_list
                   if call.args[0] == "force_auto_same_draw_grace_applied"]
        self.assertEqual(len(applied), 4)
        self.assertEqual(op.log.call_args.kwargs["effectiveActionBudgetMs"], 10000)
        extra = [call for call in op.log.call_args_list
                 if call.args[0] == "force_auto_same_draw_additional_time_used"]
        self.assertEqual([call.kwargs["actionEvidenceAgeMs"] for call in extra], [5001, 9999])
        self.assertTrue(all(call.kwargs["remainingGameExtraTimeMs"] is None for call in extra))

    def test_hard_expiry_still_stops_after_three_polls_of_one_draw(self):
        op = self.operator()
        with patch("auto_operator.time.monotonic", return_value=20.0):
            for _ in range(3):
                with self.assertRaises(RetryableSafetyAbort):
                    op.require_force_auto_click_budget(19.7, phase="before_recognition")
        self.assertEqual(op.ranked_click_budget_expiry_streak, 3)
        self.assertTrue(op.ranked_click_budget_safety_stop_requested)
        self.assertEqual(op.log.call_args.kwargs["effectiveActionBudgetMs"], 10000)

    def test_grace_never_extends_capture_freshness_or_another_draw(self):
        for change in ("capture", "draw", "empty", "uncertain", "missing_capture", "reaction", "win"):
            op = self.operator()
            capture = 12.9
            if change == "capture":
                capture = 10.4  # Exactly 2600ms old.
            elif change == "draw":
                op.screencast_draw_generation = 8
            elif change == "empty":
                op.screencast_draw_occupied = False
            elif change == "uncertain":
                op.selection_uncertainty_latch = {"drawGeneration": 7}
            elif change in {"reaction", "win"}:
                op.action_evidence_kind = change
            else:
                capture = None
            with self.subTest(change=change), patch("auto_operator.time.monotonic", return_value=13.0):
                with self.assertRaises(RetryableSafetyAbort):
                    op.require_force_auto_click_budget(capture, phase="before_discard_click")

    def test_first_selection_reserves_650ms_from_both_clocks(self):
        op = self.operator()
        with patch("auto_operator.time.monotonic", return_value=19.35):
            op.require_force_auto_discard_selection_window(19.2)
        with patch("auto_operator.time.monotonic", return_value=19.351):
            with self.assertRaises(RetryableSafetyAbort):
                op.require_force_auto_discard_selection_window(19.2)
        self.assertEqual(op.log.call_args.kwargs["effectiveActionBudgetMs"], 10000)
        with patch("auto_operator.time.monotonic", return_value=12.0):
            with self.assertRaises(RetryableSafetyAbort):
                op.require_force_auto_discard_selection_window(10.049)

    def test_long_friend_budget_is_not_extended(self):
        op = self.operator()
        op.args.force_auto_click_budget_ms = 8000
        with patch("auto_operator.time.monotonic", return_value=18.0):
            with self.assertRaises(RetryableSafetyAbort):
                op.require_force_auto_click_budget(17.9, phase="before_recognition")


class MetadataPriorityTest(unittest.TestCase):
    def test_full_ocr_yields_to_partial_retry_but_changed_scores_still_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Image.new("RGB", (1920, 1080), "black")
            changed = first.copy()
            ImageDraw.Draw(changed).rectangle((865, 373, 888, 470), fill="white")
            buffer = io.BytesIO()
            first.save(buffer, format="PNG")
            first_bytes = buffer.getvalue()
            path = Path(directory) / "latest.png"
            changed.save(path)
            op = PythonAutoOperator.__new__(PythonAutoOperator)
            op.args = argparse.Namespace(board_metadata=True)
            op.frames = Path(directory)
            op.log = Mock()
            op.board_metadata_thread = None
            op.board_metadata_result = None
            op.board_metadata_last_scan_at = 0.0
            op.board_metadata_lock = threading.Lock()
            op.board_metadata_ocr_lock = threading.Lock()
            scores = {seat: 25000 for seat in ("east", "south", "west", "north")}
            op.board_metadata_cache = {
                "capturedAt": 10.0, "signature": board_state_signature(first_bytes),
                "screenshot": "cached.png", "metadata": {
                    "verified": True, "round": "east_3", "seat": "west", "scores": scores,
                },
            }
            with patch("auto_operator.time.monotonic", return_value=11.0):
                with op.board_metadata_ocr_lock:
                    self.assertIsNone(op.cached_board_metadata(path))
                    self.assertIsNone(op.cached_board_metadata(path))
                self.assertTrue(op.board_metadata_partial_retry_pending)
                self.assertEqual(op.log.call_count, 1)  # Same miss is not flooded.
                with patch("auto_operator.threading.Thread") as worker:
                    op.schedule_board_metadata(path.read_bytes())
                    worker.assert_not_called()
                with patch("board_metadata.recognize_score", return_value=25000), \
                        patch("board_metadata.recognize_right_score", return_value=25000):
                    self.assertEqual(op.cached_board_metadata(path)["scores"], scores)
                self.assertFalse(op.board_metadata_partial_retry_pending)
                # A miss on another frame must not survive a memo cache hit.
                op.board_metadata_cache_miss("partial_ocr_lock_busy", retry_partial=True)
                self.assertTrue(op.board_metadata_partial_retry_pending)
                self.assertEqual(op.cached_board_metadata(path)["scores"], scores)
                self.assertFalse(op.board_metadata_partial_retry_pending)
                self.assertIsNone(op.board_metadata_cache_miss_reason)
                for new_score in (None, 24900):
                    op.board_metadata_frame_memo = None
                    with patch("board_metadata.recognize_score", return_value=new_score):
                        self.assertIsNone(op.cached_board_metadata(path))
                    self.assertFalse(op.board_metadata_partial_retry_pending)
                with patch("auto_operator.threading.Thread") as worker:
                    op.schedule_board_metadata(path.read_bytes())
                    worker.assert_called_once()
                # Round changes must never be accepted as turn highlights.
                ImageDraw.Draw(changed).rectangle((900, 385, 1020, 425), fill="white")
                changed.save(path)
                self.assertIsNone(op.cached_board_metadata(path))
                self.assertEqual(op.board_metadata_cache_miss_reason, "round_changed")


if __name__ == "__main__":
    unittest.main()
