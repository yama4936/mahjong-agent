"""Reconciliation may warm HUD metadata, never renew an old action clock."""
import argparse
import copy
from contextlib import ExitStack
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from auto_operator import PythonAutoOperator, RetryableSafetyAbort, load_json


class ReconciliationMetadataRefreshTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.now = 101.0
        clock = patch("auto_operator.time.monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        op = self.operator = PythonAutoOperator.__new__(PythonAutoOperator)
        op.args = argparse.Namespace(board_metadata=True, mode="force-auto",
                                    force_auto_click_budget_ms=2600, action_deadline_ms=300000)
        op.frames = self.directory
        op.action_evidence_started_at = 100.0
        op.action_budget_started_at = 100.0
        op.action_evidence_kind = "discard"
        op.action_budget_draw_generation = 4
        op.screencast_draw_generation = 4
        op.screencast_draw_occupied = True
        op.selection_uncertainty_latch = None
        op.dynamic_layout_required = False
        op.cached_open_melds = 0
        op.cached_board_metadata = Mock(return_value=None)
        op.poll_board_metadata = Mock()
        op.board_metadata_thread = None
        op.board_metadata_cache = None
        op.board_metadata_last_scan_at = 0
        op.board_metadata_last_scan_signature = None
        op.board_metadata_partial_retry_pending = False
        op.recognize_resident = Mock(return_value={"recognitionId": "same-frame-token"})
        op.poll_public_recognition = Mock()
        op.reconcile_own_discard = Mock()
        op.own_discard_reconciliation_pending = Mock(return_value=True)
        op.log = Mock()
        image = io.BytesIO()
        Image.new("RGB", (1920, 1080), (20, 40, 70)).save(image, "PNG")
        self.frame = self.directory / "immutable-frame.png"
        self.frame.write_bytes(image.getvalue())

    def stage(self, captured=None):
        return self.operator.stage_hand_during_discard_reconciliation(
            self.frame, self.now - .1 if captured is None else captured)

    def test_missing_or_expired_cache_queues_one_existing_async_worker(self):
        for cache in (None, {"capturedAt": 90.0}):
            with self.subTest(cache=cache), patch("auto_operator.threading.Thread") as thread:
                op = self.operator
                op.board_metadata_cache = cache
                op.board_metadata_thread = None
                op.board_metadata_last_scan_at = 0
                op.board_metadata_last_scan_signature = None
                thread.return_value.is_alive.return_value = True
                self.assertIsNone(self.stage())
                self.assertIsNone(self.stage())
                thread.assert_called_once()
                thread.return_value.start.assert_called_once()
                op.recognize_resident.assert_not_called()
                self.assertEqual(op.action_evidence_started_at, 100.0)
                self.assertEqual(op.action_budget_started_at, 100.0)

    def test_already_running_metadata_worker_is_never_duplicated(self):
        self.operator.board_metadata_thread = Mock()
        self.operator.board_metadata_thread.is_alive.return_value = True
        with patch("auto_operator.threading.Thread") as thread:
            self.assertIsNone(self.stage())
            thread.assert_not_called()
        self.operator.recognize_resident.assert_not_called()

    def test_metadata_refresh_alone_does_not_release_independent_river_wait(self):
        op = self.operator
        op.cached_board_metadata.return_value = {"round": "east_3"}
        self.assertIsNone(self.stage())
        op.recognize_resident.assert_called_once_with(
            self.frame, dynamic_layout=False, open_melds=None, stage_force_auto_recognition=True)
        op.poll_public_recognition.assert_called_once()
        op.reconcile_own_discard.assert_called_once()
        self.assertEqual(op.action_budget_started_at, 100.0)

    def test_confirmed_river_returns_staged_hand_without_refreshing_clocks(self):
        op = self.operator
        op.cached_board_metadata.return_value = {"round": "east_3"}
        op.own_discard_reconciliation_pending.return_value = False
        self.assertEqual(self.stage(), {"recognitionId": "same-frame-token"})
        self.assertEqual(op.action_evidence_started_at, 100.0)
        self.assertEqual(op.action_budget_started_at, 100.0)

    def test_late_fresh_frame_cannot_revive_expired_original_or_global_clock(self):
        for now, deadline in ((110.001, 300000), (102.501, 2500)):
            with self.subTest(now=now, deadline=deadline), \
                    patch.object(self.operator, "schedule_board_metadata") as schedule:
                self.now = now
                self.operator.args.action_deadline_ms = deadline
                self.operator.cached_board_metadata.return_value = {"round": "east_3"}
                self.assertIsNone(self.stage())
                schedule.assert_not_called()
                self.operator.recognize_resident.assert_not_called()
                with self.assertRaises(RetryableSafetyAbort):
                    if deadline == 2500:
                        self.operator.require_action_deadline()
                    else:
                        self.operator.require_force_auto_click_budget(self.now - .1, phase="before_recognition")
                self.assertEqual(self.operator.action_budget_started_at, 100.0)

    def test_staging_cost_is_charged_before_returning_completed_reconciliation(self):
        op = self.operator
        op.cached_board_metadata.return_value = {"round": "east_3"}
        op.own_discard_reconciliation_pending.return_value = False
        def expensive_stage(*_args, **_kwargs):
            self.now += 2.6
            return {"recognitionId": "too-late"}
        op.recognize_resident.side_effect = expensive_stage
        self.assertIsNone(self.stage())
        self.assertEqual(op.action_evidence_started_at, 100.0)

    def test_disabled_metadata_or_insufficient_image_window_never_queues(self):
        with patch.object(self.operator, "schedule_board_metadata") as schedule:
            self.operator.args.board_metadata = False
            self.assertIsNone(self.stage())
            self.operator.args.board_metadata = True
            self.assertIsNone(self.stage(captured=self.now - 2.5))
            schedule.assert_not_called()
            self.operator.recognize_resident.assert_not_called()

    def test_actual_run_reaches_metadata_queue_but_late_receipt_stops_at_original_guard(self):
        op = self.operator
        op.args.max_iterations = 2
        op.args.poll = 0
        op.args.stop_on_error = True
        op.layout = load_json(Path(__file__).resolve().parents[1] / "config/layout.json")
        op.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        op.action_clip = None
        op.screen_references = {}
        op.screencast_session = Mock()
        op.screencast_sequence = 1
        op.latest_screencast_frame = self.frame.read_bytes()
        op.latest_screencast_captured_at = self.now - .1
        op.rejected_screencast_size = None
        op.cached_public_observation = None
        op.previous_public_observation = None
        op.cached_concealed_tiles = None
        op.pending_post_call_discard = False
        op.pending_post_call_started_at = None
        op.restart_open_hand_probe_hash = None
        op.last_processed_hand = None
        op.armed = True
        op.last_shanten = 1
        op.round_terminal_latched = False
        op.action_evidence_last_seen_at = self.now - .1
        op.last_action_clicked_at = None
        op.login_button_clicked_at = None
        op.pending_own_discard = {"tile": "7p", "before": ["8p"]}
        op.pending_own_river_confirmation = ["8p", "7p"]
        for name in ("ensure_viewport", "start_screencast_gate", "schedule_periodic_public_recognition"):
            setattr(op, name, Mock())
        op.resume_if_away = Mock(return_value=False)
        op.advance_ranked_loop = Mock(return_value=False)
        op.schedule_public_recognition = Mock()
        op.schedule_board_metadata = Mock()
        def next_frame(_page):
            op.screencast_sequence += 1
            op.latest_screencast_captured_at = self.now - .1
            return False
        op.capture_self_win_result = Mock(side_effect=next_frame)
        page = Mock()
        page.url = "https://game.mahjongsoul.com/index.html"
        with ExitStack() as stack:
            stack.enter_context(patch("auto_operator.classify_screen", return_value=("match", 1)))
            stack.enter_context(patch("auto_operator.force_auto_call_buttons", return_value=[]))
            stack.enter_context(patch("auto_operator.force_auto_self_action_buttons", return_value=[]))
            stack.enter_context(patch("auto_operator.is_draw_slot_occupied", return_value=True))
            stack.enter_context(patch("auto_operator.geometric_open_meld_count", return_value=None))
            startup = stack.enter_context(patch("auto_operator.StartupTurnGuard"))
            startup.return_value.ready = True
            startup.return_value.quarantined = False
            startup.return_value.initial_action_anchor = None
            startup.return_value.observe.return_value = "ready"
            stage = stack.enter_context(patch.object(op, "stage_hand_during_discard_reconciliation",
                                                    wraps=op.stage_hand_during_discard_reconciliation))
            op.run(page)
            self.assertEqual(stage.call_count, 1)
            op.schedule_board_metadata.assert_called_once_with(self.frame.read_bytes())
            op.recognize_resident.assert_not_called()
            self.now = 110.01  # New image, same original action: no new allowance.
            stage.reset_mock()
            op.schedule_board_metadata.reset_mock()
            op.run(page)
            stage.assert_not_called()
            op.schedule_board_metadata.assert_not_called()
            self.assertTrue(any(call.args[0] == "recognition_deferred_stale_capture"
                                for call in op.log.call_args_list))
        page.mouse.click.assert_not_called()
        self.assertEqual(op.action_evidence_started_at, 100.0)
        self.assertEqual(op.action_budget_started_at, 100.0)


class RawOwnRiverDiagnosticTest(unittest.TestCase):
    def observation(self, river, captured, observed):
        return {"capturedAt": f"2026-10-29T23:44:{captured:02d}+00:00",
                "doraIndicators": ["3m"], "ownDiscards": list(river),
                "ownDiscardsObserved": observed, "ownMelds": [], "ownMeldsObserved": True,
                "opponentDiscards": [{"seat": seat, "discards": [], "discardsObserved": True,
                                      "melds": [], "meldsObserved": True}
                                     for seat in ("south", "west", "north")],
                "ownMeldTiles": [], "otherVisibleTiles": [], "acceptedTiles": 27,
                "detectedCandidates": 28}

    def test_partial_raw_river_is_logged_without_trusting_it_or_retiring_receipt(self):
        op = PythonAutoOperator.__new__(PythonAutoOperator)
        baseline = ["1m", "2p", "S", "1s", "8p"]
        candidate = [*baseline, "7p"]
        op.cached_public_observation = self.observation(baseline, 23, True)
        op.cached_open_melds = 0
        op.pending_own_discard = {"tile": "7p", "before": list(baseline), "clickedAt": "original-click"}
        op.pending_own_river_confirmation = list(candidate)
        op.observe_post_call_timeout_river = Mock()
        op.observe_uncertain_selection_river = Mock()
        op.log = Mock()
        for captured in (26, 27):
            current = self.observation(baseline[:4], captured, False)
            original = copy.deepcopy(current)
            op.accept_public_observation(current)
            self.assertEqual(current, original)
            self.assertEqual(op.cached_public_observation["ownDiscards"], baseline)
            self.assertEqual(op.pending_own_river_confirmation, candidate)
            self.assertEqual(op.pending_own_discard["tile"], "7p")
        events = [call for call in op.log.call_args_list
                  if call.args[0] == "own_discard_reconciliation_public_observation"]
        self.assertEqual(len(events), 1)  # Same missing observation is not spammed every capture.
        self.assertEqual(events[0].kwargs["rawOwnDiscards"], baseline[:4])
        self.assertFalse(events[0].kwargs["rawOwnDiscardsObserved"])
        self.assertEqual(events[0].kwargs["confirmationCandidate"], candidate)
        # Changing raw evidence/observed flag is independently visible, but
        # still cannot replace a retained, nonmatching river prefix.
        op.accept_public_observation(self.observation(["9p"], 28, True))
        events = [call for call in op.log.call_args_list
                  if call.args[0] == "own_discard_reconciliation_public_observation"]
        self.assertEqual(len(events), 2)
        self.assertEqual(op.cached_public_observation["ownDiscards"], baseline)
        op.accept_public_observation(self.observation(candidate, 29, True))
        self.assertIsNone(op.pending_own_river_confirmation)
        self.assertEqual(op.cached_public_observation["ownDiscards"], candidate)


if __name__ == "__main__":
    unittest.main()
