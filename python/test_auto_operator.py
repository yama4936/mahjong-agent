import io
import hashlib
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

import argparse
import tempfile
import json
import time
import threading
from datetime import datetime, timezone
from unittest.mock import Mock, call, patch

from auto_operator import PythonAutoOperator, RetryableSafetyAbort, SelectionStateUncertainAbort, action_deadline_timing, ambiguous_open_draw_fallback, away_resume_geometry, closed_concealed_row_visible, closed_hand_face_mismatches, confirmed_call_meld, crop_screenshot, crop_screenshot_regions, discard_point_in_hand_geometry, force_auto_call_buttons, force_auto_chi_choice_points, force_auto_reaction_win_button, force_auto_self_action_buttons, geometric_open_meld_count, is_away_resume_dialog, is_contextual_reaction_pass, is_draw_slot_occupied, is_force_auto_pass_prompt, load_json, load_secret_environment, local_discard_allowed, mean_pixel_delta, merge_public_observations, open_hand_draw_slot, own_meld_surface_visible, post_call_transition, raised_glyph_overlap_confirmation, raised_tile_confirmation_point, retreat_pointer_from_hand, riichi_selection_target_region, screencast_frame_follows_pointer_retreat, riichi_selection_is_visible, round_result_conflicts_with_live_table, selected_chi_choice_point, selected_open_draw_is_ambiguous, selected_tile_comparison_region, send_discard_click, should_guard_tenpai_reaction, should_process_reaction_prompt, should_retry_call_policy, stable_hand_comparison_region, stable_hand_delta, tile_face_structure_delta
from screen_state import classify_screen, load_references
from auto_operator import geometric_reaction_open_meld_count, draw_slots_occupied
from auto_operator import configure_evaluator_click_budget, with_match_length
from auto_operator import board_state_signature, board_state_signature_matches
from auto_operator import verified_post_call_white_discard

FRAME_FIXTURES = Path(__file__).resolve().parents[1] / "test/fixtures"


class ActionTemplatesArgumentTest(unittest.TestCase):
    def test_missing_path_is_rejected_and_existing_path_is_accepted(self):
        from auto_operator import parse_args

        base = ["auto_operator.py", "--layout", "layout.json", "--templates", "tiles",
                "--state", "state.json"]
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "actions"
            existing.mkdir()
            missing = Path(directory) / "missing"
            for value in (None, "", str(existing)):
                argv = base if value is None else base + ["--action-templates", value]
                with self.subTest(value=value), patch("sys.argv", argv):
                    self.assertEqual(parse_args().action_templates, value or "")
            stderr = io.StringIO()
            with patch("sys.argv", base + ["--action-templates", str(missing)]), \
                 patch("sys.stderr", stderr), self.assertRaises(SystemExit) as raised:
                parse_args()
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("--action-templates path does not exist", stderr.getvalue())
            self.assertIn(str(missing), stderr.getvalue())


class OperatorShutdownOrderTest(unittest.TestCase):
    def test_close_before_playwright_exit_on_normal_and_exception_paths(self):
        from auto_operator import main

        for failure in (None, RuntimeError("run failed"), KeyboardInterrupt()):
            with self.subTest(failure=failure):
                events = []
                lease = Mock()
                lease.__enter__ = Mock(return_value=None)
                lease.__exit__ = Mock(return_value=False)
                context = Mock()
                context.__enter__ = Mock(return_value=Mock())
                context.__exit__ = Mock(side_effect=lambda *args: events.append("playwright_exit"))
                operator = Mock()
                operator.run.side_effect = failure
                operator.close.side_effect = lambda: events.append("operator_close")
                with patch("auto_operator.parse_args", return_value=argparse.Namespace(cdp="endpoint")), \
                     patch("auto_operator.operator_lease", return_value=lease), \
                     patch("auto_operator.PythonAutoOperator", return_value=operator), \
                     patch("auto_operator.sync_playwright", return_value=context), \
                     patch("auto_operator.find_mahjong_page", return_value=Mock()):
                    if isinstance(failure, RuntimeError):
                        with self.assertRaisesRegex(RuntimeError, "run failed"):
                            main()
                    else:
                        self.assertEqual(main(), 0)
                self.assertEqual(events, ["operator_close", "playwright_exit"])
                operator.close.assert_called_once()

    def test_close_when_playwright_context_fails_to_enter(self):
        from auto_operator import main

        lease = Mock()
        lease.__enter__ = Mock(return_value=None)
        lease.__exit__ = Mock(return_value=False)
        context = Mock()
        context.__enter__ = Mock(side_effect=RuntimeError("driver unavailable"))
        context.__exit__ = Mock()
        operator = Mock()
        with patch("auto_operator.parse_args", return_value=argparse.Namespace(cdp="endpoint")), \
             patch("auto_operator.operator_lease", return_value=lease), \
             patch("auto_operator.PythonAutoOperator", return_value=operator), \
             patch("auto_operator.sync_playwright", return_value=context):
            with self.assertRaisesRegex(RuntimeError, "driver unavailable"):
                main()
        operator.close.assert_called_once()
        context.__exit__.assert_not_called()


class MatchLengthFlowTest(unittest.TestCase):
    def test_missing_current_wall_count_does_not_inherit_configured_value(self):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_state = {"seat": "north", "round": "east_1", "opponents": [],
                                 "remainingTiles": 55, "remaining_tiles": 56}
        operator.log = Mock()
        metadata = {"verified": True, "seat": "north", "round": "east_1",
                    "scores": {"north": 25000, "east": 25000, "south": 25000, "west": 25000},
                    "honba": 0, "riichiSticks": 0}
        state, _, _ = operator.frame_metadata_state(
            FRAME_FIXTURES / "black-client-20261021.png", prepared_metadata=metadata,
        )
        self.assertNotIn("remainingTiles", state)
        self.assertNotIn("remaining_tiles", state)
        state, _, _ = operator.frame_metadata_state(
            FRAME_FIXTURES / "black-client-20261021.png",
            prepared_metadata={**metadata, "remainingTiles": 0},
        )
        self.assertEqual(state["remainingTiles"], 0)
        self.assertNotIn("remaining_tiles", state)

    def test_explicit_format_survives_metadata_and_resident_requests(self):
        raw = {"seat": "north", "round": "unknown", "opponents": []}
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_state = with_match_length(raw, "east")
        operator.log = Mock()
        metadata = {"verified": True, "seat": "north", "round": "east_4",
                    "scores": {"north": 13700, "east": 17400, "south": 36100, "west": 32800},
                    "honba": 1, "riichiSticks": 0, "remainingTiles": 21}
        state, _, _ = operator.frame_metadata_state(
            FRAME_FIXTURES / "black-client-20261021.png", prepared_metadata=metadata,
        )
        self.assertEqual(state["matchLength"], "east")
        self.assertEqual(state["round"], "east_4")
        self.assertNotIn("matchLength", raw)
        self.assertEqual(with_match_length(raw, None), raw)
        with self.assertRaises(ValueError):
            with_match_length(raw, "unknown")
        for board_metadata, prepared in ((True, state), (False, None)):
            operator.args = argparse.Namespace(board_metadata=board_metadata, action_deadline_ms=300000)
            operator.recognition_server = Mock()
            operator.recognition_server.poll.return_value = None
            operator.recognition_server.stdin = io.StringIO()
            operator.recognition_server.stdout = io.StringIO(json.dumps({"id": 1, "result": {}}) + "\n")
            operator.recognition_request_id = 0
            operator.recognize_resident(Path("frame.jpg"), evaluate_force_auto=True, frame_public_state=prepared)
            request = json.loads(operator.recognition_server.stdin.getvalue())
            self.assertEqual(request["publicState"]["matchLength"], "east")

    def test_subprocess_evaluation_without_ocr_preserves_configured_format(self):
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.root = operator.frames = Path(directory)
            operator.state_path = operator.frames / "original.json"
            operator.state_path.write_text(json.dumps({"round": "east_4"}))
            operator.public_state = with_match_length({"round": "east_4"}, "east")
            operator.args = argparse.Namespace(mode="force-auto", board_metadata=False,
                                               match_length="east", action_templates="", evaluation_timeout=1)
            operator.layout_path = Path("layout.json")
            operator.templates = Path("templates")
            operator.evaluator_env = {}
            with patch("auto_operator.subprocess.run", return_value=Mock(returncode=0, stdout='{"status":"not_ready"}')) as run:
                operator.evaluate(Path("frame.jpg"))
            argument = next(x for x in run.call_args.args[0] if x.startswith("--state="))
            self.assertEqual(json.loads(Path(argument.split("=", 1)[1]).read_text())["matchLength"], "east")
            self.assertNotIn("matchLength", json.loads(operator.state_path.read_text()))


class RankedNavigationScopeTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.operator = PythonAutoOperator.__new__(PythonAutoOperator)
        self.operator.args = argparse.Namespace(ranked_loop=True)
        self.operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        self.operator.frames = Path(self.directory.name)
        self.operator.replays = Path(self.directory.name)
        self.operator.pending_round_replays = []
        self.operator.pending_match_replays = []
        self.operator.last_ranked_loop_state = None
        self.operator.last_ranked_loop_click_at = 0.0
        self.operator.log = Mock()
        self.page = Mock()

    def test_unfinished_match_never_sends_lobby_menu_or_room_clicks(self):
        # Recorded sequence: East2 draw -> five lobby clicks -> same match,
        # East2 honba1. A screen label cannot finish pending match evidence.
        self.operator.pending_match_replays = [Path("pending-match.json")]
        for state in ("lobby", "ranked_menu", "ranked_room"):
            with self.subTest(state=state):
                self.assertTrue(self.operator.advance_ranked_loop(self.page, state, 1.0))
                self.page.mouse.click.assert_not_called()

    def test_round_with_no_self_decisions_still_blocks_navigation(self):
        self.operator.attach_outcome("round", b"round-result", 1.0)
        self.assertTrue(self.operator.advance_ranked_loop(self.page, "lobby", 1.0))
        self.page.mouse.click.assert_not_called()

    def test_observed_table_before_first_self_decision_blocks_and_saves_frame(self):
        self.assertFalse(self.operator.handle_early_non_gameplay_screen(self.page, "match", 1.0))
        for _ in range(2):
            self.assertTrue(self.operator.handle_early_non_gameplay_screen(
                self.page, "lobby", 1.0, screenshot=b"observed-transition-frame",
            ))
        self.page.mouse.click.assert_not_called()
        snapshots = list(self.operator.frames.glob("*.ranked-navigation-deferred.png"))
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].read_bytes(), b"observed-transition-frame")

    def test_finished_match_old_table_does_not_block_next_queue_and_new_match(self):
        self.operator.attach_outcome("match", b"final-result", 1.0)
        self.operator.observe_ranked_match_screen("match")
        self.operator.attach_outcome("round", b"old-round-animation", 1.0)
        self.assertTrue(self.operator.advance_ranked_loop(self.page, "lobby", 1.0))
        self.assertTrue(self.operator.advance_ranked_loop(self.page, "ranked_menu", 1.0))
        self.assertTrue(self.operator.advance_ranked_loop(self.page, "ranked_room", 1.0))
        self.assertEqual(self.page.mouse.click.call_count, 3)
        # A queue cancellation before a new table must not inherit the old
        # round label and strand normal re-entry.
        self.assertTrue(self.operator.advance_ranked_loop(self.page, "lobby", 1.0))
        self.assertEqual(self.page.mouse.click.call_count, 4)
        self.operator.observe_ranked_match_screen("match")
        self.assertTrue(self.operator.advance_ranked_loop(self.page, "lobby", 1.0))
        self.assertEqual(self.page.mouse.click.call_count, 4)

    def test_native_match_attachment_releases_navigation_after_round(self):
        replay = self.operator.replays / "pending.json"
        replay.write_text(json.dumps({"id": "pending"}))
        self.operator.pending_match_replays = [replay]
        self.operator.pending_round_replays = [replay]
        self.operator.attach_outcome("round", b"round-result", 1.0)
        self.assertTrue(self.operator.advance_ranked_loop(self.page, "lobby", 1.0))
        self.page.mouse.click.assert_not_called()
        self.assertEqual(self.operator.attach_outcome("match", b"final-result", 1.0), 1)
        self.assertIn("match", json.loads(replay.read_text())["actualResult"])
        self.assertTrue(self.operator.advance_ranked_loop(self.page, "lobby", 1.0))
        self.page.mouse.click.assert_called_once_with(1390.08, 324.0)


class BlackScreenRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.operator = PythonAutoOperator.__new__(PythonAutoOperator)
        self.operator.args = argparse.Namespace(mode="force-auto")
        self.operator.frames = Path(self.directory.name)
        self.operator.log = Mock()
        self.operator.public_cache_generation = 7
        self.operator.cached_concealed_tiles = ["1m"] * 13
        self.operator.cached_public_observation = {"ownDiscards": ["9m"]}
        self.operator.board_metadata_cache = {"scores": {"east": 25000}}
        self.black = (FRAME_FIXTURES / "black-client-20261021.png").read_bytes()
        self.visible = (FRAME_FIXTURES / "client-startup-logo-20261021.png").read_bytes()
        self.page = Mock()

    def handle(self):
        return self.operator.handle_early_non_gameplay_screen(self.page, "black_screen", 1.0, self.black)

    def test_persistent_black_reloads_only_after_delay_and_fresh_confirmation(self):
        with patch("auto_operator.time.monotonic", return_value=100):
            self.assertTrue(self.handle())
        with patch("auto_operator.time.monotonic", return_value=114.999):
            self.assertTrue(self.handle())
        self.page.screenshot.assert_not_called()
        self.page.reload.assert_not_called()
        self.page.screenshot.side_effect = [self.black, self.visible]
        self.operator.screencast_session = object()
        lifecycle = Mock()
        self.operator.stop_screencast_gate = lifecycle.stop
        self.operator.start_screencast_gate = lifecycle.start
        lifecycle.attach_mock(self.page.reload, "reload")
        with patch("auto_operator.time.monotonic", return_value=115):
            self.assertTrue(self.handle())
        self.page.reload.assert_called_once_with(wait_until="domcontentloaded", timeout=20000)
        self.assertEqual(lifecycle.mock_calls, [call.stop(),
                         call.reload(wait_until="domcontentloaded", timeout=20000), call.start(self.page)])
        self.assertEqual(self.page.screenshot.call_args_list[-1], call())
        self.page.mouse.click.assert_not_called()
        self.assertEqual(self.operator.public_cache_generation, 8)
        for name in ("cached_concealed_tiles", "cached_public_observation", "board_metadata_cache",
                     "previous_public_observation", "pending_own_discard", "riichi_metadata_history"):
            self.assertIsNone(getattr(self.operator, name))
        self.assertEqual(self.operator.cached_open_melds, 0)
        self.assertTrue(self.operator.armed)
        observed = next(c.kwargs for c in self.operator.log.call_args_list
                        if c.args == ("black_screen_recovery_observed",))
        self.assertTrue(observed["cleared"])
        self.assertEqual(Path(observed["screenshot"]).read_bytes(), self.visible)

    def test_normal_frames_reset_the_timer_and_stale_black_never_reloads(self):
        with patch("auto_operator.time.monotonic", return_value=100):
            self.handle()
        self.assertFalse(self.operator.handle_early_non_gameplay_screen(self.page, "match", 1.0, self.visible))
        self.assertIsNone(self.operator.black_screen_seen_since)
        with patch("auto_operator.time.monotonic", return_value=200):
            self.handle()
        self.page.screenshot.return_value = self.visible
        with patch("auto_operator.time.monotonic", return_value=216):
            self.handle()
        self.page.reload.assert_not_called()
        self.assertEqual(self.operator.public_cache_generation, 7)
        self.assertIsNone(self.operator.black_screen_seen_since)

    def test_second_reload_is_held_with_evidence_but_window_expires(self):
        self.operator.black_screen_reload_attempts = [100]
        self.operator.black_screen_seen_since = 101
        self.page.screenshot.return_value = self.black
        with patch("auto_operator.time.monotonic", return_value=116):
            with self.assertRaisesRegex(RuntimeError, "one reload"):
                self.handle()
        stop = next(c.kwargs for c in self.operator.log.call_args_list
                    if c.args == ("black_screen_recovery_limit_stop",))
        self.assertEqual(Path(stop["screenshot"]).read_bytes(), self.black)
        self.page.reload.assert_not_called()
        self.operator.black_screen_seen_since = 780
        self.page.screenshot.side_effect = [self.black, self.visible]
        with patch("auto_operator.time.monotonic", return_value=800):
            self.handle()
        self.page.reload.assert_called_once()
        self.assertEqual(self.operator.black_screen_reload_attempts, [800])

    def test_observer_and_uncertain_frames_are_noninteractive(self):
        self.operator.black_screen_seen_since = 100
        for mode, confidence in (("observer", 1.0), ("force-auto", .9)):
            self.operator.args.mode = mode
            self.assertTrue(self.operator.handle_early_non_gameplay_screen(
                self.page, "black_screen", confidence, self.black))
        self.page.screenshot.assert_not_called()
        self.page.reload.assert_not_called()
        self.page.mouse.click.assert_not_called()
        self.assertIsNone(self.operator.black_screen_seen_since)

    def test_reloaded_lobby_requires_prior_outcome_before_a_new_ranked_queue(self):
        pending = [Path(self.directory.name) / "old-match-replay.json"]
        self.operator.pending_match_replays = pending
        self.operator.black_screen_recovery_pending_outcome = True
        self.operator.advance_ranked_loop = Mock()
        lobby = (FRAME_FIXTURES / "black-recovered-lobby-20261021.png").read_bytes()
        for now in (100, 101.999):
            with patch("auto_operator.time.monotonic", return_value=now):
                self.assertTrue(self.operator.handle_early_non_gameplay_screen(self.page, "lobby", 1.0, lobby))
        self.page.screenshot.assert_not_called()
        self.page.screenshot.return_value = lobby
        with patch("auto_operator.time.monotonic", return_value=102):
            with self.assertRaisesRegex(RuntimeError, "prior match result"):
                self.operator.handle_early_non_gameplay_screen(self.page, "lobby", 1.0, lobby)
        self.operator.advance_ranked_loop.assert_not_called()
        self.assertEqual(self.operator.pending_match_replays, pending)
        stop = next(c.kwargs for c in self.operator.log.call_args_list
                    if c.args == ("black_screen_outcome_missing_stop",))
        self.assertEqual(load_json(Path(stop["ledger"]))["pendingMatchReplays"], [str(pending[0])])
        self.assertEqual(Path(stop["screenshot"]).read_bytes(), lobby)

    def test_stale_lobby_cannot_stop_rejoining_match_or_already_attached_outcome(self):
        self.operator.pending_match_replays = [Path("old-match.json")]
        self.operator.black_screen_recovery_pending_outcome = True
        with patch("auto_operator.time.monotonic", return_value=100):
            self.assertTrue(self.operator.guard_black_recovery_outcome(self.page, "lobby"))
        self.page.screenshot.return_value = self.visible
        with patch("auto_operator.time.monotonic", return_value=103):
            self.assertTrue(self.operator.guard_black_recovery_outcome(self.page, "lobby"))
        self.assertFalse(self.operator.guard_black_recovery_outcome(self.page, "match"))
        self.assertFalse(self.operator.black_screen_recovery_pending_outcome)
        self.assertEqual(self.operator.pending_match_replays, [Path("old-match.json")])
        self.operator.black_screen_recovery_pending_outcome = True
        self.operator.pending_match_replays = []
        self.assertFalse(self.operator.guard_black_recovery_outcome(self.page, "lobby"))
        self.assertFalse(self.operator.black_screen_recovery_pending_outcome)


class ConnectionRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.operator = PythonAutoOperator.__new__(PythonAutoOperator)
        self.operator.args = argparse.Namespace(mode="force-auto")
        self.operator.frames = Path(self.directory.name)
        self.operator.log = Mock()
        self.operator.cached_concealed_tiles = ["1m"] * 13
        self.operator.cached_public_observation = {"ownDiscards": ["9m"]}
        self.operator.previous_public_observation = {"ownDiscards": []}
        self.operator.pending_own_discard = {"tile": "9m"}
        self.operator.pending_own_river_confirmation = ["9m"]
        self.operator.public_cache_generation = 7
        self.operator.board_metadata_cache = {"scores": {"east": 25000}}
        root = Path(__file__).resolve().parents[1] / "artifacts/live"
        self.error = (root / "connection-error-over-result-20261021.jpg").read_bytes()
        self.result = (root / "connection-recovered-result-20261021.jpg").read_bytes()
        self.conflict = (root / "session-conflict.png").read_bytes()
        self.page = Mock()

    def handle(self):
        return self.operator.handle_early_non_gameplay_screen(
            self.page, "connection_error", 1.0, self.error,
        )

    def test_confirmation_clears_message_and_invalidates_pre_disconnect_evidence(self):
        self.page.screenshot.side_effect = [self.error, self.result]
        self.assertTrue(self.handle())
        self.page.mouse.click.assert_called_once_with(960.0, 690.12)
        for name in ("cached_concealed_tiles", "cached_public_observation", "previous_public_observation",
                     "pending_own_discard", "pending_own_river_confirmation", "board_metadata_cache",
                     "last_processed_hand"):
            self.assertIsNone(getattr(self.operator, name), name)
        self.assertEqual(self.operator.public_cache_generation, 8)
        self.assertTrue(self.operator.armed)
        observed = next(c.kwargs for c in self.operator.log.call_args_list
                        if c.args == ("connection_recovery_observed",))
        self.assertTrue(observed["cleared"])
        self.assertEqual(observed["state"], "match_result")
        self.assertEqual(Path(observed["screenshot"]).read_bytes(), self.result)
        self.assertEqual(len(list(self.operator.frames.glob("*.png"))), 2)

    def test_stale_overlay_cannot_click_result_or_session_conflict(self):
        for fresh in (self.result, self.conflict):
            with self.subTest(fresh=fresh[:8]):
                self.page.screenshot.side_effect = None
                self.page.screenshot.return_value = fresh
                self.assertTrue(self.handle())
        self.page.mouse.click.assert_not_called()
        self.assertFalse(hasattr(self.operator, "connection_error_attempts"))
        self.assertEqual(self.operator.public_cache_generation, 7)

    def test_persistent_error_is_bounded_and_held_after_three_attempts(self):
        self.page.screenshot.return_value = self.error
        with patch("auto_operator.time.monotonic", side_effect=[100, 106, 112, 118]):
            for _ in range(3):
                self.assertTrue(self.handle())
            with self.assertRaisesRegex(RuntimeError, "three confirmations"):
                self.handle()
        self.assertEqual(self.page.mouse.click.call_count, 3)
        stops = [c for c in self.operator.log.call_args_list if c.args == ("connection_recovery_limit_stop",)]
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0].kwargs["attempts"], 3)
        self.assertTrue(Path(stops[0].kwargs["screenshot"]).exists())

    def test_retry_backoff_and_rolling_window(self):
        self.page.screenshot.return_value = self.error
        self.operator.connection_error_attempts = [100, 106, 112]
        with patch("auto_operator.time.monotonic", return_value=114):
            self.assertTrue(self.handle())
        self.page.mouse.click.assert_not_called()
        with patch("auto_operator.time.monotonic", return_value=800):
            self.assertTrue(self.handle())
        self.page.mouse.click.assert_called_once()
        self.assertEqual(self.operator.connection_error_attempts, [800])

    def test_observer_and_uncertain_detection_remain_noninteractive(self):
        for mode, confidence in (("observer", 1.0), ("force-auto", .9)):
            with self.subTest(mode=mode, confidence=confidence):
                self.operator.args.mode = mode
                with self.assertRaisesRegex(RuntimeError, "connection_error dialog blocks"):
                    self.operator.handle_early_non_gameplay_screen(
                        self.page, "connection_error", confidence, self.error,
                    )
        self.page.mouse.click.assert_not_called()
        self.page.screenshot.assert_not_called()


class ResidentPublicRecognitionTest(unittest.TestCase):
    def operator(self):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_recognition_io_lock = threading.Lock()
        operator.public_recognition_request_id = 0
        operator.public_recognition_server = Mock()
        operator.public_recognition_server.poll.return_value = None
        operator.args = argparse.Namespace(mode="force-auto")
        operator.public_state = {"seat": "north"}
        operator.log = Mock()
        return operator

    def test_reaction_uses_exact_prompt_and_seat_without_starting_cli(self):
        operator = self.operator()
        result = {"ownDiscards": ["1m"], "highlightedDiscard": {"tile": "3p", "fromSeat": "west"}}
        operator.public_recognition_server.stdout.readline.return_value = json.dumps({"id": 1, "result": result})
        with patch("auto_operator.subprocess.run", side_effect=AssertionError("cold CLI")):
            self.assertEqual(operator.observe_public_board(Path("prompt.png"), reaction_highlight=True), result)
        sent = json.loads(operator.public_recognition_server.stdin.write.call_args.args[0])
        self.assertEqual(sent, {"id": 1, "screenshot": "prompt.png", "reactionHighlight": True, "observationSeat": "north"})
        self.assertNotIn("concealedTiles", sent)  # Prompt requests must not wait for a new hand plan.

    def test_reaction_rejects_wrong_response_instead_of_using_cache(self):
        operator = self.operator()
        operator.cached_public_observation = {"ownDiscards": ["9m"]}
        operator.public_recognition_server.stdout.readline.return_value = json.dumps({"id": 99, "result": {}})
        self.assertIsNone(operator.observe_public_board(Path("prompt.png"), reaction_highlight=True))
        self.assertIn("id mismatch", operator.log.call_args.kwargs["error"])

    def test_reaction_context_overlaps_all_three_same_frame_observations(self):
        operator = self.operator()
        barrier = threading.Barrier(3, timeout=2)
        frame = Path("immutable-prompt.png")
        def observe(path, result):
            self.assertEqual(path, frame)
            barrier.wait()
            return result
        operator.observe_public_board = Mock(side_effect=lambda path, **kw: observe(path, {"ownDiscards": []}))
        operator.recognize_reaction_hand = Mock(side_effect=lambda path: observe(path, {"tiles": ["1m"] * 13}))
        operator.current_board_metadata = Mock(side_effect=lambda path: observe(path, {"verified": True}))
        self.assertEqual(operator.recognize_reaction_context(frame),
                         ({"ownDiscards": []}, {"tiles": ["1m"] * 13}, {"verified": True}))
        operator.recognize_reaction_hand.side_effect = RuntimeError("hand failure")
        operator.observe_public_board.side_effect = None
        operator.current_board_metadata.side_effect = None
        with self.assertRaisesRegex(RuntimeError, "hand failure"):
            operator.recognize_reaction_context(frame)

    def test_prepared_metadata_does_not_bypass_verification(self):
        operator = self.operator()
        operator.current_board_metadata = Mock(side_effect=AssertionError("duplicate OCR"))
        with self.assertRaisesRegex(RetryableSafetyAbort, "board metadata not verified"):
            operator.frame_metadata_state(Path("prompt.png"), prepared_metadata={"verified": False, "reason": "uncertain"})

    def test_reaction_cli_decision_budget_ages_original_prompt(self):
        operator = self.operator()
        operator.args = argparse.Namespace(mode="force-auto", board_metadata=False,
                                           action_templates=None, evaluation_timeout=5,
                                           force_auto_click_budget_ms=2600)
        operator.state_path = Path("state.json")
        operator.layout_path = Path("layout.json")
        operator.templates = Path("templates")
        operator.root = Path(".")
        operator.evaluator_env = {"JEV_FORCE_AUTO_DEADLINE_MS": "2300"}
        with patch("auto_operator.time.monotonic", return_value=11.9), \
             patch("auto_operator.subprocess.run", return_value=argparse.Namespace(returncode=0, stdout="{}")) as run:
            operator.evaluate(Path("prompt.png"), captured_at=10.0)
        self.assertEqual(run.call_args.kwargs["env"]["JEV_FORCE_AUTO_DEADLINE_MS"], "50")
        self.assertEqual(operator.evaluator_env["JEV_FORCE_AUTO_DEADLINE_MS"], "2300")

    def test_background_and_prompt_exchanges_cannot_steal_responses(self):
        operator = self.operator()
        written = []
        first_read = threading.Event()
        release = threading.Event()
        second_started = threading.Event()
        results = {}
        failures = []
        def write(line):
            written.append(json.loads(line))
        def read():
            if len(written) == 1:
                first_read.set()
                if not release.wait(2):
                    raise RuntimeError("test release timeout")
            request = written[-1]
            return json.dumps({"id": request["id"], "result": {"frame": request["screenshot"]}})
        operator.public_recognition_server.stdin.write.side_effect = write
        operator.public_recognition_server.stdout.readline.side_effect = read
        def request(i):
            if i == 2:
                second_started.set()
            try:
                results[i] = operator.request_public_recognition({"id": i, "screenshot": f"frame-{i}.png"})
            except Exception as error:
                failures.append(error)
        first = threading.Thread(target=request, args=(1,))
        second = threading.Thread(target=request, args=(2,))
        first.start()
        self.assertTrue(first_read.wait(2))
        second.start()
        self.assertTrue(second_started.wait(2))
        try:
            time.sleep(0.02)
            self.assertEqual(len(written), 1)
        finally:
            release.set()
            first.join(2)
            second.join(2)
        self.assertFalse(failures)
        self.assertEqual(results, {1: {"frame": "frame-1.png"}, 2: {"frame": "frame-2.png"}})


class EvaluatorClickBudgetTest(unittest.TestCase):
    def test_crop_screenshot_regions_decodes_source_once_and_matches_individual_crops(self):
        image = Image.new("RGB", (40, 30), "black")
        ImageDraw.Draw(image).rectangle((10, 5, 29, 24), fill="white")
        encoded = io.BytesIO()
        image.save(encoded, format="PNG")
        screenshot = encoded.getvalue()
        clips = {
            "hand": {"x": 0, "y": 0, "width": 20, "height": 20},
            "river": {"x": 10, "y": 5, "width": 20, "height": 20},
        }

        with patch("auto_operator.Image.open", wraps=Image.open) as opened:
            actual = crop_screenshot_regions(screenshot, clips)

        self.assertEqual(opened.call_count, 1)
        for name, clip in clips.items():
            with Image.open(io.BytesIO(actual[name])) as batched, \
                    Image.open(io.BytesIO(crop_screenshot(screenshot, clip))) as individual:
                self.assertEqual(batched.size, individual.size)
                self.assertEqual(batched.mode, individual.mode)
                self.assertEqual(batched.tobytes(), individual.tobytes())

    def test_only_a_screencast_frame_after_pointer_retreat_can_skip_fresh_capture(self):
        self.assertTrue(screencast_frame_follows_pointer_retreat(18, 17))
        self.assertFalse(screencast_frame_follows_pointer_retreat(17, 17))
        self.assertFalse(screencast_frame_follows_pointer_retreat(None, 17))
        self.assertFalse(screencast_frame_follows_pointer_retreat(18, None))

    def test_live_open_hand_vetoes_round_result_transition(self):
        project = Path(__file__).resolve().parents[1]
        frame = (project / "artifacts/friend-300-eaacede-room73637-20261011/frames/2026-10-11T08-17-50.273158+00-00.round_result.png").read_bytes()
        layout = load_json(project / "config/layout-300-regression.json")
        self.assertEqual(
            round_result_conflicts_with_live_table(frame, layout),
            {"kind": "open_hand_geometry", "openMelds": 1, "selfDrawVisible": True},
        )
        actual_result = (project / "artifacts/live/round-result.png").read_bytes()
        self.assertIsNone(round_result_conflicts_with_live_table(actual_result, layout))

    def test_ambiguous_open_draw_slot_is_not_an_auto_discard_target(self):
        evaluation = {"openMelds": 1, "clickIndex": 10,
                      "recognition": {"tiles": ["1m"] * 11, "confidence": 0.60,
                                      "ambiguityMargin": 0.003}}
        self.assertTrue(selected_open_draw_is_ambiguous(evaluation))
        evaluation["recognition"] = {"tiles": ["1m"] * 11, "confidence": 0.91,
                                      "ambiguityMargin": 0.12}
        self.assertFalse(selected_open_draw_is_ambiguous(evaluation))

    def test_ambiguous_open_draw_fallback_uses_best_compact_row_candidate(self):
        evaluation = {"recognition": {"tiles": ["7m", "8m", "1p", "1m"]},
                      "decision": {"candidates": [
                          {"action": "discard", "tile": "1m"},
                          {"action": "discard", "tile": "8m"},
                      ]}}
        self.assertEqual(ambiguous_open_draw_fallback(evaluation), ("8m", 1))

    def test_selected_open_tile_uses_its_own_match_and_strict_consensus(self):
        evaluation = {"openMelds": 2, "clickIndex": 7,
                      "recognition": {"tiles": ["2m", "2m", "4m", "0m", "0s", "5s", "5s", "W"],
                                      "confidence": 0.71578, "ambiguityMargin": 0.14912},
                      "selectedTileRecognition": {"index": 7, "tile": "W", "confidence": 0.94569,
                                                  "runnerUpConfidence": 0.58348}}
        self.assertFalse(selected_open_draw_is_ambiguous(evaluation))
        evaluation["recognition"]["tiles"][-1] = "9p"
        selected = {"index": 7, "tile": "9p", "confidence": 0.73133, "runnerUpConfidence": 0.39543}
        evaluation["selectedTileRecognition"] = selected
        self.assertTrue(selected_open_draw_is_ambiguous(evaluation))
        selected["normalizedConsensus"] = {"tile": "9p", "confidence": 0.95984, "runnerUpConfidence": 0.38676}
        self.assertFalse(selected_open_draw_is_ambiguous(evaluation))
        for invalid in ({"tile": "8p", "confidence": 0.99, "runnerUpConfidence": 0.3},
                        {"tile": "9p", "confidence": 0.949, "runnerUpConfidence": 0.3},
                        {"tile": "9p", "confidence": 0.96, "runnerUpConfidence": 0.82}, {}):
            selected["normalizedConsensus"] = invalid
            self.assertTrue(selected_open_draw_is_ambiguous(evaluation))

    def test_original_low_confidence_wrong_draw_cannot_be_promoted(self):
        evaluation = {"openMelds": 1, "clickIndex": 10,
                      "recognition": {"tiles": ["7m"] * 10 + ["1m"], "confidence": 0.60364,
                                      "ambiguityMargin": 0.00283},
                      "selectedTileRecognition": {"index": 10, "tile": "1m", "confidence": 0.60364,
                          "runnerUpConfidence": 0.60081, "normalizedConsensus": {
                              "tile": "1m", "confidence": 0.99, "runnerUpConfidence": 0.1}}}
        self.assertTrue(selected_open_draw_is_ambiguous(evaluation))
        evaluation["selectedTileRecognition"] = {"index": 9, "tile": "1m", "confidence": 0.99,
                                                 "runnerUpConfidence": 0.1}
        self.assertTrue(selected_open_draw_is_ambiguous(evaluation))

    def test_call_tile_count_conflict_retries_and_unexpected_errors_propagate(self):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_state = {"seat": "north"}
        operator.cached_public_observation = operator.previous_public_observation = None
        operator.cached_open_melds = 0
        operator.log = Mock()
        operator.observe_public_board = Mock(return_value={
            "highlightedDiscard": {"tile": "2s", "fromSeat": "west"},
            "opponentDiscards": [{"seat": "west", "discards": ["P", "2s"]}]})
        operator.recognize_reaction_hand = Mock(return_value={"tiles": ["1m"] * 13})
        operator.evaluate = Mock()
        for message in ["More than four copies of 9m",
                        "(node:33648) ExperimentalWarning: Importing JSON modules\nMore than four copies of 9m\n",
                        "More than four copies of F"]:
            with self.subTest(message=message):
                operator.evaluate.side_effect = RuntimeError(message)
                with self.assertRaisesRegex(RetryableSafetyAbort, "reaction_tile_count_conflict"):
                    operator.evaluate_force_auto_call_policy(Path("prompt.png"), "chi")
        for message in ["unexpected evaluator failure", "More than four copies of 0m",
                        "prefix More than four copies of 9m suffix"]:
            with self.subTest(message=message):
                operator.evaluate.side_effect = RuntimeError(message)
                with self.assertRaises(RuntimeError) as caught:
                    operator.evaluate_force_auto_call_policy(Path("prompt.png"), "chi")
                self.assertNotIsInstance(caught.exception, RetryableSafetyAbort)
        approved = {"status": "decision", "decision": {
            "selectedAction": {"id": "chi_2s", "action": "chi"},
            "callAssessments": [{"actionId": "chi_2s", "approved": True}]}}
        operator.evaluate.side_effect = None
        operator.evaluate.return_value = approved
        self.assertEqual(operator.evaluate_force_auto_call_policy(Path("next.png"), "chi"), approved)

    def test_verified_highlight_still_requires_strategy_approval(self):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_state = {"seat": "north"}
        operator.cached_public_observation = operator.previous_public_observation = None
        operator.cached_open_melds = 0
        operator.log = Mock()
        operator.observe_public_board = Mock(return_value={
            "highlightedDiscard": {"tile": "2s", "fromSeat": "west"},
            "opponentDiscards": [{"seat": "west", "discards": ["P", "2s"]}]})
        operator.recognize_reaction_hand = Mock(return_value={"tiles": ["1m"] * 13})
        approved = {"status": "decision", "decision": {
            "selectedAction": {"id": "chi_2s", "action": "chi"},
            "callAssessments": [{"actionId": "chi_2s", "approved": True}]}}
        operator.evaluate = Mock(return_value=approved)
        self.assertEqual(operator.evaluate_force_auto_call_policy(Path("prompt.png"), "chi"), approved)
        self.assertEqual(operator.evaluate.call_args.args[1], {"tile": "2s", "fromSeat": "west"})
        approved["decision"]["callAssessments"][0]["approved"] = False
        self.assertIsNone(operator.evaluate_force_auto_call_policy(Path("prompt.png"), "chi"))
        current = operator.observe_public_board.return_value
        current["opponentDiscards"].append({"seat": "east", "discards": ["W", "1m"]})
        operator.cached_public_observation = {"opponentDiscards": [
            {"seat": "west", "discards": ["P", "2s"]}, {"seat": "east", "discards": ["W"]}]}
        operator.evaluate.reset_mock()
        self.assertIsNone(operator.evaluate_force_auto_call_policy(Path("prompt.png"), "chi"))
        operator.evaluate.assert_not_called()
        self.assertEqual(operator.log.call_args.kwargs["reason"], "river_history_and_highlight_conflict")

    def test_prompt_highlight_requires_last_tile_correct_chi_seat_and_supported_action(self):
        observation = {"highlightedDiscard": {"tile": "2s", "fromSeat": "west"},
                       "opponentDiscards": [{"seat": "west", "discards": ["P", "2s"]}]}
        self.assertEqual(PythonAutoOperator.pending_highlighted_discard(observation, "chi", "north"),
                         {"tile": "2s", "fromSeat": "west"})
        self.assertIsNone(PythonAutoOperator.pending_highlighted_discard(observation, "chi", "east"))
        self.assertIsNone(PythonAutoOperator.pending_highlighted_discard(observation, "ron", "north"))
        observation["opponentDiscards"][0]["discards"].append("N")
        self.assertIsNone(PythonAutoOperator.pending_highlighted_discard(observation, "pon", "north"))

    def test_pass_confirmation_requires_new_self_draw_when_button_pixels_stay_same(self):
        root = Path(__file__).resolve().parents[1]
        reaction = (root / "artifacts/live/pass-before-self-riichi-20260928.png").read_bytes()
        self_turn = (root / "artifacts/live/pass-to-self-riichi-20260928.png").read_bytes()
        buffer = io.BytesIO()
        Image.new("RGB", (100, 40), "black").save(buffer, format="PNG")
        unchanged_button = buffer.getvalue()
        for prior, current, accepted in [(reaction, self_turn, True),
                                         (reaction, reaction, False),
                                         (self_turn, self_turn, False)]:
            with self.subTest(accepted=accepted, already_self_turn=prior == self_turn):
                operator = PythonAutoOperator.__new__(PythonAutoOperator)
                operator.layout = load_json(root / "config/layout.json")
                operator.layout["actionButtonRegions"] = {
                    "pass": {"x": 10, "y": 20, "width": 100, "height": 40}}
                operator.args = argparse.Namespace(
                    confirmation_timeout=0.02, action_pixel_delta=3, river_pixel_delta=1,
                )
                page = Mock()
                page.screenshot.side_effect = lambda **kwargs: unchanged_button if "clip" in kwargs else current
                if accepted:
                    receipt = operator.confirm_action_button(page, "pass", unchanged_button, screen_before=prior)
                    self.assertEqual(receipt["confirmation"], "reaction_to_self_draw")
                    self.assertEqual(receipt["buttonPixelDelta"], 0)
                else:
                    with self.assertRaisesRegex(RuntimeError, "not confirmed"):
                        operator.confirm_action_button(page, "pass", unchanged_button, screen_before=prior)

    def test_pass_confirmation_accepts_independent_river_advance(self):
        root = Path(__file__).resolve().parents[1]
        reaction = (root / "artifacts/live/pass-before-self-riichi-20260928.png").read_bytes()
        layout = load_json(root / "config/layout.json")
        changed = Image.open(io.BytesIO(reaction)).convert("RGB")
        river = layout["publicTileRegions"]["ownDiscards"]
        ImageDraw.Draw(changed).rectangle((
            river["x"], river["y"], river["x"] + river["width"], river["y"] + river["height"],
        ), fill="white")
        changed_bytes = io.BytesIO()
        changed.save(changed_bytes, format="PNG")
        button = io.BytesIO()
        Image.new("RGB", (100, 40), "black").save(button, format="PNG")
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = layout
        operator.layout["actionButtonRegions"] = {
            "pass": {"x": 10, "y": 20, "width": 100, "height": 40},
        }
        operator.args = argparse.Namespace(
            confirmation_timeout=0.1, action_pixel_delta=3, river_pixel_delta=1,
        )
        operator.cached_open_melds = 0
        page = Mock()
        page.screenshot.side_effect = lambda **kwargs: (
            button.getvalue() if "clip" in kwargs else changed_bytes.getvalue()
        )

        receipt = operator.confirm_action_button(
            page, "pass", button.getvalue(), screen_before=reaction,
        )

        self.assertEqual(receipt["confirmation"], "reaction_river_advanced")
        self.assertEqual(receipt["riverRegion"], "ownDiscards")

    def test_own_discard_mismatch_requires_temporal_confirmation_before_quarantine(self):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.pending_own_discard = {
            "tile": "W", "before": ["1m", "2m"], "evidenceToClickMs": 6701,
            "clickIndex": 4, "clickPoint": {"x": 555, "y": 999},
            "clickedAt": "2026-10-03T00:00:00+00:00", "confirmation": "hand_and_own_river_changed",
        }
        operator.cached_concealed_tiles = ["1p"] * 13
        operator.cached_public_observation = {
            "ownDiscards": ["1m", "2m", "3p"],
            "capturedAt": "2026-10-03T00:00:01+00:00",
            "doraIndicators": ["4m"],
            "opponentDiscards": [{"seat": "south", "discards": ["9s"]}],
        }
        operator.pending_own_river_confirmation = ["1m", "2m", "3p"]
        operator.log = Mock()

        operator.reconcile_own_discard()

        self.assertEqual(operator.cached_concealed_tiles, ["1p"] * 13)
        self.assertIsNotNone(operator.pending_own_discard)
        self.assertEqual(operator.pending_own_river_confirmation, ["1m", "2m", "3p"])
        operator.log.assert_called_once_with(
            "own_discard_mismatch_pending", expected="W", actual="3p", before=["1m", "2m"],
            observed=["1m", "2m", "3p"], capturedAt="2026-10-03T00:00:01+00:00",
            clickIndex=4, clickPoint={"x": 555, "y": 999},
            clickedAt="2026-10-03T00:00:00+00:00", confirmation="hand_and_own_river_changed",
        )

        operator.cached_public_observation["capturedAt"] = "2026-10-03T00:00:02+00:00"
        operator.reconcile_own_discard()

        self.assertIsNone(operator.cached_concealed_tiles)
        self.assertIsNotNone(operator.pending_own_discard)
        self.assertEqual(operator.pending_own_river_confirmation, ["1m", "2m", "3p"])
        self.assertTrue(operator.own_discard_reconciliation_pending())
        self.assertEqual(operator.cached_public_observation["ownDiscards"], ["1m", "2m"])
        self.assertEqual(operator.cached_public_observation["doraIndicators"], ["4m"])
        self.assertEqual(operator.cached_public_observation["opponentDiscards"],
                         [{"seat": "south", "discards": ["9s"]}])
        operator.log.assert_any_call(
            "own_discard_mismatch", expected="W", actual="3p", evidenceToClickMs=6701,
            before=["1m", "2m"], observed=["1m", "2m", "3p"],
            capturedAt="2026-10-03T00:00:02+00:00",
            clickIndex=4, clickPoint={"x": 555, "y": 999},
            clickedAt="2026-10-03T00:00:00+00:00", confirmation="hand_and_own_river_changed",
        )
        operator.log.assert_any_call(
            "own_discard_mismatch_cache_quarantined", expected="W", rejected="3p",
            retainedOwnDiscards=["1m", "2m"],
        )

    def test_delayed_prior_append_followed_by_expected_discard_is_not_mismatch(self):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.pending_own_discard = {
            "tile": "E", "before": ["1m", "2m"], "clickIndex": 12,
            "clickPoint": {"x": 1407.5, "y": 999}, "clickedAt": "when",
            "confirmation": "hand_and_own_river_changed",
        }
        operator.cached_concealed_tiles = ["1p"] * 13
        operator.cached_public_observation = {
            "ownDiscards": ["1m", "2m", "7m"], "capturedAt": "2026-10-03T00:00:01+00:00",
        }
        operator.pending_own_river_confirmation = None
        operator.log = Mock()

        operator.reconcile_own_discard()
        self.assertTrue(operator.own_discard_reconciliation_pending())
        self.assertIsNotNone(operator.pending_own_discard)

        operator.cached_public_observation = {
            "ownDiscards": ["1m", "2m", "7m", "E"],
            "capturedAt": "2026-10-03T00:00:02+00:00",
        }
        operator.reconcile_own_discard()

        self.assertIsNone(operator.pending_own_discard)
        self.assertIsNone(operator.pending_own_river_confirmation)
        self.assertIsNone(operator.cached_concealed_tiles)
        operator.log.assert_any_call(
            "own_discard_reconciled_after_delayed_prior_append", tile="E", delayedPriorAppend="7m",
            before=["1m", "2m"], observed=["1m", "2m", "7m", "E"],
            firstCapturedAt="2026-10-03T00:00:01+00:00",
            confirmedCapturedAt="2026-10-03T00:00:02+00:00", concealedCacheInvalidated=True,
        )
        self.assertFalse(any(call.args[0] == "own_discard_mismatch"
                             for call in operator.log.call_args_list))

    def test_reconciliation_failure_records_click_receipt(self):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.pending_own_discard = {
            "tile": "W", "before": ["1m"], "clickIndex": 2,
            "clickPoint": {"x": 363.5, "y": 999}, "clickedAt": "when",
            "confirmation": "hand_and_own_river_changed",
        }
        operator.cached_concealed_tiles = ["1p"] * 13
        operator.cached_public_observation = {"ownDiscards": ["1m", "2m", "3p"]}
        operator.log = Mock()

        operator.reconcile_own_discard()

        operator.log.assert_called_once_with(
            "own_discard_reconciliation_failed", expected="W", before=["1m"],
            observed=["1m", "2m", "3p"], reason="river_history_not_single_append",
            clickIndex=2, clickPoint={"x": 363.5, "y": 999}, clickedAt="when",
            confirmation="hand_and_own_river_changed",
        )

    def test_force_auto_friend_match_result_stops_without_screen_advance(self):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", ranked_loop=False, advance_screens=False)

        self.assertTrue(operator.should_stop_after_match_result("match_result"))

    def test_ranked_or_non_force_auto_match_result_does_not_use_friend_stop(self):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", ranked_loop=True)
        self.assertFalse(operator.should_stop_after_match_result("match_result"))
        operator.args = argparse.Namespace(mode="auto", ranked_loop=False)
        self.assertFalse(operator.should_stop_after_match_result("match_result"))
        operator.args = argparse.Namespace(mode="force-auto", ranked_loop=False)
        self.assertFalse(operator.should_stop_after_match_result("round_result"))

    def test_matching_own_discard_keeps_concealed_cache(self):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        cached = ["1p"] * 13
        operator.pending_own_discard = {
            "tile": "W", "before": ["1m", "2m"], "evidenceToClickMs": 2200,
        }
        operator.cached_concealed_tiles = cached
        operator.cached_public_observation = {"ownDiscards": ["1m", "2m", "W"]}
        operator.log = Mock()

        operator.reconcile_own_discard()

        self.assertIs(operator.cached_concealed_tiles, cached)
        self.assertIsNone(operator.pending_own_discard)
        operator.log.assert_called_once_with("own_discard_reconciled", tile="W")

    def test_riichi_discard_reconciles_exact_prefix_after_automatic_discards(self):
        for case in ("valid", "ordinary", "unverified_riichi", "wrong_first", "changed_prefix"):
            with self.subTest(case=case):
                operator = PythonAutoOperator.__new__(PythonAutoOperator)
                operator.pending_own_discard = {"tile": "F", "before": ["8s"],
                    "riichiDeclaration": case != "ordinary"}
                after = ["8s", "F", "4m", "5p"]
                if case == "wrong_first":
                    after = ["8s", "4m", "F", "5p"]
                if case == "changed_prefix":
                    after = ["7s", "F", "4m", "5p"]
                operator.cached_public_observation = {"ownDiscards": after,
                    "ownRiichiDeclared": case != "unverified_riichi"}
                operator.cached_concealed_tiles = ["1p"] * 13
                operator.log = Mock()
                operator.reconcile_own_discard()
                self.assertIsNone(operator.cached_concealed_tiles)
                self.assertIsNone(operator.pending_own_discard)
                if case == "valid":
                    operator.log.assert_called_once_with("own_discard_reconciled", tile="F",
                        followingAutomaticDiscards=2, concealedCacheInvalidated=True)
                else:
                    self.assertEqual(operator.log.call_args.args[0], "own_discard_reconciliation_failed")

    def test_riichi_multi_append_still_needs_two_public_scans(self):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_recognition_lock = threading.Lock()
        operator.public_cache_generation = 1
        operator.cached_open_melds = 0
        operator.cached_public_observation = {"ownDiscards": ["8s"]}
        operator.previous_public_observation = None
        operator.pending_own_discard = {"tile": "F", "before": ["8s"], "riichiDeclaration": True}
        operator.pending_own_river_confirmation = None
        operator.cached_concealed_tiles = ["1p"] * 13
        operator.log = Mock()
        observed = {"ownDiscards": ["8s", "F", "4m", "5p"], "ownRiichiDeclared": True}
        operator.public_recognition_result = {"generation": 1, "result": observed}
        operator.poll_public_recognition()
        operator.reconcile_own_discard()
        self.assertIsNotNone(operator.pending_own_discard)
        self.assertEqual(operator.cached_public_observation["ownDiscards"], ["8s"])
        operator.public_recognition_result = {"generation": 1, "result": observed}
        operator.poll_public_recognition()
        operator.reconcile_own_discard()
        self.assertIsNone(operator.pending_own_discard)
        self.assertIsNone(operator.cached_concealed_tiles)
        operator.log.assert_any_call("own_discard_reconciled", tile="F",
            followingAutomaticDiscards=2, concealedCacheInvalidated=True)

    def test_pending_discard_uses_public_cache_not_stale_evaluation_river(self):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.cached_public_observation = {"ownDiscards": ["W", "4p", "P"]}

        baseline = operator.own_discard_baseline({"state": {"ownDiscards": ["W"]}})

        self.assertEqual(baseline, ["W", "4p", "P"])
        self.assertIsNot(baseline, operator.cached_public_observation["ownDiscards"])

    def test_pre_click_refresh_blocks_new_river_confirmation_candidate(self):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.pending_own_discard = {"tile": "E", "before": ["S"]}
        operator.pending_own_river_confirmation = ["S", "E"]
        operator.public_recognition_lock = threading.Lock()
        operator.poll_public_recognition = Mock()
        operator.log = Mock()

        self.assertTrue(operator.refresh_discard_reconciliation_before_click())
        operator.poll_public_recognition.assert_called_once_with()
        operator.log.assert_called_once_with(
            "own_discard_reconciliation_pre_click_wait", expected="E", before=["S"],
            confirmationCandidate=["S", "E"],
        )

    def test_default_preserves_environment_and_explicit_test_budget_is_bounded(self):
        environment = {"FORCE_AUTO_CLICK_BUDGET_MS": "2600", "OTHER": "unchanged"}
        self.assertIs(configure_evaluator_click_budget(environment, None, 5000), environment)
        updated = configure_evaluator_click_budget(environment, 8000, 300000)
        self.assertEqual(updated["FORCE_AUTO_CLICK_BUDGET_MS"], "8000")
        self.assertEqual(updated["OTHER"], "unchanged")
        self.assertEqual(environment["FORCE_AUTO_CLICK_BUDGET_MS"], "2600")
        for invalid in (0, -1, 5001):
            with self.assertRaises(ValueError):
                configure_evaluator_click_budget(environment, invalid, 5000)


_ORIGINAL_PATH_READ_BYTES = Path.read_bytes
_ORIGINAL_IMAGE_OPEN = Image.open


def _is_missing_local_artifact(path) -> bool:
    if not isinstance(path, (str, Path)):
        return False
    candidate = Path(path)
    return "artifacts" in candidate.parts and not candidate.is_file()


def _read_bytes_or_skip_missing_artifact(path: Path) -> bytes:
    if _is_missing_local_artifact(path):
        raise unittest.SkipTest(f"local live fixture is unavailable: {path}")
    return _ORIGINAL_PATH_READ_BYTES(path)


def _open_or_skip_missing_artifact(path, *args, **kwargs):
    if _is_missing_local_artifact(path):
        raise unittest.SkipTest(f"local live fixture is unavailable: {path}")
    return _ORIGINAL_IMAGE_OPEN(path, *args, **kwargs)


class PostCallWhiteDiscardTest(unittest.TestCase):
    def test_native_post_pon_white_discard_keeps_evaluator_tenpai(self):
        fixture = load_json(FRAME_FIXTURES / "post-pon-white-discard-20261023.json")
        frame = (FRAME_FIXTURES / "post-pon-white-discard-20261023.jpg").read_bytes()
        self.assertEqual(hashlib.sha256(frame).hexdigest(), fixture["nativeSha256"])
        evaluation = fixture["evaluation"]
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = load_json(FRAME_FIXTURES.parents[1] / "config/layout-300-regression.json")
        operator.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        operator.river_clip = operator.layout["publicTileRegions"]["ownDiscards"]
        operator.cached_open_melds = 2
        operator.pending_post_call_discard = True
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = frame
        operator.screencast_draw_generation = 4
        operator.log = Mock()
        operator.require_force_auto_click_budget = Mock()
        operator.require_action_deadline = Mock()
        operator.refresh_discard_reconciliation_before_click = Mock(return_value=False)
        operator.confirm_discard = Mock(return_value={"confirmation": "hand_and_own_river_changed"})
        page = Mock()
        with patch("auto_operator.raised_tile_confirmation_point",
                   return_value={"x": 933, "y": 971, "lift": 28, "faceStructureDelta": 0.0}):
            receipt = operator.execute(page, evaluation, evaluated_full=frame,
                                       evaluated_hand=crop_screenshot(frame, operator.hand_clip),
                                       evaluated_draw_generation=4, evaluated_captured_at=10.0)
        self.assertEqual(receipt["discardedTile"], "P")
        self.assertEqual(receipt["clickIndex"], 7)
        self.assertEqual(page.mouse.click.call_args_list,
                         [call(933, 999), call(933, 971, delay=80)])
        self.assertFalse(any(c.args[0] == "ambiguous_open_draw_fallback"
                             for c in operator.log.call_args_list))
        operator.require_force_auto_click_budget.assert_any_call(10.0, phase="before_discard_click")

        # A later normal draw retains the existing conservative fallback.
        operator.pending_post_call_discard = False
        page.mouse.reset_mock()
        with patch("auto_operator.raised_tile_confirmation_point",
                   return_value={"x": 933, "y": 971, "lift": 28, "faceStructureDelta": 0.0}):
            receipt = operator.execute(page, evaluation, evaluated_full=frame,
                                       evaluated_hand=crop_screenshot(frame, operator.hand_clip),
                                       evaluated_draw_generation=4, evaluated_captured_at=10.0)
        self.assertEqual(receipt["discardedTile"], "9p")

        # The new certificate never bypasses the fresh pre-click hand guard.
        operator.pending_post_call_discard = True
        image = Image.open(io.BytesIO(frame)).convert("RGB")
        slots = operator.layout["handSlots"]
        first, last = slots[0], slots[7]
        face = image.crop((first["x"], first["y"], first["x"] + first["width"],
                           first["y"] + first["height"]))
        image.paste(face, (last["x"], last["y"]))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        operator.latest_screencast_frame = buffer.getvalue()
        page.mouse.reset_mock()
        with self.assertRaisesRegex(RetryableSafetyAbort, "hand changed since evaluation"):
            operator.execute(page, evaluation, evaluated_full=frame,
                             evaluated_hand=crop_screenshot(frame, operator.hand_clip),
                             evaluated_draw_generation=4, evaluated_captured_at=10.0)
        page.mouse.click.assert_not_called()

    def test_white_certificate_requires_post_call_state_and_exact_geometry(self):
        fixture = load_json(FRAME_FIXTURES / "post-pon-white-discard-20261023.json")
        frame = (FRAME_FIXTURES / "post-pon-white-discard-20261023.jpg").read_bytes()
        layout = load_json(FRAME_FIXTURES.parents[1] / "config/layout-300-regression.json")
        original = fixture["evaluation"]
        verify = lambda evaluation, image=frame, melds=2, pending=True: verified_post_call_white_discard(
            evaluation, image, layout, melds, pending)
        self.assertTrue(verify(original))
        self.assertFalse(verify(original, pending=False))
        self.assertFalse(verify(original, image=None))
        for melds in (0, 1, 3, 4):
            self.assertFalse(verify(original, melds=melds))
        for field, value in (("clickIndex", 6), ("clickPoint", {"x": 553.5, "y": 999}),
                             ("openMelds", 1)):
            evaluation = json.loads(json.dumps(original))
            evaluation[field] = value
            self.assertFalse(verify(evaluation))
        for field, value in (("draw", "S"), ("melds", []), ("hand", [])):
            evaluation = json.loads(json.dumps(original))
            evaluation["state"][field] = value
            self.assertFalse(verify(evaluation))
        evaluation = json.loads(json.dumps(original))
        evaluation["decision"]["selectedAction"]["tile"] = "9p"
        self.assertFalse(verify(evaluation))

    def test_white_certificate_rejects_ink_empty_slot_and_missing_felt_boundary(self):
        fixture = load_json(FRAME_FIXTURES / "post-pon-white-discard-20261023.json")
        frame = (FRAME_FIXTURES / "post-pon-white-discard-20261023.jpg").read_bytes()
        layout = load_json(FRAME_FIXTURES.parents[1] / "config/layout-300-regression.json")
        target = layout["handSlots"][7]
        for source_index in (0, 2, 3, 4, 8):
            with self.subTest(source_index=source_index):
                image = Image.open(io.BytesIO(frame)).convert("RGB")
                source = layout["handSlots"][source_index]
                patch_image = image.crop((source["x"], source["y"],
                                          source["x"] + source["width"], source["y"] + source["height"]))
                image.paste(patch_image, (target["x"], target["y"]))
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                self.assertFalse(verified_post_call_white_discard(
                    fixture["evaluation"], buffer.getvalue(), layout, 2, True))
        image = Image.open(io.BytesIO(frame)).convert("RGB")
        right = target["x"] + target["width"]
        ImageDraw.Draw(image).rectangle((right, target["y"], right + 30,
                                        target["y"] + target["height"]), fill="white")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        self.assertFalse(verified_post_call_white_discard(
            fixture["evaluation"], buffer.getvalue(), layout, 2, True))


class RecordingMouse:
    def __init__(self) -> None:
        self.calls = []

    def click(self, x, y, **kwargs) -> None:
        self.calls.append((x, y, kwargs))

    def move(self, x, y) -> None:
        self.calls.append(("move", x, y))


class ActionDeadlineTest(unittest.TestCase):
    def test_riichi_selection_accepts_two_bright_candidates_but_not_ordinary_hand(self) -> None:
        project = Path(__file__).resolve().parents[1]
        hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        for name, expected in (
            ("riichi-before-selection-20261020.jpg", False),
            ("riichi-two-candidates-selection-20261020.jpg", True),
        ):
            with self.subTest(frame=name):
                frame = (project / "test/fixtures" / name).read_bytes()
                self.assertEqual(riichi_selection_is_visible(crop_screenshot(frame, hand_clip)), expected)

        # Enough neutral shading alone must not admit a bright-majority hand.
        image = Image.new("RGB", (100, 1), (230, 230, 230))
        ImageDraw.Draw(image).rectangle((0, 0, 44, 0), fill=(110, 110, 110))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        self.assertFalse(riichi_selection_is_visible(buffer.getvalue()))

    def test_riichi_selection_signature_requires_dimmed_hand(self) -> None:
        project = Path(__file__).resolve().parents[1]
        selection = (project / "artifacts/live/riichi-selection-dimmed-20260928.png").read_bytes()
        ordinary = (project / "artifacts/live/riichi-button-hand-border-20260928.jpg").read_bytes()
        hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        self.assertTrue(riichi_selection_is_visible(crop_screenshot(selection, hand_clip)))
        self.assertFalse(riichi_selection_is_visible(crop_screenshot(ordinary, hand_clip)))

    def test_riichi_selection_target_requires_the_evaluated_physical_slot(self) -> None:
        layout = load_json(Path(__file__).resolve().parents[1] / "config/layout-300-regression.json")
        point = layout["clickPoints"][7]
        region = riichi_selection_target_region(layout, 7, point)
        self.assertIsNotNone(region)
        self.assertEqual(region["x"], layout["handSlots"][7]["x"] + 10)
        # A hand-wide geometry check is insufficient: a neighbouring slot
        # must not be accepted for the post-Riichi target.
        self.assertIsNone(riichi_selection_target_region(layout, 7, layout["clickPoints"][6]))

    def test_riichi_confirmation_accepts_dimmed_selection_not_unchanged_button(self) -> None:
        project = Path(__file__).resolve().parents[1]
        selection = (project / "artifacts/live/riichi-selection-dimmed-20260928.png").read_bytes()
        ordinary = (project / "artifacts/live/riichi-button-hand-border-20260928.jpg").read_bytes()
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(confirmation_timeout=1, action_pixel_delta=1.5)
        operator.layout = load_json(project / "config/layout-300-regression.json")
        operator.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        operator.screen_references = {}
        region = {"x": 894, "y": 775, "width": 229, "height": 50}
        before_button = crop_screenshot(ordinary, region)
        before_hand = crop_screenshot(ordinary, operator.hand_clip)
        page = Mock()

        def screenshot(**kwargs):
            clip = kwargs.get("clip")
            if clip == region:
                return before_button
            if clip == operator.hand_clip:
                return crop_screenshot(selection, operator.hand_clip)
            return selection

        page.screenshot.side_effect = screenshot
        receipt = operator.confirm_action_button(
            page, "riichi", before_button, before_hand, region_override=region,
        )
        self.assertEqual(receipt["confirmation"], "riichi_selection_hand_changed")
        self.assertEqual(receipt["buttonPixelDelta"], 0)
        self.assertEqual(receipt["screenState"], "match")

    def test_startup_pointer_retreats_to_table_felt(self) -> None:
        mouse = RecordingMouse()
        retreat_pointer_from_hand(mouse, {"width": 1920, "height": 1080})
        self.assertEqual(mouse.calls, [("move", 960, 777.6)])

    def test_execute_shimmer_fallback_clicks_only_after_identity_and_same_generation(self) -> None:
        project = Path(__file__).resolve().parents[1]
        before = (project / "artifacts/live/riichi-shimmer-hand-before-20260928.jpg").read_bytes()
        after = (project / "artifacts/live/riichi-shimmer-hand-after-20260928.jpg").read_bytes()
        tiles = ["3m", "3m", "0m", "7m", "3p", "4p", "5p", "6p", "8p", "8p", "2s", "3s", "4s", "6p"]
        for same_generation, verified in [(True, True), (True, False), (False, True)]:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False, stability_pixel_delta=1.5)
            operator.layout = load_json(project / "config/layout-300-regression.json")
            operator.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
            operator.river_clip = {"x": 770, "y": 535, "width": 390, "height": 225}
            operator.cached_open_melds = 0
            operator.screencast_session = Mock()
            operator.latest_screencast_frame = after
            operator.screencast_draw_generation = 5 if same_generation else 6
            operator.verify_closed_hand_identity = Mock(return_value=verified)
            operator.require_action_deadline = Mock()
            operator.log = Mock()
            operator.confirm_discard = Mock(return_value={"confirmation": "test"})
            page = Mock()
            evaluation = {"decision": {"selectedAction": {"action": "discard", "tile": "6p"}},
                          "recognition": {"tiles": tiles, "safe": False}, "clickIndex": 13}
            with patch("auto_operator.stable_hand_delta", return_value=3.0), \
                    patch("auto_operator.raised_tile_confirmation_point",
                          return_value={"x": 1532, "y": 971, "lift": 28, "faceStructureDelta": 0.0}):
                if same_generation and verified:
                    self.assertTrue(operator.execute(page, evaluation, crop_screenshot(before, operator.hand_clip),
                                                    before, 5)["clicked"])
                    self.assertEqual(page.mouse.click.call_count, 2)
                else:
                    with self.assertRaises(RetryableSafetyAbort):
                        operator.execute(page, evaluation, crop_screenshot(before, operator.hand_clip), before, 5)
                    page.mouse.click.assert_not_called()
            if not same_generation:
                operator.verify_closed_hand_identity.assert_not_called()

    def test_closed_hand_identity_uses_per_slot_glyphs_not_hybrid_recognition(self) -> None:
        expected = ["3m", "3m", "0m", "7m", "3p", "4p", "5p", "6p", "8p", "8p", "2s", "3s", "4s", "6p"]
        project = Path(__file__).resolve().parents[1]
        frames = project / "artifacts" / "friend-300-aa5dfd4-room53493-20261016" / "frames"
        evaluated = (frames / "2026-10-16T02-23-40.550363+00-00.jpg").read_bytes()
        changed = (frames / "2026-10-16T02-23-42.719303+00-00.identity.jpg").read_bytes()
        # The live artifact is crucial: the hybrid fallback hallucinated more
        # labels, but per-slot glyph comparison isolates the actual 2s -> 5s
        # face replacement at index 9 and must refuse the click.
        layout = load_json(project / "config" / "layout-300-regression.json")
        self.assertEqual(closed_hand_face_mismatches(evaluated, changed, layout, 1.5), [
            {"index": 9, "faceStructureDelta": 41.096},
        ])
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(stability_pixel_delta=1.5)
            operator.frames = Path(directory)
            operator.layout = layout
            operator.screencast_draw_generation = 5
            operator.screencast_draw_occupied = True
            operator.cached_open_melds = 0
            operator.latest_screencast_frame = changed
            operator.log = Mock()
            with patch("auto_operator.subprocess.run") as run:
                self.assertFalse(operator.verify_closed_hand_identity(Mock(), expected, evaluated, changed, 5))
                run.assert_not_called()
            detail = operator.log.call_args.kwargs
            self.assertEqual(detail["verification"], "per_slot_glyph_structure")
            self.assertEqual(detail["mismatches"], [{"index": 9, "faceStructureDelta": 41.096}])
            page = Mock()
            page.wait_for_timeout.side_effect = lambda _: setattr(operator, "screencast_draw_generation", 6)
            self.assertFalse(operator.verify_closed_hand_identity(page, expected, changed, changed, 5))
            operator.screencast_draw_generation = 5
            operator.screencast_draw_occupied = True
            operator.latest_screencast_frame = changed
            self.assertTrue(operator.verify_closed_hand_identity(Mock(), expected, changed, changed, 5))

    def test_missing_public_context_requests_refresh_without_resetting_deadline(self) -> None:
        for reason in ("stale", "invalid_capture_time", None):
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(mode="force-auto", public_cache=True)
            operator.schedule_public_recognition = Mock()
            operator.log = Mock()
            operator.action_evidence_started_at = 123.0
            cache = {"applied": False, **({"ignoredReason": reason} if reason else {})}
            evaluation = {"status": "decision", "decision": {"selectedAction": {"action": "discard"}}, "publicCache": cache}
            self.assertTrue(operator.defer_missing_public_context(evaluation, b"current-frame"))
            operator.schedule_public_recognition.assert_called_once_with(b"current-frame", force=True)
            self.assertEqual(operator.action_evidence_started_at, 123.0)

    def test_public_context_gate_preserves_wins_and_explicit_cache_disabled_mode(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", public_cache=True)
        operator.schedule_public_recognition = Mock()
        operator.log = Mock()
        for action in ("tsumo", "ron", "ankan"):
            evaluation = {"status": "decision", "decision": {"selectedAction": {"action": action}}, "publicCache": {"applied": False}}
            self.assertFalse(operator.defer_missing_public_context(evaluation, b"frame"))
        evaluation = {"status": "decision", "decision": {"selectedAction": {"action": "riichi"}}, "publicCache": {"applied": True}}
        self.assertFalse(operator.defer_missing_public_context(evaluation, b"frame"))
        operator.args.public_cache = False
        evaluation["publicCache"]["applied"] = False
        self.assertFalse(operator.defer_missing_public_context(evaluation, b"frame"))
        operator.schedule_public_recognition.assert_not_called()

    def test_explicit_300_second_test_clock_does_not_expire_after_five_seconds(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(action_deadline_ms=300000)
        operator.action_evidence_started_at = time.monotonic() - 10
        self.assertGreater(operator.action_deadline_remaining_ms(), 280000)
        operator.require_action_deadline()
        timing = action_deadline_timing(100, 110, 111, 300000)
        self.assertEqual(timing["deadlineMs"], 300000)
        self.assertTrue(timing["deadlineMet"])

    def assert_fast_path(self, kind: str, decision_delay: float, click_delay: float) -> None:
        timing = action_deadline_timing(100.0, 100.0 + decision_delay, 100.0 + click_delay)
        self.assertTrue(timing["deadlineMet"], kind)
        self.assertEqual(timing["evidenceToClickMs"], round(click_delay * 1000))
        self.assertEqual(timing["detectionToDecisionMs"] + timing["decisionToClickMs"], timing["evidenceToClickMs"])

    def test_discard_path_is_measured_from_draw_evidence(self) -> None:
        self.assert_fast_path("discard", 0.35, 2.4)

    def test_call_path_is_measured_from_reaction_evidence(self) -> None:
        self.assert_fast_path("call", 0.05, 0.25)

    def test_win_path_is_measured_from_reaction_evidence(self) -> None:
        self.assert_fast_path("win", 0.04, 0.18)

    def test_deadline_overrun_is_explicit(self) -> None:
        timing = action_deadline_timing(10.0, 14.0, 15.001)
        self.assertFalse(timing["deadlineMet"])
        self.assertLess(timing["remainingMsAtClick"], 0)


class AwayDialogDetectionTest(unittest.TestCase):
    def test_board_cache_verifies_changed_right_score_panel(self):
        from auto_operator import wall_counter_signature
        root = Path(__file__).resolve().parents[1]
        before = (root / "test/fixtures/board-right-highlight-before-20261029.jpg").read_bytes()
        after_path = root / "test/fixtures/board-right-highlight-after-20261029.jpg"
        self.assertFalse(board_state_signature_matches(board_state_signature(before),
                                                       board_state_signature(after_path.read_bytes())))
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.board_metadata_lock = threading.Lock()
        operator.board_metadata_ocr_lock = threading.Lock()
        operator.board_metadata_result = None
        operator.log = Mock()
        metadata = {"verified": True, "seat": "north", "remainingTiles": 57,
                    "scores": {"north": 25000, "east": 25000, "south": 25000, "west": 25000}}
        operator.board_metadata_cache = {"metadata": metadata, "signature": board_state_signature(before),
                                         "wallSignature": wall_counter_signature(before),
                                         "capturedAt": 10.0, "screenshot": "before"}
        with patch("auto_operator.time.monotonic", return_value=11), \
             patch("board_metadata.recognize_remaining_count", return_value=54), \
             patch("board_metadata.recognize_right_score", return_value=25000) as score:
            self.assertEqual(operator.cached_board_metadata(after_path)["remainingTiles"], 54)
            score.return_value = 24000
            self.assertIsNone(operator.cached_board_metadata(after_path))
            score.return_value = None
            self.assertIsNone(operator.cached_board_metadata(after_path))
            score.return_value = 25000
            with operator.board_metadata_ocr_lock:
                self.assertIsNone(operator.cached_board_metadata(after_path))
            with tempfile.TemporaryDirectory() as directory:
                changed = Path(directory) / "changed.png"
                with Image.open(after_path) as image:
                    modified = image.convert("RGB")
                ImageDraw.Draw(modified).rectangle((905, 385, 1015, 424), fill="white")
                modified.save(changed)
                self.assertIsNone(operator.cached_board_metadata(changed))

    def test_board_cache_requires_exact_wall_counter_for_cached_remaining_tiles(self):
        from auto_operator import wall_counter_signature

        def make_frame(digit):
            image = Image.new("RGB", (1920, 1080), (20, 30, 50))
            ImageDraw.Draw(image).text((960, 435), digit, fill=(220, 220, 220))
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()

        before, after = make_frame("9"), make_frame("8")
        self.assertTrue(board_state_signature_matches(board_state_signature(before),
                                                      board_state_signature(after)))
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.board_metadata_lock = threading.Lock()
        operator.board_metadata_result = None
        operator.log = Mock()
        metadata = {"verified": True, "remainingTiles": 69}
        operator.board_metadata_cache = {"metadata": metadata, "signature": board_state_signature(before),
                                         "wallSignature": wall_counter_signature(before),
                                         "capturedAt": 10.0, "screenshot": "before"}
        with tempfile.TemporaryDirectory() as directory, patch("auto_operator.time.monotonic", return_value=11):
            frame = Path(directory) / "frame.png"
            frame.write_bytes(before)
            self.assertEqual(operator.cached_board_metadata(frame), metadata)
            frame.write_bytes(after)
            self.assertIsNone(operator.cached_board_metadata(frame))
            operator.board_metadata_ocr_lock = threading.Lock()
            with patch("board_metadata.recognize_remaining_count", return_value=68):
                self.assertEqual(operator.cached_board_metadata(frame)["remainingTiles"], 68)
                self.assertEqual(operator.board_metadata_cache["metadata"]["remainingTiles"], 69)
            with patch("board_metadata.recognize_remaining_count", return_value=0):
                self.assertEqual(operator.cached_board_metadata(frame)["remainingTiles"], 0)
            with patch("board_metadata.recognize_remaining_count", return_value=None):
                self.assertIsNone(operator.cached_board_metadata(frame))
            with operator.board_metadata_ocr_lock:
                self.assertIsNone(operator.cached_board_metadata(frame))
            frame.write_bytes(before)
            operator.board_metadata_cache.pop("wallSignature")
            with patch("board_metadata.recognize_remaining_count", return_value=None):
                self.assertIsNone(operator.cached_board_metadata(frame))

    def test_board_metadata_cache_ignores_turn_rim_but_expires(self) -> None:
        project = Path(__file__).resolve().parents[1]
        before = (project / "test/fixtures/board-cache-opponent-turn-20261020.jpg").read_bytes()
        current = project / "test/fixtures/board-cache-same-scores-own-turn-20261020.png"
        self.assertTrue(board_state_signature_matches(
            board_state_signature(before), board_state_signature(current.read_bytes()),
        ))
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.board_metadata_lock = threading.Lock()
        operator.board_metadata_ocr_lock = threading.Lock()
        operator.board_metadata_result = None
        operator.board_metadata_thread = None
        metadata = {"verified": True, "seat": "north", "round": "east_2", "honba": 1,
                    "riichiSticks": 1,
                    "scores": {"north": 23500, "east": 25500, "south": 22900, "west": 27100}}
        operator.board_metadata_cache = {
            "metadata": metadata, "signature": board_state_signature(before),
            "capturedAt": 10.0, "screenshot": "verified-opponent-turn.jpg",
        }
        operator.log = Mock()
        with patch("auto_operator.time.monotonic", return_value=15.8), \
                patch("board_metadata.recognize_board", side_effect=AssertionError("unnecessary OCR")):
            self.assertEqual(operator.current_board_metadata(current), metadata)
        with patch("auto_operator.time.monotonic", return_value=18.001), \
                patch("board_metadata.recognize_board", return_value={"verified": False}) as recognize:
            self.assertEqual(operator.current_board_metadata(current), {"verified": False})
            recognize.assert_called_once_with(current)

    def test_board_metadata_cache_rejects_single_score_digit_change_alone(self) -> None:
        project = Path(__file__).resolve().parents[1]
        first = (project / "test/fixtures/board-cache-score-26400-20261020.jpg").read_bytes()
        second = (project / "test/fixtures/board-cache-score-25400-20261020.jpg").read_bytes()
        # Copy only the opposite score: retain the original turn rim, round,
        # counters and all other pixels. The one changed digit must suffice.
        with Image.open(io.BytesIO(first)) as source, Image.open(io.BytesIO(second)) as changed:
            isolated = source.convert("RGB")
            score_box = (905, 350, 1015, 377)
            isolated.paste(changed.crop(score_box), score_box)
            buffer = io.BytesIO()
            isolated.save(buffer, format="PNG")
        self.assertFalse(board_state_signature_matches(
            board_state_signature(first), board_state_signature(buffer.getvalue()),
        ))

    def test_board_metadata_cache_requires_same_recent_scoreboard(self) -> None:
        def frame_with_score(color: tuple[int, int, int]) -> bytes:
            image = Image.new("RGB", (1920, 1080), (20, 30, 50))
            ImageDraw.Draw(image).rectangle((910, 460, 1010, 505), fill=color)
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()

        first = frame_with_score((45, 50, 55))
        changed = frame_with_score((120, 130, 140))
        self.assertTrue(board_state_signature_matches(board_state_signature(first), board_state_signature(first)))
        self.assertFalse(board_state_signature_matches(board_state_signature(first), board_state_signature(changed)))
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(board_metadata=True)
            operator.frames = Path(directory)
            operator.board_metadata_thread = None
            operator.board_metadata_result = None
            operator.board_metadata_cache = None
            operator.board_metadata_lock = threading.Lock()
            operator.board_metadata_ocr_lock = threading.Lock()
            operator.board_metadata_last_scan_at = 0.0
            operator.log = Mock()
            path = Path(directory) / "current.png"
            path.write_bytes(first)
            metadata = {"verified": True, "round": "east_1", "scores": {"east": 25000}}
            with patch("board_metadata.recognize_board", return_value=metadata) as recognize:
                operator.schedule_board_metadata(first)
                operator.board_metadata_thread.join(timeout=2)
                self.assertEqual(operator.current_board_metadata(path), metadata)
                self.assertEqual(recognize.call_count, 1)
                path.write_bytes(changed)
                self.assertEqual(operator.current_board_metadata(path), metadata)
                self.assertEqual(recognize.call_count, 2)

    def test_board_metadata_refresh_throttle_yields_to_changed_hud(self) -> None:
        def frame(color):
            image = Image.new("RGB", (1920, 1080), (20, 30, 50))
            ImageDraw.Draw(image).rectangle((910, 460, 1010, 505), fill=color)
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()

        first = frame((45, 50, 55))
        changed = frame((120, 130, 140))
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(board_metadata=True)
            operator.frames = Path(directory)
            operator.board_metadata_thread = None
            operator.board_metadata_result = None
            operator.board_metadata_cache = None
            operator.board_metadata_lock = threading.Lock()
            operator.board_metadata_ocr_lock = threading.Lock()
            operator.board_metadata_last_scan_at = 0.0
            operator.log = Mock()
            metadata = {"verified": True, "round": "east_1", "scores": {"east": 25000}}
            with patch("auto_operator.time.monotonic", return_value=100.0), \
                    patch("board_metadata.recognize_board", return_value=metadata) as recognize:
                operator.schedule_board_metadata(first)
                operator.board_metadata_thread.join(timeout=2)
                operator.schedule_board_metadata(first)
                self.assertEqual(recognize.call_count, 1)
                operator.schedule_board_metadata(changed)
                operator.board_metadata_thread.join(timeout=2)
                self.assertEqual(recognize.call_count, 2)
                path = Path(directory) / "old.png"
                path.write_bytes(first)
                self.assertIsNone(operator.cached_board_metadata(path))

    def setUp(self) -> None:
        # Captured live-match frames are intentionally gitignored. Keep these
        # regressions active on workstations that retain them, while allowing a
        # clean checkout to run the hermetic portion of the suite.
        read_patcher = patch.object(Path, "read_bytes", _read_bytes_or_skip_missing_artifact)
        open_patcher = patch.object(Image, "open", _open_or_skip_missing_artifact)
        read_patcher.start()
        open_patcher.start()
        self.addCleanup(open_patcher.stop)
        self.addCleanup(read_patcher.stop)

    def run_reaction_frame(self, frame: bytes, *, accept_call: bool, policy_error=None, iterations=2) -> PythonAutoOperator:
        project = Path(__file__).resolve().parents[1]
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(
            mode="force-auto", max_iterations=iterations, poll=0.001,
            accept_single_call=accept_call, action_templates="", stability_pixel_delta=1.5,
            stop_on_error=True,
        )
        operator.layout = load_json(project / "config" / "layout.json")
        operator.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        operator.action_clip = None
        operator.frames = Path(directory.name)
        operator.screen_references = {}
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = frame
        operator.screencast_sequence = 1
        operator.screencast_draw_occupied = False
        operator.screencast_draw_generation = 0
        operator.rejected_screencast_size = None
        operator.cached_public_observation = None
        operator.cached_concealed_tiles = None
        operator.cached_open_melds = 0
        operator.dynamic_layout_required = False
        operator.pending_post_call_discard = False
        operator.pending_post_call_started_at = None
        operator.restart_open_hand_probe_hash = None
        operator.open_meld_candidate = None
        operator.open_meld_candidate_frames = set()
        operator.last_processed_hand = None
        operator.armed = True
        operator.previous_public_observation = None
        operator.last_shanten = 1
        operator.round_terminal_latched = False
        operator.action_evidence_started_at = None
        operator.action_evidence_last_seen_at = None
        operator.action_evidence_kind = None
        operator.last_action_clicked_at = None
        operator.poll_public_recognition = Mock()
        operator.ensure_viewport = Mock()
        operator.start_screencast_gate = Mock()
        operator.schedule_periodic_public_recognition = Mock()
        operator.resume_if_away = Mock(return_value=False)
        operator.advance_ranked_loop = Mock(return_value=False)
        operator.execute_force_auto_call = Mock(return_value={"clicked": True, "action": "pon"})
        operator.evaluate_force_auto_call_policy = Mock(return_value={
            "status": "decision",
            "decision": {"selectedAction": {"id": "pon_P", "action": "pon"},
                         "callAssessments": [{"actionId": "pon_P", "approved": True}]},
        })
        operator.execute_force_auto_reaction_win = Mock(return_value={"clicked": True, "action": "ron"})
        if policy_error is not None:
            operator.evaluate_force_auto_call_policy.side_effect = policy_error
        operator.execute_reaction_pass = Mock(return_value={"clicked": True, "action": "pass"})
        operator.log = Mock()
        page = Mock()
        page.url = "https://game.mahjongsoul.com/index.html"
        page.screenshot.return_value = frame
        with patch("auto_operator.classify_screen", return_value=("match", 1.0)):
            operator.run(page)
        return operator

    def test_retryable_call_policy_failure_defers_without_clicking(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frame = (project / "artifacts" / "debug-300-after-hash-fix.png").read_bytes()
        operator = self.run_reaction_frame(
            frame, accept_call=True,
            policy_error=RetryableSafetyAbort("board metadata not verified: four_scores_not_verified"),
        )
        operator.evaluate_force_auto_call_policy.assert_called_once()
        operator.execute_force_auto_call.assert_not_called()
        operator.execute_reaction_pass.assert_not_called()
        self.assertTrue(any(c.args[0] == "reaction_call_policy_deferred" for c in operator.log.call_args_list))
        self.assertIsNotNone(operator.action_evidence_started_at)

    def test_call_policy_can_recover_on_next_frame(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frame = (project / "artifacts" / "debug-300-after-hash-fix.png").read_bytes()
        operator = self.run_reaction_frame(
            frame, accept_call=True, iterations=3,
            policy_error=[RetryableSafetyAbort("four_scores_not_verified"), {"status": "decision"}],
        )
        self.assertEqual(operator.evaluate_force_auto_call_policy.call_count, 2)
        operator.execute_force_auto_call.assert_called_once()
        operator.execute_reaction_pass.assert_not_called()
        self.assertTrue(any(c.args[0] == "reaction_call_policy_deferred" for c in operator.log.call_args_list))

    def test_call_policy_unexpected_error_is_not_swallowed(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frame = (project / "artifacts" / "debug-300-after-hash-fix.png").read_bytes()
        with self.assertRaisesRegex(RuntimeError, "unexpected evaluator failure"):
            self.run_reaction_frame(frame, accept_call=True, policy_error=RuntimeError("unexpected evaluator failure"))

    def test_run_loop_call_path_meets_end_to_end_deadline(self) -> None:
        project = Path(__file__).resolve().parents[1]
        image = Image.open(project / "artifacts" / "debug-300-after-hash-fix.png").convert("RGB")
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=55)
        operator = self.run_reaction_frame(output.getvalue(), accept_call=True)
        operator.execute_force_auto_call.assert_called_once()
        operator.evaluate_force_auto_call_policy.assert_called_once()
        event = next(c for c in operator.log.call_args_list if c.args[0] == "reaction_call")
        self.assertTrue(event.kwargs["execution"]["actionTiming"]["deadlineMet"])

    def test_run_loop_win_path_meets_end_to_end_deadline(self) -> None:
        project = Path(__file__).resolve().parents[1]
        image = Image.open(project / "artifacts" / "debug-300-after-hash-fix.png").convert("RGB")
        # Preserve the captured certified pass prompt and add the calibrated
        # orange win button pixels from the live Ron frame.
        ron = Image.open(project / "artifacts" / "friend-5-20" / "frames" /
                         "2026-09-21T08-38-54.094464+00-00.png").convert("RGB")
        image.paste(ron.crop((850, 700, 1150, 900)), (850, 700))
        output = io.BytesIO()
        image.save(output, format="PNG")
        win = {"center": {"x": 1010.5, "y": 823.0}}
        with patch("auto_operator.force_auto_self_action_buttons", return_value=[win]), \
                patch("auto_operator.force_auto_reaction_win_button", return_value=win):
            operator = self.run_reaction_frame(output.getvalue(), accept_call=True)
        operator.execute_force_auto_reaction_win.assert_called_once()
        event = next(c for c in operator.log.call_args_list if c.args[0] == "reaction_win")
        self.assertTrue(event.kwargs["execution"]["actionTiming"]["deadlineMet"])

    def test_screencast_rejects_resized_frame_and_clears_stale_gate(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = {
            "viewport": {"width": 1920, "height": 1080},
            "drawSlot": {"x": 1600, "y": 900, "width": 100, "height": 100},
        }
        operator.latest_screencast_frame = b"stale calibrated frame"
        operator.latest_screencast_captured_at = 123.456
        operator.screencast_sequence = 4
        operator.screencast_draw_occupied = True
        operator.screencast_draw_generation = 2
        operator.rejected_screencast_size = None
        operator.log = Mock()
        resized = io.BytesIO()
        Image.new("RGB", (1058, 1080), "white").save(resized, format="JPEG")

        self.assertFalse(operator.accept_screencast_frame(resized.getvalue()))

        self.assertIsNone(operator.latest_screencast_frame)
        self.assertIsNone(operator.latest_screencast_captured_at)
        self.assertIsNone(operator.screencast_draw_occupied)
        self.assertEqual(operator.screencast_draw_generation, 2)
        self.assertEqual(operator.screencast_sequence, 5)
        operator.log.assert_called_once_with(
            "screencast_frame_rejected", expected=[1920, 1080], actual=[1058, 1080],
        )

    def test_screencast_repeated_full_width_resize_requests_screen_loss_stop(self) -> None:
        """A replaced tab must not be treated as an open hand indefinitely."""
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = {
            "viewport": {"width": 1920, "height": 1080},
            "drawSlot": {"x": 1600, "y": 900, "width": 100, "height": 100},
        }
        operator.latest_screencast_frame = b"stale calibrated frame"
        operator.screencast_sequence = 0
        operator.screencast_draw_occupied = True
        operator.screencast_draw_generation = 0
        operator.rejected_screencast_size = None
        operator.rejected_viewport_frame_streak = 0
        operator.screen_loss_stop_requested = False
        operator.log = Mock()
        resized = io.BytesIO()
        Image.new("RGB", (1920, 733), "white").save(resized, format="JPEG")

        for _ in range(3):
            self.assertFalse(operator.accept_screencast_frame(resized.getvalue()))

        self.assertTrue(operator.screen_loss_stop_requested)
        self.assertEqual(operator.rejected_viewport_frame_streak, 3)
        self.assertIsNone(operator.latest_screencast_frame)
        self.assertEqual(operator.log.call_args_list[-1], call(
            "screen_loss_stop", expected=[1920, 1080], actual=[1920, 733],
            rejectedViewportFrames=3, gameplayClicks=0,
            reason="repeated_full_width_screencast_dimension_mismatch",
        ))

    def test_screencast_calibrated_frame_clears_pending_screen_loss_streak(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = {
            "viewport": {"width": 1920, "height": 1080},
            "drawSlot": {"x": 1600, "y": 900, "width": 100, "height": 100},
        }
        operator.latest_screencast_frame = None
        operator.screencast_sequence = 0
        operator.screencast_draw_occupied = None
        operator.screencast_draw_generation = 0
        operator.rejected_screencast_size = (1920, 733)
        operator.rejected_viewport_frame_streak = 2
        operator.screen_loss_stop_requested = False
        operator.log = Mock()
        calibrated = io.BytesIO()
        Image.new("RGB", (1920, 1080), "white").save(calibrated, format="JPEG")

        self.assertTrue(operator.accept_screencast_frame(calibrated.getvalue()))

        self.assertEqual(operator.rejected_viewport_frame_streak, 0)
        self.assertFalse(operator.screen_loss_stop_requested)

    def test_run_returns_before_gameplay_after_screen_loss_is_latched(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="observer", max_iterations=0)
        operator.screen_loss_stop_requested = True
        operator.screencast_session = None
        operator.ensure_viewport = Mock()
        operator.start_screencast_gate = Mock()
        operator.poll_public_recognition = Mock()
        operator.log = Mock()
        page = Mock()
        page.url = "https://mahjongsoul.game.yo-star.com/"

        operator.run(page)

        operator.poll_public_recognition.assert_not_called()

    def test_screencast_accepts_calibrated_frame_after_resize(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = {
            "viewport": {"width": 1920, "height": 1080},
            "drawSlot": {"x": 1600, "y": 900, "width": 100, "height": 100},
        }
        operator.latest_screencast_frame = None
        operator.screencast_sequence = 1
        operator.screencast_draw_occupied = None
        operator.screencast_draw_generation = 0
        operator.rejected_screencast_size = (1058, 1080)
        operator.log = Mock()
        calibrated = io.BytesIO()
        Image.new("RGB", (1920, 1080), "white").save(calibrated, format="JPEG")

        self.assertTrue(operator.accept_screencast_frame(calibrated.getvalue()))

        self.assertEqual(operator.latest_screencast_frame, calibrated.getvalue())
        self.assertTrue(operator.screencast_draw_occupied)
        self.assertEqual(operator.screencast_draw_generation, 1)
        self.assertIsNone(operator.rejected_screencast_size)

    def test_silent_screencast_is_seeded_from_exact_size_screenshot_once(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = {
            "viewport": {"width": 1920, "height": 1080},
            "drawSlot": {"x": 1600, "y": 900, "width": 100, "height": 100},
        }
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = None
        operator.screencast_sequence = 0
        operator.screencast_draw_occupied = None
        operator.screencast_draw_generation = 0
        operator.rejected_screencast_size = None
        operator.log = Mock()
        frame = io.BytesIO()
        Image.new("RGB", (1920, 1080), "white").save(frame, format="PNG")
        page = Mock()
        page.screenshot.return_value = frame.getvalue()

        self.assertTrue(operator.seed_silent_screencast_gate(page))
        self.assertFalse(operator.seed_silent_screencast_gate(page))

        self.assertEqual(operator.latest_screencast_frame, frame.getvalue())
        self.assertEqual(operator.screencast_sequence, 1)
        page.screenshot.assert_called_once_with(animations="disabled")
        operator.log.assert_called_once_with(
            "screencast_gate_seeded", source="one_shot_screenshot",
        )

    def test_real_stream_frame_wins_seed_race_without_duplicate_gate_event(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = None
        operator.screencast_sequence = 0
        operator.log = Mock()
        page = Mock()

        def stream_arrives(**_kwargs):
            operator.latest_screencast_frame = b"stream"
            operator.screencast_sequence = 1
            return b"screenshot"

        page.screenshot.side_effect = stream_arrives

        self.assertFalse(operator.seed_silent_screencast_gate(page))
        self.assertEqual(operator.latest_screencast_frame, b"stream")
        self.assertEqual(operator.screencast_sequence, 1)
        operator.log.assert_not_called()

    def test_stalled_stream_refreshes_to_captured_closed_hand_reaction_prompt(self) -> None:
        project = Path(__file__).resolve().parents[1]
        prompt = (project / "artifacts" / "debug-300-monitor.png").read_bytes()
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(stability_pixel_delta=1.5)
        operator.layout = load_json(project / "config" / "layout.json")
        operator.screencast_session = Mock()
        operator.screencast_sequence = 7
        stale = io.BytesIO()
        Image.new("RGB", (1920, 1080), (25, 55, 85)).save(stale, format="PNG")
        operator.latest_screencast_frame = stale.getvalue()
        operator.screencast_draw_occupied = False
        operator.screencast_draw_generation = 0
        operator.rejected_screencast_size = None
        operator.log = Mock()
        page = Mock()
        page.screenshot.return_value = prompt

        self.assertTrue(operator.refresh_silent_screencast_gate(page))

        pass_region = operator.layout["actionButtonRegions"]["pass"]
        calls = force_auto_call_buttons(operator.latest_screencast_frame, operator.layout["viewport"])
        self.assertTrue(calls)
        self.assertTrue(is_contextual_reaction_pass(
            operator.latest_screencast_frame, pass_region, len(calls),
        ))
        self.assertEqual(operator.screencast_sequence, 8)

    def test_run_loop_routes_existing_prompt_and_survives_expired_pass_deadline(self) -> None:
        project = Path(__file__).resolve().parents[1]
        prompt_image = Image.open(project / "artifacts" / "debug-300-after-hash-fix.png").convert("RGB")
        prompt_buffer = io.BytesIO()
        prompt_image.save(prompt_buffer, format="JPEG", quality=55)
        prompt = prompt_buffer.getvalue()
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(
                mode="force-auto", max_iterations=2, poll=0.001,
                accept_single_call=False, action_templates="", stability_pixel_delta=1.5,
            )
            operator.layout = load_json(project / "config" / "layout.json")
            operator.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
            operator.action_clip = None
            operator.frames = Path(directory)
            operator.screen_references = {}
            operator.screencast_session = Mock()
            operator.latest_screencast_frame = prompt
            operator.screencast_sequence = 1
            operator.screencast_draw_occupied = False
            operator.screencast_draw_generation = 0
            operator.rejected_screencast_size = None
            operator.cached_public_observation = None
            operator.cached_concealed_tiles = None
            operator.cached_open_melds = 0
            operator.dynamic_layout_required = False
            operator.pending_post_call_discard = False
            operator.pending_post_call_started_at = None
            operator.restart_open_hand_probe_hash = None
            operator.open_meld_candidate = None
            operator.open_meld_candidate_frames = set()
            operator.last_processed_hand = None
            operator.armed = True
            operator.previous_public_observation = None
            operator.last_shanten = 1
            operator.poll_public_recognition = Mock()
            operator.ensure_viewport = Mock()
            operator.start_screencast_gate = Mock()
            operator.schedule_periodic_public_recognition = Mock()
            operator.resume_if_away = Mock(return_value=False)
            operator.advance_ranked_loop = Mock(return_value=False)
            operator.recognize_resident = Mock(return_value={"tiles": ["1m"] * 13})
            operator.execute_reaction_pass = Mock(side_effect=[
                RetryableSafetyAbort("five-second action deadline expired before safe click"),
                {"clicked": True, "action": "pass"},
            ])
            operator.log = Mock()
            page = Mock()
            page.url = "https://game.mahjongsoul.com/index.html"
            page.screenshot.return_value = prompt

            with patch("auto_operator.classify_screen", return_value=("match", 1.0)):
                operator.run(page)

            self.assertGreaterEqual(operator.execute_reaction_pass.call_count, 1)
            self.assertTrue(any(call.args and call.args[0] == "reaction_pass_deferred"
                                for call in operator.log.call_args_list))
            reaction = operator.execute_reaction_pass.call_args_list[0].args[1]
            self.assertEqual(reaction["status"], "reaction_prompt")
            self.assertEqual(reaction["actionButton"]["action"], "pass")
            self.assertTrue(any(
                call.args and call.args[0] == "reaction_gate_candidate"
                for call in operator.log.call_args_list
            ))
            self.assertFalse(any(call.args and call.args[0] == "safety_stop"
                                 for call in operator.log.call_args_list))

    def test_confirmed_call_removes_only_source_tail_and_invalidates_old_worker(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        before = {"doraIndicators": ["1p"], "ownDiscards": ["N"], "ownMeldTiles": [],
                  "opponentDiscards": [{"seat": "north", "discards": ["E", "F"], "riichiDeclared": True},
                                       {"seat": "west", "discards": ["F"]}]}
        operator.cached_public_observation = before
        operator.previous_public_observation = before
        operator.public_cache_generation = 2
        operator.public_recognition_lock = threading.Lock()
        operator.log = Mock()
        operator.reconcile_confirmed_call_discard({"tile": "F", "fromSeat": "north"})
        after = operator.cached_public_observation
        self.assertEqual(after["opponentDiscards"][0]["discards"], ["E"])
        self.assertTrue(after["opponentDiscards"][0]["riichiDeclared"])
        self.assertEqual(after["opponentDiscards"][1]["discards"], ["F"])
        self.assertEqual(after["otherVisibleTiles"], ["E", "F"])
        self.assertEqual(after["acceptedTiles"], 4)
        self.assertEqual(before["opponentDiscards"][0]["discards"], ["E", "F"])
        self.assertEqual(operator.previous_public_observation, after)
        operator.public_recognition_result = {"generation": 2, "result": before}
        operator.poll_public_recognition()
        self.assertEqual(operator.cached_public_observation, after)
        for pending in [{"tile": "F", "fromSeat": "north"}, {"tile": "F", "fromSeat": "south"}]:
            operator.reconcile_confirmed_call_discard(pending)
            self.assertEqual(operator.cached_public_observation, after)
        fresh = {**after, "ownMeldTiles": ["F", "F", "F"],
                 "ownMelds": [{"type": "pon", "tiles": ["F", "F", "F"]}]}
        merged = merge_public_observations(after, fresh)
        self.assertEqual(merged["otherVisibleTiles"].count("F"), 4)
        interior = {"opponentDiscards": [{"seat": "north", "discards": ["F", "E"]}]}
        operator.cached_public_observation = interior
        operator.reconcile_confirmed_call_discard({"tile": "F", "fromSeat": "north"})
        self.assertIs(operator.cached_public_observation, interior)

    def test_async_public_cache_retains_previous_snapshot_for_call_policy(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_recognition_lock = threading.Lock()
        operator.public_cache_generation = 2
        before = {"opponentDiscards": [{"seat": "south", "discards": ["E"]}]}
        after = {"opponentDiscards": [{"seat": "south", "discards": ["E", "P"]}]}
        operator.cached_public_observation = before
        operator.previous_public_observation = None
        operator.log = Mock()
        operator.public_recognition_result = {"generation": 1, "result": after}
        operator.poll_public_recognition()
        self.assertIsNone(operator.previous_public_observation)
        operator.public_recognition_result = {"generation": 2, "result": after}
        operator.poll_public_recognition()
        self.assertIs(operator.previous_public_observation, before)
        self.assertEqual(operator.infer_pending_discard(
            operator.previous_public_observation, operator.cached_public_observation,
        ), {"tile": "P", "fromSeat": "south"})
        operator.public_recognition_result = {"generation": 2, "result": after}
        operator.poll_public_recognition()
        self.assertEqual(operator.infer_pending_discard(
            operator.previous_public_observation, operator.cached_public_observation,
        ), {"tile": "P", "fromSeat": "south"})
        operator.public_recognition_result = {"generation": 2, "result": {
            **after, "ownDiscards": ["1m"],
        }}
        operator.poll_public_recognition()
        self.assertIsNone(operator.infer_pending_discard(
            operator.previous_public_observation, operator.cached_public_observation,
        ))

    def test_pending_own_discard_requires_two_matching_public_river_scans(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_recognition_lock = threading.Lock()
        operator.public_cache_generation = 3
        operator.cached_open_melds = 0
        operator.cached_public_observation = {"ownDiscards": ["1m"]}
        operator.previous_public_observation = None
        operator.pending_own_discard = {"tile": "2p", "before": ["1m"]}
        operator.cached_concealed_tiles = ["1p"] * 13
        operator.pending_own_river_confirmation = None
        operator.log = Mock()
        observed = {"ownDiscards": ["1m", "2p"], "opponentDiscards": []}

        # A click with no observed river candidate must not consume the whole
        # game timer if its visual post-click confirmation was false.
        self.assertFalse(operator.own_discard_reconciliation_pending())

        operator.public_recognition_result = {"generation": 3, "result": observed}
        operator.poll_public_recognition()
        self.assertEqual(operator.cached_public_observation["ownDiscards"], ["1m"])
        self.assertEqual(operator.pending_own_river_confirmation, ["1m", "2p"])
        self.assertTrue(operator.own_discard_reconciliation_pending())
        self.assertTrue(any(call.args[0] == "public_own_river_append_pending"
                            for call in operator.log.call_args_list))

        operator.public_recognition_result = {"generation": 3, "result": observed}
        operator.poll_public_recognition()
        self.assertEqual(operator.cached_public_observation["ownDiscards"], ["1m", "2p"])
        self.assertIsNone(operator.pending_own_river_confirmation)
        self.assertTrue(any(call.args[0] == "public_own_river_append_confirmed"
                            for call in operator.log.call_args_list))
        operator.reconcile_own_discard()
        self.assertFalse(operator.own_discard_reconciliation_pending())

    def test_called_own_discard_retires_unconfirmed_candidate_from_actual_scans(self) -> None:
        project = Path(__file__).resolve().parents[1]
        fixture = load_json(project / "test/fixtures/called-own-discard-public-scans-20261020.json")
        scans = [item["response"]["result"] for item in fixture["scans"]]
        baseline = scans[1]["ownDiscards"]
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_recognition_lock = threading.Lock()
        operator.public_cache_generation = 3
        operator.cached_open_melds = 1
        operator.cached_public_observation = {"ownDiscards": baseline}
        operator.previous_public_observation = None
        operator.pending_own_discard = {"tile": "3m", "before": baseline}
        operator.cached_concealed_tiles = ["2p"] * 10
        operator.pending_own_river_confirmation = None
        operator.log = Mock()

        for index, scan in enumerate(scans):
            operator.public_recognition_result = {"generation": 3, "result": scan}
            operator.poll_public_recognition()
            self.assertEqual(operator.own_discard_reconciliation_pending(), index < 2)
            self.assertEqual(operator.cached_public_observation["ownDiscards"], baseline)
        self.assertIsNone(operator.cached_concealed_tiles)
        self.assertIsNone(operator.pending_own_discard)
        self.assertTrue(any(c.args[0] == "own_discard_reconciliation_unresolved"
                            for c in operator.log.call_args_list))
        self.assertFalse(any(c.args[0] == "own_discard_reconciled" for c in operator.log.call_args_list))

        # A later real discard belongs to its own receipt, never to the called
        # 3m. Independent matching scans are still required to confirm it.
        operator.pending_own_discard = {"tile": "8m", "before": baseline}
        for stamp in ("2026-10-20T08:32:25+00:00", "2026-10-20T08:32:26+00:00"):
            operator.public_recognition_result = {"generation": 3, "result": {
                "ownDiscards": [*baseline, "8m"], "capturedAt": stamp,
            }}
            operator.poll_public_recognition()
        operator.reconcile_own_discard()
        self.assertIsNone(operator.pending_own_discard)
        self.assertFalse(any(c.args[0] == "own_discard_mismatch" for c in operator.log.call_args_list))

    def test_withdrawn_river_candidate_requires_two_distinct_exact_baseline_scans(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_recognition_lock = threading.Lock()
        operator.public_cache_generation = 3
        operator.cached_open_melds = 0
        operator.cached_public_observation = {"ownDiscards": ["1m", "2p"]}
        operator.previous_public_observation = None
        operator.pending_own_discard = {"tile": "3m", "before": ["1m", "2p"]}
        operator.pending_own_river_confirmation = ["1m", "2p", "3m"]
        operator.cached_concealed_tiles = ["1p"] * 13
        operator.log = Mock()

        def scan(tiles, stamp):
            operator.public_recognition_result = {"generation": 3, "result": {
                "ownDiscards": tiles, "capturedAt": stamp,
            }}
            operator.poll_public_recognition()

        scan(["1m", "2p"], "10")
        scan(["1m", "2p"], "10")  # Repeated capture is not independent.
        scan(["1m", "2p"], "09")  # Nor is an older capture.
        self.assertTrue(operator.own_discard_reconciliation_pending())
        scan(["1m"], "11")  # Partial/missing/misread rivers cannot retire it.
        scan([], "12")
        scan(["9m", "2p"], "13")
        scan(["1m", "2p"], None)
        scan(["1m", "2p"], "14")
        self.assertTrue(operator.own_discard_reconciliation_pending())
        scan(["1m", "2p", "4m"], "15")  # A new candidate resets withdrawal evidence.
        scan(["1m", "2p"], "16")
        self.assertTrue(operator.own_discard_reconciliation_pending())
        scan(["1m", "2p"], "17")
        self.assertFalse(operator.own_discard_reconciliation_pending())
        self.assertIsNone(operator.cached_concealed_tiles)

    def test_public_cache_only_grows_rivers_and_preserves_riichi(self) -> None:
        previous = {
            "doraIndicators": ["4m"], "ownDiscards": ["1p"], "ownRiichiDeclared": True,
            "ownMeldTiles": [], "ownMelds": [],
            "opponentDiscards": [
                {"seat": "south", "discards": ["E"], "riichiDeclared": True, "melds": []},
            ],
        }
        current = {
            "doraIndicators": [], "ownDiscards": ["1p", "2p"], "ownRiichiDeclared": False,
            "ownMeldTiles": [], "ownMelds": [],
            "opponentDiscards": [
                {"seat": "south", "discards": [], "riichiDeclared": False, "melds": []},
            ],
            "capturedAt": "now", "recognitionLatencyMs": 350,
            "handPlan": {"planId": "tanyao", "confidence": 0.7},
        }

        merged = merge_public_observations(previous, current)

        self.assertEqual(merged["doraIndicators"], ["4m"])
        self.assertEqual(merged["ownDiscards"], ["1p", "2p"])
        self.assertEqual(merged["opponentDiscards"][0]["discards"], ["E"])
        self.assertTrue(merged["opponentDiscards"][0]["riichiDeclared"])
        self.assertTrue(merged["ownRiichiDeclared"])
        self.assertEqual(merged["handPlan"]["planId"], "tanyao")

    def test_saved_longer_river_consensus_repairs_stale_initial_dragon(self) -> None:
        root = Path(__file__).resolve().parents[1]
        fixture = load_json(root / "test/fixtures/opponent-river-stale-prefix-20261021.json")
        first, second = [item["observation"] for item in fixture["captures"][1:]]
        previous = {**fixture["captures"][0]["observation"], "opponentDiscards": [
            {"seat": opponent["seat"], "discards": opponent["discards"],
             "melds": opponent.get("melds", [])}
            for opponent in fixture["initialState"]["opponents"]
        ]}
        pending = merge_public_observations(previous, first)
        self.assertEqual(pending["opponentDiscards"][2]["discards"], ["F"])
        self.assertEqual(pending["opponentRiverRepairs"], [])
        repaired = merge_public_observations(pending, second)
        self.assertEqual(repaired["opponentDiscards"][2]["discards"], ["9m", "7m", "8m", "5m"])
        self.assertEqual(repaired["opponentRiverRepairs"], [{
            "seat": "west", "before": ["F"], "after": ["9m", "7m", "8m", "5m"],
            "firstCapturedAt": first["capturedAt"], "confirmedCapturedAt": second["capturedAt"],
        }])
        self.assertEqual(repaired["_opponentRiverCandidates"], {})
        self.assertEqual(repaired["otherVisibleTiles"].count("F"), 4)
        self.assertEqual(repaired["acceptedTiles"], len(repaired["doraIndicators"])
                         + len(repaired["ownDiscards"]) + len(repaired["otherVisibleTiles"]))

    def test_river_repair_rejects_incomplete_short_or_disagreeing_evidence(self) -> None:
        def observation(river, stamp, observed=True):
            return {"capturedAt": stamp, "opponentDiscards": [
                {"seat": "south", "discards": river, "discardsObserved": observed},
            ]}
        prior = observation(["F"], "2026-10-21T09:00:00+00:00")
        for invalid in [observation(["9m"], "2026-10-21T09:00:01+00:00"),
                        observation(["9m", "7m"], "2026-10-21T09:00:01+00:00"),
                        observation(["9m", "7m", "8m"], "2026-10-21T09:00:01+00:00", False),
                        observation(["9m", "7m", "8m"], None)]:
            pending = merge_public_observations(prior, invalid)
            self.assertEqual(pending["opponentDiscards"][0]["discards"], ["F"])
            self.assertEqual(pending["_opponentRiverCandidates"], {})
        first = observation(["9m", "7m", "8m"], "2026-10-21T09:00:01+00:00")
        pending = merge_public_observations(prior, first)
        changed = observation(["9m", "7m", "6m"], "2026-10-21T09:00:03+00:00")
        self.assertEqual(merge_public_observations(pending, changed)["opponentRiverRepairs"], [])
        # An unsafe intervening scan breaks corroboration instead of allowing
        # two unrelated safe captures to repair the river around it.
        interrupted = merge_public_observations(pending, {**first, "capturedAt": None})
        self.assertEqual(merge_public_observations(interrupted,
                         {**first, "capturedAt": "2026-10-21T09:00:04+00:00"})["opponentRiverRepairs"], [])

    def test_river_repair_needs_recent_distinct_ordered_captures(self) -> None:
        prior = {"opponentDiscards": [{"seat": "south", "discards": ["F"]}]}
        first = {"capturedAt": "2026-10-21T09:00:01+00:00", "opponentDiscards": [
            {"seat": "south", "discards": ["9m", "7m", "8m"], "discardsObserved": True},
        ]}
        pending = merge_public_observations(prior, first)
        for stamp in [first["capturedAt"], "2026-10-21T09:00:00+00:00",
                      "2026-10-21T09:00:01.499+00:00", "not-a-date", "2026-10-21T09:00:04",
                      "2026-10-21T09:00:32+00:00"]:
            with self.subTest(stamp=stamp):
                result = merge_public_observations(pending, {**first, "capturedAt": stamp})
                self.assertEqual(result["opponentRiverRepairs"], [])
                self.assertEqual(result["opponentDiscards"][0]["discards"], ["F"])
        result = merge_public_observations(pending, {**first, "capturedAt": "2026-10-21T09:00:03+00:00"})
        self.assertEqual(result["opponentDiscards"][0]["discards"], ["9m", "7m", "8m"])

    def test_river_consensus_cannot_replace_own_or_established_opponent_history(self) -> None:
        prior = {"ownDiscards": ["F"], "doraIndicators": ["F"], "opponentDiscards": [
            {"seat": "south", "discards": ["F", "C", "P"]},
        ]}
        current = {"ownDiscards": ["9m", "7m", "8m", "5m", "P"], "doraIndicators": ["9m"],
                   "capturedAt": "2026-10-21T09:00:01+00:00", "opponentDiscards": [
                       {"seat": "south", "discards": ["9m", "7m", "8m", "5m", "P"], "discardsObserved": True},
                   ]}
        pending = merge_public_observations(prior, current)
        result = merge_public_observations(pending, {**current, "capturedAt": "2026-10-21T09:00:03+00:00"})
        self.assertEqual(result["ownDiscards"], ["F"])
        self.assertEqual(result["doraIndicators"], ["F"])
        self.assertEqual(result["opponentDiscards"][0]["discards"], ["F", "C", "P"])
        self.assertEqual(result["opponentRiverRepairs"], [])

    def test_closed_hand_clears_phantom_own_kan_from_public_cache(self) -> None:
        previous = {
            "ownMelds": [{"type": "minkan", "tiles": ["P"] * 4, "confidence": 0.7}],
            "ownMeldTiles": ["P"] * 4,
            "opponentDiscards": [],
        }
        current = {
            "ownMelds": [], "ownMeldTiles": [], "ownMeldsObserved": True,
            "opponentDiscards": [],
        }
        merged = merge_public_observations(previous, current, confirmed_open_melds=0)
        self.assertEqual(merged["ownMelds"], [])
        self.assertEqual(merged["ownMeldTiles"], [])
        self.assertEqual(merged["allMeldTiles"], [])

        confirmed = merge_public_observations(previous, current, confirmed_open_melds=1)
        self.assertEqual(confirmed["ownMeldTiles"], ["P"] * 4)

    def test_confirmed_empty_opponent_meld_region_clears_phantom_kan(self) -> None:
        previous = {
            "ownMelds": [], "ownMeldTiles": [],
            "opponentDiscards": [{
                "seat": "east", "discards": ["9s"],
                "melds": [{"type": "minkan", "tiles": ["P"] * 4}],
                "meldsObserved": False,
            }],
        }
        current = {
            "ownMelds": [], "ownMeldTiles": [],
            "opponentDiscards": [{
                "seat": "east", "discards": ["9s"],
                "melds": [], "meldsObserved": True,
            }],
        }
        merged = merge_public_observations(previous, current)
        self.assertEqual(merged["opponentDiscards"][0]["melds"], [])
        self.assertEqual(merged["allMeldTiles"], [])

    def test_public_board_scan_runs_periodically_on_any_turn(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(public_cache=True, public_scan_interval=2.0)
        operator.public_recognition_server = Mock()
        operator.last_public_scan_at = 0.0
        operator.schedule_public_recognition = Mock()

        self.assertTrue(operator.schedule_periodic_public_recognition(b"first", now=10.0))
        self.assertFalse(operator.schedule_periodic_public_recognition(b"too-soon", now=11.9))
        self.assertTrue(operator.schedule_periodic_public_recognition(b"second", now=12.0))
        self.assertEqual(operator.schedule_public_recognition.call_count, 2)
        self.assertEqual(operator.schedule_public_recognition.call_args_list[0].args, (b"first",))
        self.assertEqual(operator.schedule_public_recognition.call_args_list[1].args, (b"second",))

    def test_pending_discard_temporarily_accelerates_unforced_public_scans(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(public_cache=True, public_scan_interval=2.0)
        operator.public_recognition_server = Mock()
        operator.last_public_scan_at = 10.0
        operator.pending_own_discard = {"tile": "9m", "before": ["3p"], "registeredMonotonic": 10.0}
        operator.schedule_public_recognition = Mock()

        self.assertFalse(operator.schedule_periodic_public_recognition(b"same", now=10.39))
        self.assertTrue(operator.schedule_periodic_public_recognition(b"new", now=10.41, verified_match=True))
        operator.schedule_public_recognition.assert_called_once_with(b"new", verified_match=True)
        operator.last_public_scan_at = 12.8
        self.assertFalse(operator.schedule_periodic_public_recognition(b"later", now=13.0))
        self.assertTrue(operator.schedule_periodic_public_recognition(b"later", now=14.8))

    def test_public_cache_scheduler_rejects_friend_room_even_when_forced(self) -> None:
        root = Path(__file__).resolve().parents[1]
        screenshot = (root / "artifacts/live/friend-room-public-cache-contamination-20260929.png").read_bytes()
        self.assertEqual(classify_screen(screenshot, {})[0], "unknown")
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_recognition_server = Mock()
        operator.public_recognition_server.poll.return_value = None
        operator.public_recognition_thread = None
        with patch("auto_operator.threading.Thread") as worker:
            for force in (False, True):
                operator.schedule_public_recognition(screenshot, force=force)
            for filename in ["300-fixed-e66ef28-room-settings-20260928.png", "draw-tenpai-result-20260928.png"]:
                frame = (root / "artifacts/live" / filename).read_bytes()
                self.assertNotEqual(classify_screen(frame, {})[0], "match")
                operator.schedule_public_recognition(frame, force=True)
            operator.schedule_public_recognition(b"invalid image", force=True)
            resized = io.BytesIO()
            Image.open(io.BytesIO(screenshot)).resize((960, 540)).save(resized, format="PNG")
            operator.schedule_public_recognition(resized.getvalue(), force=True)
            worker.assert_not_called()
        operator.public_recognition_server.stdin.write.assert_not_called()
        self.assertFalse(hasattr(operator, "public_cache_last_frame_hash"))
        self.assertFalse(hasattr(operator, "public_recognition_request_id"))

    def test_public_cache_scheduler_still_dispatches_verified_table(self) -> None:
        root = Path(__file__).resolve().parents[1]
        screenshot = (root / "artifacts/live/board-score-opposite-low-confidence-20260928.png").read_bytes()
        self.assertEqual(classify_screen(screenshot, {})[0], "match")
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_recognition_server = Mock()
        operator.public_recognition_server.poll.return_value = None
        operator.public_recognition_thread = None
        operator.public_cache_last_frame_hash = None
        operator.public_recognition_request_id = 0
        operator.public_cache_generation = 3
        with tempfile.TemporaryDirectory() as directory:
            operator.frames = Path(directory)
            with patch("auto_operator.threading.Thread") as worker:
                operator.schedule_public_recognition(screenshot)
                worker.assert_called_once()
                worker.return_value.start.assert_called_once()
            self.assertEqual(operator.public_recognition_request_id, 1)
            self.assertEqual(len(list(operator.frames.glob("*.public-cache.jpg"))), 1)

    def test_public_cache_scheduler_reuses_verified_match_state_for_same_frame(self) -> None:
        root = Path(__file__).resolve().parents[1]
        screenshot = (root / "artifacts/live/board-score-opposite-low-confidence-20260928.png").read_bytes()
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_recognition_server = Mock()
        operator.public_recognition_server.poll.return_value = None
        operator.public_recognition_thread = None
        operator.public_cache_last_frame_hash = None
        operator.public_recognition_request_id = 0
        operator.public_cache_generation = 3
        with tempfile.TemporaryDirectory() as directory:
            operator.frames = Path(directory)
            with patch("auto_operator.classify_screen", side_effect=AssertionError("duplicate classification")):
                with patch("auto_operator.threading.Thread") as worker:
                    operator.schedule_public_recognition(screenshot, verified_match=True)
                    worker.assert_called_once()
            self.assertEqual(operator.public_recognition_request_id, 1)

    def test_batched_draw_presence_keeps_exact_color_and_twenty_percent_boundaries(self) -> None:
        image = Image.new("RGB", (60, 10), (25, 55, 85))
        # Only the first two colors satisfy all three strict channel limits.
        for index, (color, qualifying_pixels) in enumerate([
            ((146, 146, 136), 20), ((255, 255, 255), 19),
            ((145, 146, 136), 100), ((146, 145, 136), 100),
            ((146, 146, 135), 100), ((146, 146, 136), 100),
        ]):
            for pixel in range(qualifying_pixels):
                image.putpixel((index * 10 + pixel % 10, pixel // 10), color)
        output = io.BytesIO()
        image.save(output, format="PNG")
        regions = [{"x": index * 10, "y": 0, "width": 10, "height": 10} for index in range(6)]
        self.assertEqual(draw_slots_occupied(output.getvalue(), regions),
                         [True, False, False, False, False, True])

    def test_draw_slot_presence_distinguishes_own_and_opponent_turns(self) -> None:
        region = {"x": 100, "y": 50, "width": 100, "height": 100}
        own_turn = io.BytesIO()
        image = Image.new("RGB", (300, 200), (25, 55, 85))
        ImageDraw.Draw(image).rectangle((100, 50, 200, 150), fill=(230, 225, 210))
        image.save(own_turn, format="PNG")
        self.assertTrue(is_draw_slot_occupied(own_turn.getvalue(), region))

        opponent_turn = io.BytesIO()
        Image.new("RGB", (300, 200), (25, 55, 85)).save(opponent_turn, format="PNG")
        self.assertFalse(is_draw_slot_occupied(opponent_turn.getvalue(), region))

    def test_open_hand_draw_slot_reuses_the_first_slot_after_compact_concealed_row(self) -> None:
        layout = {
            "viewport": {"width": 1920, "height": 1080},
            "handSlots": [
                {"x": 223 + index * 95, "y": 926, "width": 92, "height": 146}
                for index in range(13)
            ],
            "drawSlot": {"x": 1486, "y": 926, "width": 92, "height": 146},
        }

        self.assertEqual(open_hand_draw_slot(layout, 1), {
            "x": 1173.0, "y": 926.0, "width": 92.0, "height": 146.0,
        })
        self.assertEqual(open_hand_draw_slot(layout, 2), {
            "x": 888.0, "y": 926.0, "width": 92.0, "height": 146.0,
        })
        self.assertIsNone(open_hand_draw_slot(layout, 0))

    def test_winning_animation_does_not_look_like_verified_new_round(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        frames = project / "artifacts" / "friend-5-20" / "frames"
        for name in (
            "2026-09-21T05-41-02.311448+00-00.jpg",
            "2026-09-21T05-41-03.461291+00-00.jpg",
            "2026-09-21T05-41-04.636486+00-00.jpg",
            "2026-09-21T05-41-06.397759+00-00.jpg",
            "2026-09-21T05-41-07.758711+00-00.jpg",
        ):
            self.assertFalse(closed_concealed_row_visible((frames / name).read_bytes(), layout), name)
        self.assertTrue(closed_concealed_row_visible(
            (frames / "2026-09-21T05-41-16.298972+00-00.jpg").read_bytes(), layout,
        ))

    def test_shifted_open_hand_draw_slot_does_not_match_empty_opponent_turn(self) -> None:
        region = {"x": 1201, "y": 926, "width": 92, "height": 146}
        own_turn = io.BytesIO()
        image = Image.new("RGB", (1920, 1080), (25, 55, 85))
        ImageDraw.Draw(image).rectangle((1201, 926, 1293, 1072), fill=(230, 225, 210))
        image.save(own_turn, format="PNG")
        self.assertTrue(is_draw_slot_occupied(own_turn.getvalue(), region))

        opponent_turn = io.BytesIO()
        Image.new("RGB", (1920, 1080), (25, 55, 85)).save(opponent_turn, format="PNG")
        self.assertFalse(is_draw_slot_occupied(opponent_turn.getvalue(), region))

    def test_live_compact_hand_geometry_recovers_unpromoted_own_meld(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        frame = (project / "artifacts" / "debug-300-live-now2.png").read_bytes()

        self.assertEqual(geometric_open_meld_count(frame, layout), 1)

    def test_compact_self_draw_survives_exposed_meld_overlap_after_draw_slot(self) -> None:
        layout = {
            "viewport": {"width": 1920, "height": 1080},
            "handSlots": [
                {"x": 220 + index * 95, "y": 926, "width": 92, "height": 146}
                for index in range(13)
            ],
            "drawSlot": {"x": 1485, "y": 926, "width": 92, "height": 146},
        }
        image = Image.new("RGB", (1920, 1080), (25, 55, 85))
        draw = ImageDraw.Draw(image)
        # One pon leaves ten concealed tiles plus the compact draw at slot 10.
        for slot in layout["handSlots"][:11]:
            draw.rectangle((slot["x"], slot["y"], slot["x"] + slot["width"], slot["y"] + slot["height"]),
                           fill=(230, 225, 210))
        # The actual exposed pon can cover the felt immediately to the draw's
        # right. It must not turn a genuine self draw into an opponent turn.
        overlap = layout["handSlots"][11]
        draw.rectangle((overlap["x"], overlap["y"], overlap["x"] + overlap["width"],
                        overlap["y"] + overlap["height"]), fill=(230, 225, 210))
        draw.rectangle((1540, 910, 1880, 1070), fill=(230, 225, 210))
        encoded = io.BytesIO()
        image.save(encoded, format="PNG")

        self.assertEqual(geometric_open_meld_count(encoded.getvalue(), layout), 1)

    def test_restart_geometry_recovers_three_melds_despite_closed_slot_overlap(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        frames = project / "artifacts" / "friend-5-20" / "frames"
        for name in (
            "2026-09-21T05-46-30.872131+00-00.jpg",
            "2026-09-21T05-46-33.088404+00-00.jpg",
        ):
            self.assertEqual(geometric_open_meld_count((frames / name).read_bytes(), layout), 3)

    def test_closed_new_round_requires_two_frames_and_clears_prior_meld_evidence(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        frames = project / "artifacts" / "friend-5-20" / "frames"
        first = (frames / "2026-09-21T06-15-22.969232+00-00.jpg").read_bytes()
        second = (frames / "2026-09-21T06-15-24.317758+00-00.jpg").read_bytes()
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = layout
        operator.closed_new_round_candidate_frames = set()

        self.assertFalse(operator.stable_closed_new_round(first))
        self.assertTrue(operator.stable_closed_new_round(second))
        # An open hand in the same round must not satisfy the reset proof.
        open_frame = (frames / "2026-09-21T05-46-33.088404+00-00.jpg").read_bytes()
        self.assertFalse(operator.stable_closed_new_round(open_frame))

    def test_pending_post_chi_cannot_be_reset_by_stale_closed_row_evidence(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        frame = (project / "artifacts" / "friend-5-20" / "frames" /
                 "2026-09-21T08-18-08.901402+00-00.png").read_bytes()
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = layout
        operator.cached_open_melds = 1
        operator.pending_post_call_discard = True
        operator.closed_new_round_candidate_frames = {"stale-before-call-a", "stale-before-call-b"}

        self.assertFalse(operator.should_reset_open_hand_state(frame))
        self.assertEqual(operator.closed_new_round_candidate_frames, set())

    def test_live_first_chi_selector_exposes_only_complete_two_tile_choices(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frame = (project / "artifacts" / "friend-5-20" / "frames" /
                 "2026-09-21T08-18-13.104524+00-00.public-cache.jpg").read_bytes()
        started = time.monotonic()
        choices = force_auto_chi_choice_points(frame, {"width": 1920, "height": 1080})

        self.assertEqual(len(choices), 3)
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertTrue(all(650 <= choice["x"] <= 1230 for choice in choices))
        self.assertTrue(all(790 <= choice["y"] <= 800 for choice in choices))

    def test_restart_after_call_has_stable_meld_surface_without_closed_round_proof(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        frames = project / "artifacts" / "friend-5-20" / "frames"
        first = (frames / "2026-09-21T06-21-57.847655+00-00.jpg").read_bytes()
        second = (frames / "2026-09-21T06-22-00.877593+00-00.jpg").read_bytes()
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = layout
        operator.cached_open_melds = 0
        operator.open_meld_candidate = None
        operator.open_meld_candidate_frames = set()

        started = time.monotonic()
        self.assertTrue(own_meld_surface_visible(first, layout))
        self.assertTrue(own_meld_surface_visible(second, layout))
        self.assertFalse(closed_concealed_row_visible(first, layout))
        compact_region = stable_hand_comparison_region(layout, 2)
        self.assertLess(mean_pixel_delta(
            crop_screenshot(first, compact_region), crop_screenshot(second, compact_region),
        ), 1.5)
        self.assertFalse(operator.stable_open_meld_count(2, first))
        self.assertEqual(operator.stable_open_meld_count(2, second), 2)
        self.assertTrue(discard_point_in_hand_geometry({"x": 838, "y": 996.5}, layout, 2))
        self.assertLess(time.monotonic() - started, 5.0)

    def test_two_meld_stream_tracks_compact_draw_and_skips_opponent_recognition(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config/layout-300-regression.json")
        opponent = (project / "test/fixtures/two-meld-opponent-turn-20261020.jpg").read_bytes()
        own = (project / "test/fixtures/two-meld-own-draw-20261020.jpg").read_bytes()
        # The old closed draw ROI contains our exposed white pon on both frames.
        self.assertTrue(is_draw_slot_occupied(opponent, layout["drawSlot"]))
        self.assertTrue(is_draw_slot_occupied(own, layout["drawSlot"]))
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(mode="force-auto", max_iterations=2, poll=0.001)
            operator.layout = layout
            operator.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
            operator.action_clip = None
            operator.frames = Path(directory)
            operator.screen_references = {}
            operator.screencast_session = Mock()
            operator.screencast_sequence = 0
            operator.screencast_draw_occupied = None
            operator.screencast_draw_generation = 0
            operator.cached_public_observation = None
            operator.cached_concealed_tiles = None
            operator.cached_open_melds = 2
            operator.dynamic_layout_required = True
            operator.pending_post_call_discard = False
            operator.pending_post_call_started_at = None
            operator.restart_open_hand_probe_hash = None
            operator.last_processed_hand = None
            operator.armed = True
            operator.previous_public_observation = None
            operator.last_shanten = None
            operator.poll_public_recognition = Mock()
            operator.ensure_viewport = Mock()
            operator.start_screencast_gate = Mock()
            operator.schedule_periodic_public_recognition = Mock()
            operator.resume_if_away = Mock(return_value=False)
            operator.advance_ranked_loop = Mock(return_value=False)
            operator.recognize_resident = Mock()
            operator.force_auto_reaction_fallback = Mock(return_value=None)
            operator.log = Mock()
            self.assertTrue(operator.accept_screencast_frame(opponent))
            self.assertFalse(operator.screencast_draw_occupied)
            self.assertEqual(operator.screencast_draw_generation, 0)
            self.assertTrue(operator.accept_screencast_frame(own))
            self.assertTrue(operator.screencast_draw_occupied)
            self.assertEqual(operator.screencast_draw_generation, 1)
            operator.accept_screencast_frame(own)
            self.assertEqual(operator.screencast_draw_generation, 1)
            operator.accept_screencast_frame(opponent)
            self.assertFalse(operator.screencast_draw_occupied)
            page = Mock()
            page.url = "https://mahjongsoul.game.yo-star.com/"
            with patch("auto_operator.classify_screen", return_value=("match", 1.0)):
                operator.run(page)
            operator.recognize_resident.assert_not_called()
            operator.accept_screencast_frame(own)
            self.assertTrue(operator.screencast_draw_occupied)
            self.assertEqual(operator.screencast_draw_generation, 2)

    def test_run_loop_revisits_identical_hand_after_a_new_streamed_draw(self) -> None:
        project = Path(__file__).resolve().parents[1]
        fixtures = FRAME_FIXTURES / "repeated-draw-20261023"
        first = (fixtures / "first-two-man.jpg").read_bytes()
        opponent = (fixtures / "opponent-turn.jpg").read_bytes()
        next_draw = (fixtures / "next-two-man.jpg").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(mode="force-auto", max_iterations=2, poll=0.001,
                                               stop_on_error=True)
            operator.layout = load_json(project / "config/layout.json")
            operator.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
            operator.action_clip = {"x": 1170, "y": 775, "width": 275, "height": 105}
            operator.frames = Path(directory)
            operator.screen_references = {}
            operator.screencast_session = Mock()
            operator.screencast_sequence = 0
            operator.screencast_draw_occupied = None
            operator.screencast_draw_generation = 0
            operator.cached_public_observation = None
            operator.cached_concealed_tiles = None
            operator.cached_open_melds = 1
            operator.dynamic_layout_required = True
            operator.pending_post_call_discard = False
            operator.pending_post_call_started_at = None
            operator.restart_open_hand_probe_hash = None
            operator.last_processed_hand = None
            operator.armed = True
            operator.previous_public_observation = None
            operator.last_shanten = None
            operator.pointer_retreat_screencast_sequence = 0
            operator.login_button_clicked_at = None
            operator.poll_public_recognition = Mock()
            operator.reconcile_own_discard = Mock()
            operator.ensure_viewport = Mock()
            operator.start_screencast_gate = Mock()
            operator.schedule_periodic_public_recognition = Mock()
            operator.resume_if_away = Mock(return_value=False)
            operator.advance_ranked_loop = Mock(return_value=False)
            # Stop at recognition: this tests the real stream/duplicate gate
            # without OCR, model execution, browser access, or a tile click.
            operator.recognize_resident = Mock(return_value={"status": "not_ready"})
            operator.force_auto_reaction_fallback = Mock(return_value=None)
            operator.force_auto_riichi_kan_fallback = Mock(return_value=None)
            operator.log = Mock()
            page = Mock()
            page.url = "https://mahjongsoul.game.yo-star.com/"
            page.wait_for_timeout.side_effect = lambda _: operator.accept_screencast_frame(
                operator.latest_screencast_frame,
            )
            with patch("auto_operator.classify_screen", return_value=("match", 1.0)), \
                    patch("auto_operator.StartupTurnGuard") as guard:
                guard.return_value.observe.return_value = "ready"
                operator.accept_screencast_frame(first)
                operator.run(page)
                self.assertEqual(operator.screencast_draw_generation, 1)
                operator.recognize_resident.assert_called_once()
                first_identity = operator.last_processed_hand

                # Another stable frame of the same draw is still suppressed.
                operator.armed = False
                operator.run(page)
                operator.recognize_resident.assert_called_once()
                self.assertEqual(operator.last_processed_hand, first_identity)

                operator.accept_screencast_frame(opponent)
                self.assertFalse(operator.screencast_draw_occupied)
                operator.accept_screencast_frame(next_draw)
                self.assertEqual(operator.screencast_draw_generation, 2)
                operator.run(page)
                self.assertEqual(operator.recognize_resident.call_count, 2)
                self.assertEqual(operator.reconcile_own_discard.call_count, 2)
                self.assertNotEqual(operator.last_processed_hand, first_identity)

    def test_run_loop_reaches_post_pon_next_draw_with_trusted_open_meld_count(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        frame = (project / "artifacts" / "debug-300-current5.png").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(mode="force-auto", max_iterations=2, poll=0.001)
            operator.layout = layout
            operator.hand_clip = {
                "x": 223, "y": 926, "width": 1355, "height": 146,
            }
            operator.action_clip = None
            operator.frames = Path(directory)
            operator.screen_references = {}
            operator.screencast_session = Mock()
            operator.latest_screencast_frame = frame
            operator.latest_screencast_captured_at = 123.456
            operator.screencast_sequence = 1
            operator.screencast_draw_occupied = False
            operator.screencast_draw_generation = 0
            operator.cached_public_observation = None
            operator.cached_concealed_tiles = None
            operator.cached_open_melds = 1
            operator.dynamic_layout_required = False
            operator.pending_post_call_discard = False
            operator.pending_post_call_started_at = None
            operator.restart_open_hand_probe_hash = None
            operator.last_processed_hand = None
            operator.armed = True
            operator.previous_public_observation = None
            operator.last_shanten = None
            operator.poll_public_recognition = Mock()
            operator.ensure_viewport = Mock()
            operator.start_screencast_gate = Mock()
            operator.schedule_periodic_public_recognition = Mock()
            operator.resume_if_away = Mock(return_value=False)
            operator.advance_ranked_loop = Mock(return_value=False)
            operator.recognize_resident = Mock(return_value={"status": "not_ready"})
            operator.evaluate = Mock(return_value={"status": "not_ready"})
            operator.force_auto_reaction_fallback = Mock(return_value=None)
            operator.log = Mock()
            page = Mock()
            page.url = "https://mahjongsoul.game.yo-star.com/"

            with patch("auto_operator.classify_screen", return_value=("match", 1.0)) as classify:
                operator.run(page)

            operator.recognize_resident.assert_called_once()
            # A self-turn evaluator must age the same streamed frame that
            # supplied recognition.  Omitting this causes a full default
            # evaluator budget to run against an already-old ranked frame.
            self.assertEqual(operator.evaluate.call_args.kwargs["captured_at"], 123.456)
            # The two loop passes establish the stable streamed draw.  The
            # decision pass must reuse that gate's classification rather than
            # classifying the same bytes again in the full-screen branch.
            self.assertEqual(classify.call_count, 2)
            self.assertEqual(operator.recognize_resident.call_args.kwargs["open_melds"], 1)
            self.assertTrue(operator.dynamic_layout_required)
            self.assertEqual(operator.cached_open_melds, 1)
            self.assertTrue(any(
                call.args and call.args[0] == "open_hand_geometry_gate"
                for call in operator.log.call_args_list
            ))

    def test_run_loop_supersedes_vanished_reaction_with_later_verified_draw(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        frames = project / "artifacts" / "friend-5-20" / "frames"
        first = (frames / "2026-09-21T05-46-30.872131+00-00.jpg").read_bytes()
        second = (frames / "2026-09-21T05-46-33.088404+00-00.jpg").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(mode="force-auto", max_iterations=2, poll=0.001,
                                               stop_on_error=True)
            operator.layout = layout
            operator.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
            operator.action_clip = None
            operator.frames = Path(directory)
            operator.screen_references = {}
            operator.screencast_session = Mock()
            operator.latest_screencast_frame = second
            operator.screencast_sequence = 2
            operator.screencast_draw_occupied = False
            operator.screencast_draw_generation = 1
            operator.cached_public_observation = {
                "capturedAt": datetime.now(timezone.utc).isoformat(),
                "ownDiscards": ["1m"], "doraIndicators": ["2m"],
            }
            operator.cached_concealed_tiles = None
            operator.cached_open_melds = 0
            operator.dynamic_layout_required = False
            operator.pending_post_call_discard = False
            operator.pending_post_call_started_at = None
            operator.restart_open_hand_probe_hash = None
            operator.open_meld_candidate = 3
            operator.open_meld_candidate_frames = {hashlib.sha256(first).hexdigest()}
            operator.last_processed_hand = None
            operator.armed = True
            operator.previous_public_observation = None
            operator.last_shanten = None
            operator.round_terminal_latched = False
            # Reproduce the live sequence: a reaction prompt was latched, then
            # disappeared, and this later frame is a verified self draw.
            operator.action_evidence_started_at = time.monotonic() - 11.0
            operator.action_evidence_last_seen_at = time.monotonic() - 10.0
            operator.action_evidence_kind = "reaction"
            operator.action_evidence_generation = 1
            operator.last_action_clicked_at = None
            operator.poll_public_recognition = Mock()
            operator.ensure_viewport = Mock()
            operator.start_screencast_gate = Mock()
            operator.schedule_periodic_public_recognition = Mock()
            operator.resume_if_away = Mock(return_value=False)
            operator.advance_ranked_loop = Mock(return_value=False)
            operator.force_auto_reaction_fallback = Mock(return_value=None)
            operator.recognize_resident = Mock(return_value={
                "status": "decision", "openMelds": 3,
                "recognition": {"tiles": ["1p"] * 5},
                "decision": {"selectedAction": {"action": "discard", "tile": "1p"}},
                "clickIndex": 0,
            })
            operator.execute = Mock(return_value={
                "clicked": True, "confirmation": "hand_and_own_river_changed",
            })
            operator.record_replay = Mock(return_value=Path(directory) / "replay.json")
            operator.log = Mock()
            page = Mock()
            page.url = "https://mahjongsoul.game.yo-star.com/"

            started = time.monotonic()
            with patch("auto_operator.classify_screen", return_value=("match", 1.0)):
                operator.run(page)

            operator.execute.assert_called_once()
            self.assertEqual(
                operator.recognize_resident.call_args.kwargs["public_observation"],
                operator.cached_public_observation,
            )
            self.assertEqual(operator.cached_open_melds, 3)
            self.assertLess(time.monotonic() - started, 5.0)
            logged = next(call for call in operator.log.call_args_list
                          if call.args and call.args[0] == "decision")
            self.assertTrue(logged.kwargs["execution"]["actionTiming"]["deadlineMet"],
                            operator.log.call_args_list)
            self.assertEqual(logged.kwargs["execution"]["actionTiming"]["actionKind"], "discard")
            self.assertTrue(any(
                call.args and call.args[0] == "action_deadline_superseded"
                for call in operator.log.call_args_list
            ))

    def test_expired_deadline_is_fail_closed_before_click(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.action_evidence_started_at = time.monotonic() - 5.1
        operator.action_evidence_kind = "reaction"
        operator.last_action_clicked_at = None
        operator.log = Mock()
        with self.assertRaisesRegex(RetryableSafetyAbort, "deadline expired"):
            operator.require_action_deadline()
        self.assertTrue(any(call.args[0] == "action_deadline_expired"
                            for call in operator.log.call_args_list))

    def test_ranked_click_budget_rejects_stale_evaluated_capture(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(force_auto_click_budget_ms=2600)
        operator.log = Mock()

        with patch("auto_operator.time.monotonic", return_value=12.601):
            with self.assertRaisesRegex(RetryableSafetyAbort, "click budget expired"):
                operator.require_force_auto_click_budget(10.0, phase="before_discard_click")

        operator.log.assert_called_once_with(
            "force_auto_click_budget_expired",
            phase="before_discard_click",
            clickBudgetMs=2600,
            captureAgeBeforeDecisionMs=2601,
            decisionBudgetMs=0,
        )

    def test_ranked_click_budget_keeps_fresh_evaluated_capture(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(force_auto_click_budget_ms=2600)
        operator.log = Mock()

        with patch("auto_operator.time.monotonic", return_value=12.599):
            operator.require_force_auto_click_budget(10.0, phase="before_discard_click")

        operator.log.assert_not_called()

    def test_long_friend_first_turn_keeps_separate_deadline_and_observed_budget(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(force_auto_click_budget_ms=8000, action_deadline_ms=300000)
        operator.log = Mock()
        with patch("auto_operator.time.monotonic", return_value=17.0):
            operator.mark_action_evidence("discard", observed_at=0.0, budget_observed_at=16.0)
            self.assertEqual(operator.action_deadline_remaining_ms(), 283000)
            self.assertEqual(operator.force_auto_action_evidence_age_ms(), 1000)
            operator.require_force_auto_click_budget(16.5, phase="before_recognition")
        with patch("auto_operator.time.monotonic", return_value=24.0):
            operator.mark_action_evidence("discard")
            with self.assertRaises(RetryableSafetyAbort):
                operator.require_force_auto_click_budget(23.9, phase="before_recognition")
            self.assertEqual(operator.action_deadline_remaining_ms(), 276000)
            operator.mark_action_evidence("win", supersede=True)
            self.assertEqual(operator.force_auto_action_evidence_age_ms(), 0)
            operator.action_timing(clear=True)
            self.assertIsNone(operator.action_budget_started_at)

    def test_default_start_anchor_remains_budget_anchor(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(force_auto_click_budget_ms=2600, action_deadline_ms=300000)
        operator.log = Mock()
        with patch("auto_operator.time.monotonic", return_value=17.0):
            operator.mark_action_evidence("discard", observed_at=0.0)
            with self.assertRaises(RetryableSafetyAbort):
                operator.require_force_auto_click_budget(16.9, phase="before_recognition")

    def test_short_discard_selection_reserves_confirmed_second_click(self) -> None:
        """Do not select a tile after the measured two-click reserve is gone."""
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(force_auto_click_budget_ms=2600)
        operator.action_evidence_started_at = 10.0
        operator.log = Mock()

        # This is the 5+20 failure shape: the first click would be within
        # 2600ms but leaves only 289ms to observe and hit the raised tile.
        with patch("auto_operator.time.monotonic", return_value=12.311):
            with self.assertRaisesRegex(RetryableSafetyAbort, "lacks time"):
                operator.require_force_auto_discard_selection_window(12.2)

        operator.log.assert_called_once_with(
            "force_auto_discard_selection_window_insufficient",
            clickBudgetMs=2600,
            reserveMs=650,
            captureAgeBeforeSelectionMs=111,
            actionEvidenceAgeMs=2311,
            remainingMs=289,
        )

    def test_short_click_budget_rejects_fresh_frame_after_old_self_turn_gate(self) -> None:
        """A later receipt cannot reset the 5+20 turn clock."""
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(force_auto_click_budget_ms=2600)
        operator.action_evidence_started_at = 10.0
        operator.log = Mock()

        with patch("auto_operator.time.monotonic", return_value=12.601):
            with self.assertRaisesRegex(RetryableSafetyAbort, "click budget expired"):
                # This frame itself is only 100ms old, but the self-turn
                # has already exceeded the short execution budget.
                operator.require_force_auto_click_budget(12.5, phase="before_discard_click")

        operator.log.assert_called_once_with(
            "force_auto_click_budget_expired",
            phase="before_discard_click",
            clickBudgetMs=2600,
            captureAgeBeforeDecisionMs=101,
            actionEvidenceAgeMs=2601,
            decisionBudgetMs=0,
        )

    def test_ranked_capture_age_uses_stream_receipt_not_temporary_file_time(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)

        with patch("auto_operator.time.monotonic", return_value=12.601):
            self.assertEqual(operator.force_auto_capture_age_ms(10.0), 2601)
            self.assertIsNone(operator.force_auto_capture_age_ms(None))

    def test_ranked_stale_receipt_defers_before_expensive_recognition(self) -> None:
        """An aging 2600ms receipt must not enter OCR/evaluation then expire."""
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", board_metadata=False,
                                           force_auto_click_budget_ms=2600)
        operator.log = Mock()
        operator.recognize_resident = Mock(side_effect=AssertionError("late recognition started"))
        screenshot = Path("/tmp/stale-ranked-receipt.jpg")

        # Only 300ms remain, far below the measured recognition + pre-click
        # window.  This must defer without calling the evaluator path that
        # would otherwise reach before_pre_click_validation too late.
        with patch("auto_operator.time.monotonic", return_value=12.3):
            self.assertIsNone(operator.recognize_force_auto_or_defer(
                screenshot, captured_at=10.0,
            ))

        operator.recognize_resident.assert_not_called()
        operator.log.assert_called_once_with(
            "recognition_deferred_insufficient_click_window",
            screenshot=str(screenshot),
            captureAgeMs=2300,
            clickBudgetMs=2600,
            requiredRecognitionWindowMs=1800,
        )

    def test_ranked_fresh_receipt_runs_after_matching_board_metadata_is_cached(self) -> None:
        """A normal 330--400ms screencast age must not starve short turns.

        Board OCR is deliberately deferred on a cold cache.  Once that
        matching cache is available, a new receipt with the upper end of the
        observed 420--547ms CDP delivery age has at least 2050ms left and
        must reach the parallel evaluator;
        the final click-budget guard remains the authority if it later ages
        out.
        """
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", board_metadata=True,
                                           force_auto_click_budget_ms=2600)
        operator.log = Mock()
        operator.cached_board_metadata = Mock(return_value={"round": "east_1"})
        operator.recognize_force_auto_parallel = Mock(return_value={"status": "decision"})
        screenshot = Path("/tmp/fresh-ranked-receipt.jpg")
        kwargs = dict(dynamic_layout=False, open_melds=None, public_observation=None,
                      force_auto_action_buttons=[], captured_at=10.0)

        with patch("auto_operator.time.monotonic", return_value=10.547):
            result = operator.recognize_force_auto_or_defer(screenshot, **kwargs)

        self.assertEqual(result, {"status": "decision"})
        operator.cached_board_metadata.assert_called_once_with(screenshot)
        operator.recognize_force_auto_parallel.assert_called_once_with(screenshot, **kwargs)
        self.assertFalse(any(
            call.args[0] == "recognition_deferred_insufficient_click_window"
            for call in operator.log.call_args_list
        ))

    def test_ranked_receipt_just_beyond_admission_age_defers(self) -> None:
        """The relaxed start rule admits the measured range, not stale frames."""
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", board_metadata=False,
                                           force_auto_click_budget_ms=2600)
        operator.log = Mock()
        operator.recognize_resident = Mock(side_effect=AssertionError("late recognition started"))
        screenshot = Path("/tmp/beyond-ranked-admission.jpg")

        # 801ms old leaves 1799ms: below the 1800ms recognition admission
        # window.  The final click guard remains unchanged and would reject
        # any later decision that actually consumes the 2600ms budget.
        with patch("auto_operator.time.monotonic", return_value=10.801):
            self.assertIsNone(operator.recognize_force_auto_or_defer(
                screenshot, captured_at=10.0,
            ))

        operator.recognize_resident.assert_not_called()
        operator.log.assert_called_once_with(
            "recognition_deferred_insufficient_click_window",
            screenshot=str(screenshot),
            captureAgeMs=801,
            clickBudgetMs=2600,
            requiredRecognitionWindowMs=1800,
        )

    def test_ranked_click_budget_stops_after_three_consecutive_expiries(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(force_auto_click_budget_ms=2600, ranked_loop=True)
        operator.log = Mock()

        with patch("auto_operator.time.monotonic", return_value=12.601):
            for _ in range(3):
                with self.assertRaisesRegex(RetryableSafetyAbort, "click budget expired"):
                    operator.require_force_auto_click_budget(10.0, phase="before_discard_click")

        self.assertEqual(operator.ranked_click_budget_expiry_streak, 3)
        self.assertTrue(operator.ranked_click_budget_safety_stop_requested)
        stop = operator.log.call_args_list[-1]
        self.assertEqual(stop.args[0], "ranked_click_budget_safety_stop")
        self.assertEqual(stop.kwargs["expiryStreak"], 3)
        self.assertEqual(stop.kwargs["reason"], "three_consecutive_force_auto_click_budget_expiries")

    def test_expired_ranked_optional_call_does_not_stop_the_operator(self) -> None:
        """A late chi/pon may be safely declined without leaving the match."""
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(force_auto_click_budget_ms=2600, ranked_loop=True)
        operator.log = Mock()

        with patch("auto_operator.time.monotonic", return_value=12.601):
            for _ in range(3):
                with self.assertRaisesRegex(RetryableSafetyAbort, "click budget expired"):
                    operator.require_force_auto_click_budget(
                        10.0, phase="before_reaction_call_click",
                    )

        self.assertEqual(getattr(operator, "ranked_click_budget_expiry_streak", 0), 0)
        self.assertFalse(getattr(operator, "ranked_click_budget_safety_stop_requested", False))
        self.assertFalse(any(call.args[0] == "ranked_click_budget_safety_stop"
                             for call in operator.log.call_args_list))

    def test_non_ranked_click_budget_expiry_does_not_request_safety_stop(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(force_auto_click_budget_ms=2600, ranked_loop=False)
        operator.log = Mock()

        with patch("auto_operator.time.monotonic", return_value=12.601):
            for _ in range(3):
                with self.assertRaisesRegex(RetryableSafetyAbort, "click budget expired"):
                    operator.require_force_auto_click_budget(10.0, phase="before_discard_click")

        self.assertFalse(getattr(operator, "ranked_click_budget_safety_stop_requested", False))
        self.assertFalse(any(call.args[0] == "ranked_click_budget_safety_stop"
                             for call in operator.log.call_args_list))

    def test_confirmed_ranked_action_resets_click_budget_expiry_streak(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.ranked_click_budget_expiry_streak = 2

        operator.reset_ranked_click_budget_expiry_streak()

        self.assertEqual(operator.ranked_click_budget_expiry_streak, 0)

    def test_ranked_click_budget_safety_stop_returns_before_away_resume(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", max_iterations=1, board_metadata=False)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.latest_screencast_frame = None
        operator.screencast_session = None
        operator.ranked_click_budget_safety_stop_requested = True
        operator.ensure_viewport = Mock()
        operator.start_screencast_gate = Mock()
        operator.poll_public_recognition = Mock()
        operator.resume_if_away = Mock()
        operator.log = Mock()
        page = Mock()
        page.url = "https://game.mahjongsoul.com/index.html"

        operator.run(page)

        operator.poll_public_recognition.assert_not_called()
        operator.resume_if_away.assert_not_called()
        page.mouse.click.assert_not_called()

    def test_execute_never_clicks_a_stale_ranked_capture(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(
            mode="force-auto", allow_local_discard=False, force_auto_click_budget_ms=2600,
        )
        operator.log = Mock()
        page = Mock()
        evaluation = {
            "decision": {"selectedAction": {"action": "discard", "tile": "1m"}},
            "recognition": {"tiles": ["1m"] * 14},
        }

        with patch("auto_operator.time.monotonic", return_value=12.7):
            with self.assertRaisesRegex(RetryableSafetyAbort, "click budget expired"):
                operator.execute(page, evaluation, evaluated_captured_at=10.0)

        page.mouse.click.assert_not_called()

    def test_reaction_pass_uses_its_fresh_button_confirmation_not_stale_evaluation(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(
            mode="force-auto", stability_pixel_delta=1.5, force_auto_click_budget_ms=2600,
        )
        operator.layout = {"actionButtonRegions": {"pass": {"x": 10, "y": 20, "width": 100, "height": 40}}}
        operator.log = Mock()
        # This is intentionally an old *self-turn* latch: the current UI is
        # a separately verified reaction prompt, so its PASS must use the
        # fresh button confirmation rather than the obsolete turn clock.
        operator.action_evidence_started_at = 10.0
        operator.confirm_action_button = Mock(return_value={"confirmation": "action_button_region_changed"})
        page = Mock()
        button = io.BytesIO()
        Image.new("RGB", (100, 40), "black").save(button, format="PNG")
        page.screenshot.return_value = button.getvalue()
        evaluation = {
            "recognition": {"safe": False, "tiles": ["1m"] * 13},
            "actionButton": {"action": "pass", "center": {"x": 60, "y": 40}},
        }

        # The evaluator's full-frame timestamp is already 2.7 seconds old,
        # but execute_reaction_pass has independently just sampled a stable
        # pass button.  Its short ranked budget begins at that confirmation.
        with patch("auto_operator.time.monotonic", return_value=12.7):
            receipt = operator.execute_reaction_pass(page, evaluation, evaluated_captured_at=10.0)

        self.assertTrue(receipt["clicked"])
        page.mouse.click.assert_called_once_with(60, 40)

    def test_riichi_discard_uses_confirmed_selection_ui_as_ranked_budget_baseline(self) -> None:
        """A confirmed Riichi selection can outlive its original evaluation."""
        project = Path(__file__).resolve().parents[1]
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(
            mode="force-auto", allow_local_discard=False, stability_pixel_delta=1.5,
            force_auto_click_budget_ms=2600,
        )
        operator.layout = load_json(project / "config/layout-300-regression.json")
        operator.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        operator.river_clip = {"x": 10, "y": 0, "width": 10, "height": 10}
        frame = (project / "test/fixtures/riichi-before-selection-20261020.jpg").read_bytes()
        selection = (project / "test/fixtures/riichi-two-candidates-selection-20261020.jpg").read_bytes()
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = frame
        operator.screencast_draw_generation = 4
        operator.cached_open_melds = 0
        operator.confirm_action_button = Mock(return_value={"confirmation": "riichi_selection_hand_changed"})
        operator.confirm_discard = Mock(return_value={"confirmation": "hand_and_own_river_changed"})
        operator.refresh_discard_reconciliation_before_click = Mock(return_value=False)
        operator.require_action_deadline = Mock()
        operator.log = Mock()
        page = Mock()
        button_buffer = io.BytesIO()
        Image.new("RGB", (100, 40), "orange").save(button_buffer, format="PNG")
        page.screenshot.side_effect = lambda **kwargs: button_buffer.getvalue() if "clip" in kwargs else selection
        evaluation = {
            "decision": {"selectedAction": {"action": "riichi", "tile": "1m"}},
            "recognition": {"tiles": ["1m", "3m", "0m", "6m", "7m", "3p", "4p", "1s", "1s", "1s", "5s", "6s", "7s", "2p"], "safe": False},
            "clickIndex": 0,
            "clickPoint": {"x": 269, "y": 999},
            "actionButton": {
                "action": "riichi", "x": 1087, "y": 788, "width": 352, "height": 57,
                "center": {"x": 1263, "y": 816.5},
            },
        }
        clock = {"now": 12.5}

        def classify_confirmed_selection(*_args):
            # Classification consumes the remaining time from the original
            # evaluated frame, but the verified selection screenshot itself
            # was captured at 12.5 and remains inside the 2600ms budget.
            # A Riichi declaration establishes a new baseline, but its tile
            # discard is still a two-click gesture and must retain the
            # confirmed-selection reserve for the raised hitbox.
            clock["now"] = 14.3
            return "match", 1.0

        with patch("auto_operator.time.monotonic", side_effect=lambda: clock["now"]), \
                patch("auto_operator.stable_hand_delta", return_value=0.0), \
                patch("auto_operator.send_discard_click", wraps=send_discard_click) as discard_click, \
                patch("auto_operator.raised_tile_confirmation_point",
                      return_value={"x": 269, "y": 971, "lift": 28, "faceStructureDelta": 0.0}), \
                patch("auto_operator.classify_screen", side_effect=classify_confirmed_selection), \
                patch("auto_operator.is_away_resume_dialog", return_value=False), \
                patch("auto_operator.discard_point_in_hand_geometry", return_value=True):
            receipt = operator.execute(
                page, evaluation,
                evaluated_hand=crop_screenshot(frame, operator.hand_clip),
                evaluated_full=frame,
                evaluated_draw_generation=4,
                evaluated_captured_at=10.0,
            )

        self.assertTrue(receipt["clicked"])
        self.assertEqual(discard_click.call_args.args[4], selection)
        # send_discard_click may issue its normal focus/click sequence after
        # the declaration; both phases reached the mouse without a budget
        # abort.
        self.assertGreaterEqual(page.mouse.click.call_count, 2)
        self.assertFalse(any(
            call.args and call.args[0] == "force_auto_click_budget_expired"
            for call in operator.log.call_args_list
        ))

    def test_confirmed_riichi_selection_uses_local_budget_only_for_long_friend_mode(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frame = (project / "test/fixtures/riichi-before-selection-20261020.jpg").read_bytes()
        selection = (project / "test/fixtures/riichi-two-candidates-selection-20261020.jpg").read_bytes()
        for budget, ranked, stale_selection, should_click in (
            (8000, False, False, True), (8000, True, False, False),
            (2600, False, False, False), (8000, False, True, False),
        ):
            with self.subTest(budget=budget, ranked=ranked, stale_selection=stale_selection):
                operator = PythonAutoOperator.__new__(PythonAutoOperator)
                operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                    stability_pixel_delta=1.5, force_auto_click_budget_ms=budget, ranked_loop=ranked)
                operator.layout = load_json(project / "config/layout-300-regression.json")
                operator.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
                operator.river_clip = {"x": 10, "y": 0, "width": 10, "height": 10}
                operator.screencast_session = Mock()
                operator.latest_screencast_frame = frame
                operator.screencast_draw_generation = 4
                operator.cached_open_melds = 0
                operator.action_evidence_started_at = 10.0
                operator.confirm_action_button = Mock(return_value={"confirmation": "riichi_selection_hand_changed"})
                operator.confirm_discard = Mock(return_value={"confirmation": "hand_and_own_river_changed"})
                operator.refresh_discard_reconciliation_before_click = Mock(return_value=False)
                operator.require_action_deadline = Mock()
                operator.log = Mock()
                page = Mock()
                button = io.BytesIO()
                Image.new("RGB", (100, 40), "orange").save(button, format="PNG")
                page.screenshot.side_effect = lambda **kw: button.getvalue() if "clip" in kw else selection
                evaluation = {
                    "decision": {"selectedAction": {"action": "riichi", "tile": "1m"}},
                    "recognition": {"tiles": ["1m"] * 14, "safe": False},
                    "clickIndex": 0, "clickPoint": {"x": 269, "y": 999},
                    "actionButton": {"action": "riichi", "x": 1087, "y": 788, "width": 352,
                                     "height": 57, "center": {"x": 1263, "y": 816.5}},
                }
                clock = {"now": 10.1}
                def classify(*_args):
                    clock["now"] = 18.8
                    return "match", 1.0
                def stable_delta(*_args):
                    if stale_selection and clock["now"] >= 18.8:
                        clock["now"] = 27.0
                    return 0.0
                with patch("auto_operator.time.monotonic", side_effect=lambda: clock["now"]), \
                        patch("auto_operator.stable_hand_delta", side_effect=stable_delta), \
                        patch("auto_operator.raised_tile_confirmation_point", return_value={"x": 269, "y": 971, "lift": 28, "faceStructureDelta": 0.0}), \
                        patch("auto_operator.classify_screen", side_effect=classify), \
                        patch("auto_operator.is_away_resume_dialog", return_value=False), \
                        patch("auto_operator.discard_point_in_hand_geometry", return_value=True):
                    if should_click:
                        receipt = operator.execute(page, evaluation, crop_screenshot(frame, operator.hand_clip), frame, 4, 10.0)
                        self.assertTrue(receipt["clicked"])
                    else:
                        with self.assertRaisesRegex(RetryableSafetyAbort, "click budget expired"):
                            operator.execute(page, evaluation, crop_screenshot(frame, operator.hand_clip), frame, 4, 10.0)
                        page.mouse.click.assert_called_once_with(1263, 816.5)

    def test_riichi_discard_aborts_when_selection_target_moves_after_declaration(self) -> None:
        """Never apply the pre-Riichi target after a changing selection row."""
        project = Path(__file__).resolve().parents[1]
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(
            mode="force-auto", allow_local_discard=False, stability_pixel_delta=1.5,
            force_auto_click_budget_ms=2600,
        )
        operator.layout = load_json(project / "config/layout-300-regression.json")
        operator.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        operator.river_clip = {"x": 770, "y": 535, "width": 390, "height": 225}
        frame = (project / "test/fixtures/riichi-before-selection-20261020.jpg").read_bytes()
        selection = (project / "test/fixtures/riichi-two-candidates-selection-20261020.jpg").read_bytes()
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = frame
        operator.screencast_draw_generation = 4
        operator.cached_open_melds = 0
        operator.confirm_action_button = Mock(return_value={"confirmation": "riichi_selection_hand_changed"})
        operator.refresh_discard_reconciliation_before_click = Mock(return_value=False)
        operator.require_action_deadline = Mock()
        operator.log = Mock()
        page = Mock()
        page.screenshot.side_effect = lambda **kwargs: selection
        evaluation = {
            "decision": {"selectedAction": {"action": "riichi", "tile": "1m"}},
            "recognition": {"tiles": ["1m"] * 14, "safe": False},
            "clickIndex": 0,
            "clickPoint": {"x": 269, "y": 999},
            "actionButton": {"action": "riichi", "x": 1087, "y": 788, "width": 352, "height": 57,
                             "center": {"x": 1263, "y": 816.5}},
        }
        with patch("auto_operator.stable_hand_delta", side_effect=[0.0, 2.0]), \
                patch("auto_operator.classify_screen", return_value=("match", 1.0)), \
                patch("auto_operator.is_away_resume_dialog", return_value=False), \
                patch("auto_operator.discard_point_in_hand_geometry", return_value=True), \
                patch("auto_operator.time.monotonic", return_value=10.1):
            with self.assertRaisesRegex(RetryableSafetyAbort, "riichi selection target changed"):
                operator.execute(page, evaluation, crop_screenshot(frame, operator.hand_clip), frame, 4, 10.0)
        # The declaration can be sent, but the unsafe second tile click cannot.
        page.mouse.click.assert_called_once_with(1263, 816.5)

    def test_reaction_call_never_clicks_a_stale_ranked_capture(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(
            mode="force-auto", accept_single_call=True, force_auto_click_budget_ms=2600,
        )
        operator.layout = {"viewport": {"width": 1920, "height": 1080}, "publicTileRegions": {}}
        operator.hand_clip = {"x": 0, "y": 0, "width": 10, "height": 10}
        operator.log = Mock()
        page = Mock()
        button = {"action": "pon", "center": {"x": 800, "y": 700}}
        frame = io.BytesIO()
        Image.new("RGB", (1920, 1080), "black").save(frame, format="PNG")

        with patch("auto_operator.force_auto_call_buttons", return_value=[button]), \
                patch("auto_operator.time.monotonic", return_value=12.7):
            with self.assertRaisesRegex(RetryableSafetyAbort, "click budget expired"):
                operator.execute_force_auto_call(
                    page, frame.getvalue(), button, evaluated_captured_at=10.0,
                )

        page.mouse.click.assert_not_called()

    def test_reaction_win_never_clicks_a_stale_ranked_capture(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", force_auto_click_budget_ms=2600)
        operator.layout = {
            "viewport": {"width": 1920, "height": 1080},
            "actionButtonRegions": {"pass": {"x": 10, "y": 20, "width": 100, "height": 40}},
        }
        operator.log = Mock()
        page = Mock()
        button = {"action": "ron", "center": {"x": 1010, "y": 824}}

        with patch("auto_operator.force_auto_reaction_win_button", return_value=button), \
                patch("auto_operator.time.monotonic", return_value=12.7):
            with self.assertRaisesRegex(RetryableSafetyAbort, "click budget expired"):
                operator.execute_force_auto_reaction_win(
                    page, b"frame", button, evaluated_captured_at=10.0,
                )

        page.mouse.click.assert_not_called()

    def test_single_missing_frame_does_not_clear_first_evidence(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.action_evidence_started_at = 10.0
        operator.action_evidence_last_seen_at = 10.1
        operator.action_evidence_kind = "win"
        operator.last_action_clicked_at = None
        operator.log = Mock()
        with patch("auto_operator.time.monotonic", return_value=10.2):
            operator.mark_action_evidence("win")
        self.assertEqual(operator.action_evidence_started_at, 10.0)

    def test_different_gate_does_not_refresh_reaction_during_frame_drop_grace(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.action_evidence_started_at = 10.0
        operator.action_evidence_last_seen_at = 10.1
        operator.action_evidence_kind = "reaction"
        operator.action_evidence_generation = 4
        operator.last_action_clicked_at = None
        operator.log = Mock()
        operator.mark_action_evidence(
            "discard", observed_at=10.2, gate_generation=5, supersede=False,
        )
        self.assertEqual(operator.action_evidence_started_at, 10.0)
        self.assertEqual(operator.action_evidence_last_seen_at, 10.1)
        self.assertEqual(operator.action_evidence_kind, "reaction")

    def test_live_300_closed_draw_replaces_stale_reaction_deadline(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        frame = (project / "artifacts" / "friend-300-20260925" / "frames" /
                 "2026-09-25T04-19-21.922394+00-00.jpg").read_bytes()
        self.assertTrue(is_draw_slot_occupied(frame, layout["drawSlot"]))
        self.assertIsNone(geometric_open_meld_count(frame, layout))
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.cached_open_melds = 0
        operator.screencast_sequence = 10
        operator.action_evidence_started_at = time.monotonic() - 11
        operator.action_evidence_last_seen_at = time.monotonic() - 10
        operator.action_evidence_kind = "reaction"
        operator.action_evidence_generation = 4
        operator.last_action_clicked_at = None
        operator.log = Mock()
        self.assertTrue(operator.supersede_reaction_on_verified_draw(
            draw_occupied=True, exact_open_melds=None, geometric_open_melds=None,
        ))
        self.assertEqual(operator.action_evidence_kind, "discard")
        self.assertTrue(operator.action_timing()["deadlineMet"])
        self.assertFalse(operator.supersede_reaction_on_verified_draw(
            draw_occupied=False, exact_open_melds=None, geometric_open_melds=None,
        ))

    def test_compact_geometry_rejects_opponent_turn_without_own_meld_surface(self) -> None:
        layout = {
            "viewport": {"width": 1920, "height": 1080},
            "handSlots": [
                {"x": 223 + index * 95, "y": 926, "width": 92, "height": 146}
                for index in range(13)
            ],
            "drawSlot": {"x": 1486, "y": 926, "width": 92, "height": 146},
        }
        frame = io.BytesIO()
        image = Image.new("RGB", (1920, 1080), (25, 55, 85))
        draw = ImageDraw.Draw(image)
        for slot in layout["handSlots"][:10]:
            draw.rectangle((
                slot["x"], slot["y"], slot["x"] + slot["width"], slot["y"] + slot["height"],
            ), fill=(230, 225, 210))
        image.save(frame, format="PNG")

        self.assertIsNone(geometric_open_meld_count(frame.getvalue(), layout))

    def test_force_auto_pass_prompt_requires_dark_button_and_warm_neutral_text(self) -> None:
        region = {"x": 100, "y": 50, "width": 200, "height": 80}
        image = Image.new("RGB", (400, 200), (25, 55, 85))
        draw = ImageDraw.Draw(image)
        draw.rectangle((100, 50, 300, 130), fill=(35, 40, 45))
        draw.rectangle((140, 75, 170, 90), fill=(180, 150, 70))
        draw.rectangle((190, 75, 250, 90), fill=(150, 145, 90))
        output = io.BytesIO()
        image.save(output, format="PNG")
        self.assertTrue(is_force_auto_pass_prompt(output.getvalue(), region))

        empty = io.BytesIO()
        Image.new("RGB", (400, 200), (25, 55, 85)).save(empty, format="PNG")
        self.assertFalse(is_force_auto_pass_prompt(empty.getvalue(), region))

    def test_force_auto_call_buttons_only_find_green_action_buttons(self) -> None:
        viewport = {"width": 1600, "height": 900}
        image = Image.new("RGB", (1600, 900), (25, 55, 85))
        draw = ImageDraw.Draw(image)
        draw.rectangle((893, 650, 1131, 743), fill=(45, 130, 70))
        output = io.BytesIO()
        image.save(output, format="PNG")
        buttons = force_auto_call_buttons(output.getvalue(), viewport)
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0]["action"], "chi")
        self.assertEqual(buttons[0]["center"], {"x": 1012.0, "y": 696.5})

        orange = Image.new("RGB", (1600, 900), (25, 55, 85))
        ImageDraw.Draw(orange).rectangle((893, 650, 1131, 743), fill=(190, 110, 35))
        output = io.BytesIO()
        orange.save(output, format="PNG")
        self.assertEqual(force_auto_call_buttons(output.getvalue(), viewport), [])

    def test_call_palette_threshold_boundaries_and_column_extents(self) -> None:
        viewport = {"width": 1000, "height": 1000}
        cases = [
            ((50, 81, 60), "chi"), ((50, 80, 60), None),
            ((66, 81, 60), None), ((50, 81, 71), None),
            ((100, 140, 150), "pon"), ((100, 135, 150), None),
            ((80, 120, 150), None), ((100, 140, 140), None),
        ]
        for color, action in cases:
            with self.subTest(color=color):
                frame = Image.new("RGB", (1000, 1000), "black")
                frame.paste(color, (400, 700, 501, 761))
                output = io.BytesIO()
                frame.save(output, format="PNG")
                buttons = force_auto_call_buttons(output.getvalue(), viewport)
                if action is None:
                    self.assertEqual(buttons, [])
                else:
                    self.assertEqual(buttons, [{"action": action, "x": 400, "y": 700,
                        "width": 100, "height": 60, "center": {"x": 450.0, "y": 730.0}}])

    def test_force_auto_call_buttons_keep_multiple_choices_ambiguous(self) -> None:
        viewport = {"width": 1600, "height": 900}
        image = Image.new("RGB", (1600, 900), (25, 55, 85))
        draw = ImageDraw.Draw(image)
        draw.rectangle((650, 650, 790, 743), fill=(45, 130, 70))
        draw.rectangle((850, 650, 990, 743), fill=(25, 145, 180))
        # Bamboo-colored pixels in the concealed-hand row must not merge with
        # the cyan pon button above them.
        draw.rectangle((870, 780, 930, 899), fill=(30, 120, 100))
        output = io.BytesIO()
        image.save(output, format="PNG")
        buttons = force_auto_call_buttons(output.getvalue(), viewport)
        self.assertEqual(len(buttons), 2)
        self.assertEqual([button["action"] for button in buttons], ["chi", "pon"])
        self.assertLess(max(button["height"] for button in buttons), 100)

    def test_force_auto_call_buttons_reject_wide_table_coloring(self) -> None:
        viewport = {"width": 1920, "height": 1080}
        image = Image.new("RGB", (1920, 1080), (25, 55, 85))
        draw = ImageDraw.Draw(image)
        draw.rectangle((741, 734, 1164, 855), fill=(25, 145, 180))
        output = io.BytesIO()
        image.save(output, format="PNG")

        self.assertEqual(force_auto_call_buttons(output.getvalue(), viewport), [])

    def test_live_300_pon_kan_prompt_retains_independent_pon_and_skip_evidence(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frame = (project / "artifacts" / "live" / "pon-kan-prompt-20260928.png").read_bytes()
        layout = load_json(project / "config" / "layout.json")
        buttons = force_auto_call_buttons(frame, layout["viewport"])
        self.assertEqual([button["action"] for button in buttons], ["pon"])
        self.assertTrue(is_contextual_reaction_pass(frame, layout["actionButtonRegions"]["pass"], len(buttons)))
        self.assertIsNone(force_auto_reaction_win_button(frame, layout["viewport"], layout["actionButtonRegions"]["pass"]))

    def test_tenpai_guard_allows_pass_when_a_green_call_is_visible(self) -> None:
        self.assertTrue(should_guard_tenpai_reaction(0, []))
        self.assertFalse(should_guard_tenpai_reaction(0, [{"center": {"x": 100, "y": 100}}]))
        self.assertFalse(should_guard_tenpai_reaction(1, []))

    def test_force_auto_self_action_button_finds_visible_riichi_colored_button(self) -> None:
        viewport = {"width": 1600, "height": 900}
        image = Image.new("RGB", (1600, 900), (25, 55, 85))
        # Keep the synthetic button above the concealed row (85% height).
        ImageDraw.Draw(image).rectangle((893, 680, 1131, 750), fill=(190, 110, 35))
        output = io.BytesIO()
        image.save(output, format="PNG")
        buttons = force_auto_self_action_buttons(output.getvalue(), viewport)
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0]["center"], {"x": 1012.0, "y": 715.0})

    def test_red_action_button_keeps_inclusive_green_ratio_boundary(self) -> None:
        viewport = {"width": 1600, "height": 900}
        for color, expected in [
            ((210, 80, 100), True),  # red ron, exactly green == blue * 0.8
            ((210, 79, 100), False),
            ((210, 81, 101), True),  # fractional blue threshold must round up
            ((210, 80, 101), False),
            ((160, 80, 100), False),  # red - blue must exceed 60
            ((161, 80, 100), True),
        ]:
            with self.subTest(color=color):
                image = Image.new("RGB", (1600, 900), (25, 55, 85))
                ImageDraw.Draw(image).rectangle((893, 680, 1131, 750), fill=color)
                output = io.BytesIO()
                image.save(output, format="PNG")
                buttons = force_auto_self_action_buttons(output.getvalue(), viewport)
                self.assertEqual(bool(buttons), expected)
                if expected:
                    self.assertEqual(buttons[0]["center"], {"x": 1012.0, "y": 715.0})

    def test_force_auto_reaction_win_requires_pass_and_one_orange_button(self) -> None:
        viewport = {"width": 1600, "height": 900}
        pass_region = {"x": 1170, "y": 650, "width": 275, "height": 105}
        image = Image.new("RGB", (1600, 900), (25, 55, 85))
        draw = ImageDraw.Draw(image)
        draw.rectangle((850, 650, 1050, 743), fill=(190, 90, 35))
        draw.rectangle((1170, 650, 1445, 755), fill=(35, 40, 45))
        draw.rectangle((1210, 675, 1240, 690), fill=(180, 150, 70))
        draw.rectangle((1260, 675, 1320, 690), fill=(150, 145, 90))
        output = io.BytesIO()
        image.save(output, format="PNG")
        button = force_auto_reaction_win_button(output.getvalue(), viewport, pass_region)
        self.assertIsNotNone(button)
        self.assertEqual(button["center"], {"x": 950.0, "y": 696.5})

    def test_live_magenta_kan_is_not_promoted_to_ron_or_a_fourth_pon(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        prompt = (project / "artifacts" / "friend-5-20" / "frames" /
                  "2026-09-21T08-38-54.094464+00-00.png").read_bytes()
        pass_region = layout["actionButtonRegions"]["pass"]

        self.assertEqual(force_auto_call_buttons(prompt, layout["viewport"]), [])
        button = force_auto_reaction_win_button(prompt, layout["viewport"], pass_region)
        self.assertIsNone(button)

    def test_single_call_arms_compact_hand_discard_after_button_disappears(self) -> None:
        viewport = {"width": 1600, "height": 900}
        prompt = Image.new("RGB", (1600, 900), (25, 55, 85))
        ImageDraw.Draw(prompt).rectangle((893, 650, 1131, 743), fill=(45, 130, 70))
        ImageDraw.Draw(prompt).rectangle((100, 780, 700, 899), fill=(230, 225, 210))
        ImageDraw.Draw(prompt).rectangle((20, 700, 180, 770), fill=(25, 55, 85))
        prompt_bytes = io.BytesIO()
        prompt.save(prompt_bytes, format="PNG")
        table_bytes = io.BytesIO()
        table = Image.new("RGB", (1600, 900), (25, 55, 85))
        ImageDraw.Draw(table).rectangle((100, 780, 500, 899), fill=(230, 225, 210))
        ImageDraw.Draw(table).rectangle((20, 700, 180, 770), fill=(230, 225, 210))
        # A completed meld can still contain enough cyan/green pixels to look
        # like an action button. Visual hand+meld change remains authoritative.
        ImageDraw.Draw(table).rectangle((900, 650, 1080, 743), fill=(25, 145, 180))
        table.save(table_bytes, format="PNG")
        button = force_auto_call_buttons(prompt_bytes.getvalue(), viewport)[0]

        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(
            mode="force-auto", accept_single_call=True, confirmation_timeout=1, action_pixel_delta=3,
        )
        operator.layout = {"viewport": viewport, "publicTileRegions": {
            "ownMelds": {"x": 20, "y": 700, "width": 160, "height": 70},
        }}
        operator.hand_clip = {"x": 100, "y": 780, "width": 600, "height": 120}
        operator.screencast_sequence = 0
        operator.latest_screencast_frame = None
        operator.cached_concealed_tiles = ["1m"] * 13
        operator.cached_open_melds = 1
        operator.dynamic_layout_required = False
        operator.pending_post_call_discard = False
        operator.closed_new_round_candidate_frames = {"stale-closed-row"}
        operator.last_processed_hand = "old"
        operator.armed = False
        operator.log = Mock()
        page = Mock()
        page.screenshot.return_value = table_bytes.getvalue()

        receipt = operator.execute_force_auto_call(page, prompt_bytes.getvalue(), button)

        self.assertEqual(receipt["confirmation"], "hand_and_own_meld_changed")
        self.assertEqual(receipt["action"], "chi")
        self.assertEqual(receipt["nextAction"], "discard")
        self.assertEqual(operator.cached_open_melds, 2)
        self.assertTrue(operator.pending_post_call_discard)
        self.assertEqual(operator.closed_new_round_candidate_frames, set())
        self.assertIsNotNone(operator.pending_post_call_started_at)
        self.assertTrue(operator.dynamic_layout_required)
        self.assertTrue(operator.armed)
        page.mouse.click.assert_called_once_with(1012.0, 696.5)

    def test_single_call_policy_requires_verified_discard_and_approved_assessment(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_state = {"seat": "south"}
        operator.cached_public_observation = {"opponentDiscards": [
            {"seat": "east", "discards": ["P"]}, {"seat": "west", "discards": []},
            {"seat": "north", "discards": []},
        ]}
        operator.previous_public_observation = {"opponentDiscards": [
            {"seat": "east", "discards": []}, {"seat": "west", "discards": []},
            {"seat": "north", "discards": []},
        ]}
        operator.cached_open_melds = 0
        operator.log = Mock()
        operator.observe_public_board = Mock(return_value=operator.cached_public_observation)
        operator.recognize_resident = Mock(return_value={"tiles": ["1m"] * 13, "safe": True})
        approved = {"status": "decision", "decision": {
            "selectedAction": {"id": "pon_P", "action": "pon"},
            "callAssessments": [{"actionId": "pon_P", "approved": True}],
        }}
        operator.evaluate = Mock(return_value=approved)
        screenshot = Path("prompt.png")
        self.assertEqual(operator.evaluate_force_auto_call_policy(screenshot, "pon"), approved)
        operator.evaluate.assert_called_once()
        self.assertEqual(operator.evaluate.call_args.args[-1], ["pon", "pass"])

        before = operator.previous_public_observation
        after = operator.cached_public_observation
        operator.previous_public_observation = {**before, "ownDiscards": ["9m"]}
        operator.cached_public_observation = before
        operator.observe_public_board.return_value = after
        operator.evaluate.reset_mock()
        self.assertEqual(operator.evaluate_force_auto_call_policy(screenshot, "pon"), approved)
        operator.evaluate.assert_called_once()
        self.assertEqual(operator.evaluate.call_args.args[1], {"tile": "P", "fromSeat": "east"})
        operator.previous_public_observation = before
        operator.cached_public_observation = after
        operator.evaluate.reset_mock()
        operator.observe_public_board.return_value = operator.previous_public_observation
        self.assertIsNone(operator.evaluate_force_auto_call_policy(screenshot, "pon"))
        operator.evaluate.assert_not_called()
        evidence = operator.log.call_args.kwargs["riverEvidence"]
        self.assertEqual(evidence["cached"]["opponentDiscards"][0]["discards"], ["P"])
        self.assertEqual(evidence["prompt"]["opponentDiscards"][0]["discards"], [])
        operator.previous_public_observation = operator.cached_public_observation
        self.assertIsNone(operator.evaluate_force_auto_call_policy(screenshot, "pon"))
        operator.evaluate.assert_not_called()

    def test_post_call_transition_distinguishes_discard_and_rinshan_draw(self) -> None:
        self.assertEqual(post_call_transition("pon", 1), {
            "openMelds": 2, "dynamicLayoutRequired": True, "pendingPostCallDiscard": True,
        })
        self.assertEqual(post_call_transition("minkan", 2), {
            "openMelds": 3, "dynamicLayoutRequired": True, "pendingPostCallDiscard": False,
        })
        self.assertFalse(should_process_reaction_prompt(True))
        self.assertTrue(should_process_reaction_prompt(False))

    def test_confirmed_call_builds_typed_meld_and_selects_requested_chi_variant(self) -> None:
        selected = {
            "id": "chi_3s_4s_5s", "action": "chi", "tile": "3s",
            "consumedTiles": ["4s", "0s"],
        }
        legal = [
            {"id": "chi_3s_2s_4s", "action": "chi"},
            selected,
            {"id": "pass", "action": "pass"},
        ]
        points = [{"x": 800.0, "y": 790.0}, {"x": 1100.0, "y": 790.0}]

        self.assertEqual(selected_chi_choice_point(points, selected, legal), points[1])
        self.assertEqual(confirmed_call_meld(selected), {
            "type": "chi", "tiles": ["4s", "0s", "3s"], "confidence": 1.0,
        })
        self.assertIsNone(selected_chi_choice_point(points, None, legal))
        self.assertIsNone(confirmed_call_meld({"action": "chi", "tile": "3s", "consumedTiles": ["4s"]}))

    def test_native_red_pon_preserves_forced_consumption_in_cached_meld(self) -> None:
        fixture = load_json(FRAME_FIXTURES / "red-call-physical-identity-20261022.json")
        action = {**fixture["beforeAction"], "consumedTiles": fixture["physicalConsumedTiles"]}
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.cached_public_observation = {
            "doraIndicators": ["6m"], "ownDiscards": [], "ownMelds": [],
            "ownMeldTiles": [], "ownMeldsObserved": True,
            "opponentDiscards": [{"seat": "south", "discards": ["5p"]}],
        }
        operator.previous_public_observation = None
        operator.public_cache_generation = 0
        operator.log = Mock()
        operator.reconcile_confirmed_call_discard({"tile": "5p", "fromSeat": "south"}, action)
        cached = operator.cached_public_observation
        self.assertEqual(cached["ownMelds"][0]["tiles"], ["0p", "5p", "5p"])
        self.assertEqual(cached["ownMeldTiles"], ["0p", "5p", "5p"])
        self.assertTrue(cached["ownMeldsObserved"])
        self.assertEqual(cached["opponentDiscards"][0]["discards"], [])

    def test_ambiguous_red_consumption_never_certifies_a_physical_meld(self) -> None:
        action = {"id": "pon_5p", "action": "pon", "tile": "5p",
                  "consumedTiles": ["0p", "5p"],
                  "consumedTileChoices": [["0p", "5p"], ["5p", "5p"]]}
        self.assertIsNone(confirmed_call_meld(action))
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.cached_public_observation = {
            "doraIndicators": [], "ownDiscards": [], "ownMelds": [],
            "ownMeldTiles": [], "ownMeldsObserved": True,
            "opponentDiscards": [{"seat": "south", "discards": ["5p"]}],
        }
        operator.previous_public_observation = None
        operator.public_cache_generation = 0
        operator.log = Mock()
        operator.reconcile_confirmed_call_discard({"tile": "5p", "fromSeat": "south"}, action)
        cached = operator.cached_public_observation
        self.assertEqual(cached["ownMelds"], [])
        self.assertFalse(cached["ownMeldsObserved"])
        self.assertEqual(cached["opponentDiscards"][0]["discards"], [])

    def test_persistent_call_tile_conflict_falls_back_to_safe_pass(self) -> None:
        conflict = RetryableSafetyAbort("reaction_tile_count_conflict")
        self.assertTrue(should_retry_call_policy(conflict, 19999))
        self.assertFalse(should_retry_call_policy(conflict, 20000))
        self.assertTrue(should_retry_call_policy(RetryableSafetyAbort("transient"), 30000))

    def test_confirmed_call_persists_typed_meld_when_vision_could_not_classify_it(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        observation = {
            "doraIndicators": ["1m"], "ownDiscards": ["N"],
            "ownMelds": [], "ownMeldTiles": [], "ownMeldsObserved": False,
            "opponentDiscards": [{"seat": "west", "discards": ["C", "3s"]}],
        }
        operator.cached_public_observation = observation
        operator.previous_public_observation = None
        operator.public_cache_generation = 4
        operator.log = Mock()

        operator.reconcile_confirmed_call_discard(
            {"tile": "3s", "fromSeat": "west"},
            {"id": "chi_3s_2s_4s", "action": "chi", "tile": "3s",
             "consumedTiles": ["2s", "4s"]},
        )

        cached = operator.cached_public_observation
        self.assertEqual(cached["opponentDiscards"][0]["discards"], ["C"])
        self.assertEqual(cached["ownMelds"], [{
            "type": "chi", "tiles": ["2s", "4s", "3s"], "confidence": 1.0,
        }])
        self.assertEqual(cached["ownMeldTiles"], ["2s", "4s", "3s"])
        self.assertTrue(cached["ownMeldsObserved"])

    def test_restart_accepts_compact_hand_with_complete_visible_meld(self) -> None:
        observation = {
            "ownMelds": [{
                "type": "pon", "tiles": ["5p", "5p", "5p"], "confidence": 0.93,
            }],
            "ownMeldTiles": ["5p", "5p", "5p"],
        }

        self.assertEqual(
            PythonAutoOperator.verified_visible_open_meld_count(1, observation), 1,
        )
        self.assertTrue(PythonAutoOperator.compact_hand_is_proven(1, False, observation))

    def test_restart_rejects_compact_hand_with_incomplete_or_ambiguous_meld(self) -> None:
        incomplete = {
            "ownMelds": [],
            "ownMeldTiles": ["5p", "5p", "5p"],
        }
        unexplained_tile = {
            "ownMelds": [{
                "type": "pon", "tiles": ["5p", "5p", "5p"], "confidence": 0.93,
            }],
            "ownMeldTiles": ["5p", "5p", "5p", "7s"],
        }

        for observation in (None, incomplete, unexplained_tile):
            with self.subTest(observation=observation):
                self.assertIsNone(
                    PythonAutoOperator.verified_visible_open_meld_count(1, observation),
                )
                self.assertFalse(PythonAutoOperator.compact_hand_is_proven(1, False, observation))

    def test_restart_open_discard_gate_accepts_only_self_turn_tile_count(self) -> None:
        observation = {
            "ownMelds": [{
                "type": "pon", "tiles": ["5p", "5p", "5p"], "confidence": 0.93,
            }],
            "ownMeldTiles": ["5p", "5p", "5p"],
        }

        self.assertEqual(
            PythonAutoOperator.restart_open_discard_meld_count(11, observation), 1,
        )
        # Ten concealed tiles is the stable post-discard/opponent-turn state.
        self.assertIsNone(
            PythonAutoOperator.restart_open_discard_meld_count(10, observation),
        )

    def test_restart_open_discard_gate_rejects_incomplete_meld_evidence(self) -> None:
        observation = {
            "ownMelds": [],
            "ownMeldTiles": ["5p", "5p", "5p"],
        }

        self.assertIsNone(
            PythonAutoOperator.restart_open_discard_meld_count(11, observation),
        )

    def test_force_auto_reaction_fallback_requires_thirteen_concealed_tiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(mode="force-auto", action_templates="", evaluation_timeout=30)
            operator.root = Path(directory)
            operator.layout_path = Path(directory) / "layout.json"
            operator.templates = Path(directory) / "templates"
            operator.evaluator_env = {}
            operator.layout = {"actionButtonRegions": {"pass": {"x": 100, "y": 50, "width": 200, "height": 80}}}
            image = Image.new("RGB", (400, 200), (25, 55, 85))
            draw = ImageDraw.Draw(image)
            draw.rectangle((100, 50, 300, 130), fill=(35, 40, 45))
            draw.rectangle((140, 75, 170, 90), fill=(180, 150, 70))
            draw.rectangle((190, 75, 250, 90), fill=(150, 145, 90))
            screenshot = Path(directory) / "reaction.png"
            image.save(screenshot)
            operator.recognize_resident = Mock(return_value={"tiles": ["1m"] * 13})
            result = operator.force_auto_reaction_fallback(screenshot)

            self.assertEqual(result["status"], "reaction_prompt")
            self.assertEqual(result["actionButton"]["center"], {"x": 200.0, "y": 90.0})
            operator.recognize_resident.assert_called_once_with(screenshot, concealed_only=True)

    def test_live_open_hand_chi_skip_prompt_uses_contextual_reaction_gate(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frame = (project / "artifacts" / "debug-300-current-end.png").read_bytes()
        layout = load_json(project / "config" / "layout.json")
        pass_region = layout["actionButtonRegions"]["pass"]
        calls = force_auto_call_buttons(frame, layout["viewport"])

        self.assertTrue(calls)
        self.assertFalse(is_force_auto_pass_prompt(frame, pass_region))
        self.assertTrue(is_contextual_reaction_pass(frame, pass_region, len(calls)))
        self.assertFalse(is_contextual_reaction_pass(frame, pass_region, 0))

    def test_contextual_open_hand_pass_accepts_compact_concealed_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(mode="force-auto", action_templates="")
            operator.layout = {"actionButtonRegions": {
                "pass": {"x": 100, "y": 50, "width": 200, "height": 80},
            }}
            operator.cached_open_melds = 1
            operator.recognize_resident = Mock(return_value={"tiles": ["1m"] * 10})
            screenshot = Path(directory) / "prompt.png"
            Image.new("RGB", (400, 200), "navy").save(screenshot)

            result = operator.force_auto_reaction_fallback(
                screenshot, contextual_prompt_verified=True,
            )

            self.assertEqual(result["status"], "reaction_prompt")
            self.assertEqual(result["actionButton"]["action"], "pass")
            operator.recognize_resident.assert_called_once_with(
                screenshot, concealed_only=True, dynamic_layout=True, open_melds=1,
            )

    def test_restart_on_live_open_reaction_recovers_only_after_two_frames(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frame = project / "artifacts" / "live" / "open-pon-prompt-20260928.png"
        layout = load_json(project / "config" / "layout.json")
        self.assertEqual(geometric_reaction_open_meld_count(frame.read_bytes(), layout), 1)
        closed = project / "artifacts" / "live" / "closed-self-draw-20260928.png"
        self.assertIsNone(geometric_reaction_open_meld_count(closed.read_bytes(), layout))
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = layout
        operator.cached_open_melds = 0
        operator.open_meld_candidate = None
        operator.open_meld_candidate_frames = set()
        operator.recognize_resident = Mock(return_value={"tiles": ["1m"] * 10})
        operator.log = Mock()
        operator.recognize_reaction_hand(frame)
        self.assertEqual(operator.cached_open_melds, 0)
        operator.recognize_resident.assert_called_with(frame, concealed_only=True)
        with tempfile.TemporaryDirectory() as directory:
            second = Path(directory) / "second.png"
            image = Image.open(frame).convert("RGB")
            image.putpixel((1500, 800), (0, 0, 0))
            image.save(second)
            operator.recognize_reaction_hand(second)
            self.assertEqual(operator.cached_open_melds, 1)
            operator.recognize_resident.assert_called_with(
                second, concealed_only=True, dynamic_layout=True, open_melds=1,
            )

    def test_force_auto_post_discard_verifier_keeps_exact_multiset_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.frames = Path(directory)
            operator.root = Path(directory)
            operator.layout_path = Path(directory) / "layout.json"
            operator.templates = Path(directory) / "templates"
            operator.evaluator_env = {}
            operator.args = argparse.Namespace(mode="force-auto", evaluation_timeout=30)
            completed = argparse.Namespace(returncode=0, stdout=json.dumps({
                "verified": True,
                "force": True,
                "expected": ["1m"] * 13,
                "actual": ["1m"] * 13,
            }), stderr="")

            with patch("auto_operator.subprocess.run", return_value=completed) as run:
                result = operator.verify_post_discard(b"png", ["1m"] * 14, 0)

            self.assertTrue(result["verified"])
            self.assertIn("--force", run.call_args.args[0])

    def test_strategy_bridge_decodes_utf8_json_independent_of_windows_code_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.frames = Path(directory)
            operator.root = Path(directory)
            operator.layout_path = Path(directory) / "layout.json"
            operator.templates = Path(directory) / "templates"
            operator.state_path = Path(directory) / "state.json"
            operator.evaluator_env = {}
            operator.args = argparse.Namespace(
                mode="force-auto", action_templates="", evaluation_timeout=30,
            )
            strategy = {
                "status": "decision",
                "decision": {
                    "selectedAction": {"action": "discard", "tile": "1m"},
                    "handPlan": {"primaryYaku": "立直", "reason": "両面待ちを維持"},
                },
            }
            completed = argparse.Namespace(
                returncode=0,
                stdout=json.dumps(strategy, ensure_ascii=False),
                stderr="",
            )

            with patch("auto_operator.subprocess.run", return_value=completed) as run:
                result = operator.evaluate(Path(directory) / "frame.png")

            self.assertEqual(result["decision"]["handPlan"]["primaryYaku"], "立直")
            self.assertEqual(result["decision"]["handPlan"]["reason"], "両面待ちを維持")
            self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
            self.assertEqual(run.call_args.kwargs["errors"], "strict")

    def test_force_auto_confirmation_uses_visual_change_without_repeating_recognition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(
                mode="force-auto", confirmation_timeout=1,
                action_pixel_delta=1, river_pixel_delta=1,
            )
            operator.frames = Path(directory)
            operator.hand_clip = {"x": 0, "y": 0, "width": 10, "height": 10}
            operator.river_clip = {"x": 10, "y": 0, "width": 10, "height": 10}
            operator.verify_post_discard = Mock(side_effect=AssertionError("must not re-recognize"))
            black = io.BytesIO()
            Image.new("RGB", (10, 10), "black").save(black, format="PNG")
            white = io.BytesIO()
            Image.new("RGB", (10, 10), "white").save(white, format="PNG")
            full = io.BytesIO()
            Image.new("RGB", (20, 10), "navy").save(full, format="PNG")
            page = Mock()
            page.screenshot.side_effect = lambda **kwargs: white.getvalue() if kwargs.get("clip") else full.getvalue()

            receipt = operator.confirm_discard(
                page, black.getvalue(), black.getvalue(), ["1m"] * 14, 0,
            )

            self.assertEqual(receipt["confirmation"], "hand_and_own_river_changed")
            self.assertTrue(Path(receipt["screenshot"]).exists())
            operator.verify_post_discard.assert_not_called()

    def test_terminal_reveal_waits_for_result_instead_of_rejecting_empty_slots(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(
            confirmation_timeout=0.1, terminal_transition_timeout=1,
            action_pixel_delta=1, river_pixel_delta=1,
        )
        operator.hand_clip = {"x": 0, "y": 0, "width": 10, "height": 10}
        operator.river_clip = {"x": 10, "y": 0, "width": 10, "height": 10}
        operator.screen_references = {}
        operator.verify_post_discard = Mock(return_value={"verified": False, "actual": []})
        operator.log = Mock()
        black = io.BytesIO()
        Image.new("RGB", (10, 10), "black").save(black, format="PNG")
        changed = io.BytesIO()
        Image.new("RGB", (10, 10), "white").save(changed, format="PNG")
        result_image = Image.new("RGB", (1920, 1080), (25, 55, 85))
        draw = ImageDraw.Draw(result_image)
        draw.rectangle((1650, 950, 1849, 1045), fill=(35, 40, 45))
        draw.rectangle((1650, 950, 1749, 1045), fill=(55, 70, 115))
        draw.rectangle((1680, 975, 1780, 1005), fill=(190, 165, 100))
        terminal = io.BytesIO()
        result_image.save(terminal, format="PNG")
        page = Mock()
        page.screenshot.side_effect = lambda **kwargs: (
            changed.getvalue() if kwargs.get("clip") else terminal.getvalue()
        )

        receipt = operator.confirm_discard(
            page, black.getvalue(), black.getvalue(), ["1m"] * 14, 0,
        )

        self.assertEqual(receipt["confirmation"], "discard_followed_by_terminal_result")
        self.assertEqual(receipt["terminalScreenState"], "round_result")
        operator.log.assert_called_once_with("terminal_transition_wait", verification={"verified": False, "actual": []})

    def test_operator_restores_and_verifies_cdp_viewport(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.log = Mock()
        page = Mock()
        page.evaluate.side_effect = [
            {"width": 630, "height": 84},
            {"width": 1920, "height": 1080},
        ]

        operator.ensure_viewport(page)

        page.set_viewport_size.assert_called_once_with({"width": 1920, "height": 1080})
        operator.log.assert_called_once_with(
            "viewport_restored",
            previous={"width": 630, "height": 84},
            viewport={"width": 1920, "height": 1080},
        )

    def test_operator_restarts_screencast_after_viewport_restore(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.log = Mock()
        operator.screencast_session = Mock()
        operator.restart_screencast_gate = Mock()
        page = Mock()
        page.evaluate.side_effect = [
            {"width": 1920, "height": 1119},
            {"width": 1920, "height": 1080},
        ]

        operator.ensure_viewport(page)

        operator.restart_screencast_gate.assert_called_once_with(page)

    def test_restart_screencast_replaces_silent_subscription(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        old_session = Mock()
        operator.screencast_session = old_session
        operator.latest_screencast_frame = b"stale"
        operator.screencast_draw_occupied = True
        operator.start_screencast_gate = Mock()
        page = Mock()

        operator.restart_screencast_gate(page)

        old_session.send.assert_called_once_with("Page.stopScreencast")
        old_session.detach.assert_called_once_with()
        self.assertIsNone(operator.screencast_session)
        self.assertIsNone(operator.latest_screencast_frame)
        self.assertIsNone(operator.screencast_draw_occupied)
        operator.start_screencast_gate.assert_called_once_with(page)

    def test_operator_leaves_matching_viewport_unchanged(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        page = Mock()
        page.evaluate.return_value = {"width": 1920, "height": 1080}

        operator.ensure_viewport(page)

        page.set_viewport_size.assert_not_called()

    def test_operator_force_sets_matching_viewport_after_cdp_attach(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.log = Mock()
        page = Mock()
        page.evaluate.side_effect = [
            {"width": 1920, "height": 1080},
            {"width": 1920, "height": 1080},
        ]

        operator.ensure_viewport(page, force=True)

        page.set_viewport_size.assert_called_once_with({"width": 1920, "height": 1080})
        page.wait_for_timeout.assert_called_once_with(250)
        operator.log.assert_not_called()

    def test_replay_records_execution_and_receives_round_and_match_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.replays = Path(directory) / "replays"
            operator.replays.mkdir()
            operator.frames = Path(directory) / "frames"
            operator.frames.mkdir()
            operator.log_path = Path(directory) / "operator.jsonl"
            operator.pending_round_replays = []
            operator.pending_match_replays = []
            screenshot = operator.frames / "decision.png"
            screenshot.write_bytes(b"decision")
            evaluation = {
                "state": {"round": "east_1"},
                "recognition": {"backend": "template", "tiles": ["1m"], "confidence": 1,
                                "ambiguityMargin": 1, "safe": True},
                "decision": {"selectedActionId": "discard_1m", "recommendedAction": "discard"},
            }
            replay = operator.record_replay(evaluation, screenshot, execution={
                "clicked": True,
                "confirmation": "hand_and_own_river_changed",
                "tileMultisetVerification": {"verified": True},
            })
            self.assertEqual(load_json(replay)["executionEvidence"]["status"], "verified")

            operator.args = argparse.Namespace(advance_screens=True, ranked_loop=False)
            page = Mock()
            def verify_saved_before_advance(_page, state, confidence):
                kind = "match" if state == "match_result" else "round"
                evidence = load_json(replay)["actualResult"][kind]
                self.assertEqual(Path(evidence["screenshot"]).read_bytes(), kind.encode())
            operator.advance_result_screen_once = Mock(side_effect=verify_saved_before_advance)
            self.assertTrue(operator.handle_early_non_gameplay_screen(page, "round_result", 0.99, b"round"))
            self.assertEqual(operator.pending_round_replays, [])
            self.assertEqual(operator.pending_match_replays, [replay])
            self.assertTrue(operator.handle_early_non_gameplay_screen(page, "match_result", 0.98, b"match"))
            self.assertEqual(operator.pending_match_replays, [])
            result = load_json(replay)["actualResult"]
            self.assertEqual(result["round"]["screenState"], "round_result")
            self.assertEqual(result["match"]["screenState"], "match_result")
            jsonl_record = json.loads((operator.replays / "decisions.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(jsonl_record["actualResult"]["round"]["screenState"], "round_result")
            self.assertEqual(jsonl_record["actualResult"]["match"]["screenState"], "match_result")
            self.assertEqual(operator.attach_outcome("round", b"duplicate", 1), 0)

    def test_early_result_invalidates_old_round_hand_and_public_cache(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(advance_screens=False, ranked_loop=False)
        operator.cached_concealed_tiles = ["1m"]
        operator.cached_open_melds = 1
        operator.cached_public_observation = {"ownDiscards": ["9p"]}
        operator.previous_public_observation = {"ownDiscards": ["8p"]}
        operator.public_cache_generation = 7
        operator.pending_post_call_discard = True
        operator.armed = False
        self.assertTrue(operator.handle_early_non_gameplay_screen(Mock(), "round_result", 1.0))
        self.assertIsNone(operator.cached_concealed_tiles)
        self.assertEqual(operator.cached_open_melds, 0)
        self.assertIsNone(operator.cached_public_observation)
        self.assertIsNone(operator.previous_public_observation)
        self.assertEqual(operator.public_cache_generation, 8)
        self.assertFalse(operator.pending_post_call_discard)
        self.assertTrue(operator.armed)
        operator.public_recognition_lock = threading.Lock()
        operator.public_recognition_result = {"generation": 7, "result": {"ownDiscards": ["9p"]}}
        operator.poll_public_recognition()
        self.assertIsNone(operator.cached_public_observation)

    def test_early_friend_match_result_confirms_after_evidence_then_stops(self) -> None:
        """The fast gate saves the result, confirms once, and stops."""
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", ranked_loop=False, advance_screens=True)
        operator.match_completed_stop_requested = False
        operator.log = Mock()
        operator.advance_result_screen_once = Mock()
        operator.attach_outcome = Mock()
        operator.advance_result_screen_once.side_effect = lambda *args: operator.attach_outcome.assert_called_once_with(
            "match", b"result", 0.98
        )
        page = Mock()

        self.assertTrue(operator.handle_early_non_gameplay_screen(page, "match_result", 0.98, b"result"))
        self.assertTrue(operator.match_completed_stop_requested)
        operator.attach_outcome.assert_called_once_with("match", b"result", 0.98)
        operator.advance_result_screen_once.assert_called_once_with(page, "match_result", 0.98)
        operator.log.assert_called_once_with("match_completed_stop", confidence=0.98)

    def test_early_friend_result_without_evidence_does_not_confirm(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", ranked_loop=False, advance_screens=True)
        operator.log = Mock()
        operator.advance_result_screen_once = Mock()
        self.assertTrue(operator.handle_early_non_gameplay_screen(Mock(), "match_result", 0.98))
        operator.advance_result_screen_once.assert_not_called()
        self.assertTrue(operator.match_completed_stop_requested)

    def test_early_friend_lobby_after_unconfirmed_selection_requests_stop(self) -> None:
        """A withheld second click must not leave a completed friend run polling lobby."""
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", ranked_loop=False, advance_screens=True)
        operator.match_completed_stop_requested = False
        operator.selection_uncertainty_latch = {"drawGeneration": 7, "ownDiscards": ["9m"]}
        operator.log = Mock()
        operator.advance_ranked_loop = Mock()
        page = Mock()

        self.assertTrue(operator.handle_early_non_gameplay_screen(page, "lobby", 1.0, b"lobby"))

        self.assertTrue(operator.match_completed_stop_requested)
        operator.advance_ranked_loop.assert_not_called()
        page.mouse.click.assert_not_called()
        operator.log.assert_called_once_with(
            "match_completed_stop", confidence=1.0, terminalState="lobby",
            reason="selection_uncertainty_followed_by_lobby", gameplayClicks=0,
        )

    def test_early_friend_lobby_without_unconfirmed_selection_does_not_stop(self) -> None:
        """A normal lobby label alone remains insufficient to invent a match result."""
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", ranked_loop=False, advance_screens=True)
        operator.selection_uncertainty_latch = None
        operator.log = Mock()
        operator.advance_ranked_loop = Mock(return_value=False)
        page = Mock()

        self.assertTrue(operator.handle_early_non_gameplay_screen(page, "lobby", 1.0, b"lobby"))

        operator.advance_ranked_loop.assert_called_once_with(page, "lobby", 1.0, screenshot=b"lobby")
        self.assertFalse(any(
            call.args and call.args[0] == "match_completed_stop"
            for call in operator.log.call_args_list
        ))

    def test_riichi_button_is_not_merged_with_concealed_tile_borders(self) -> None:
        from auto_operator import self_turn_draw_visible
        screenshot = (Path(__file__).resolve().parents[1] / "artifacts/live/riichi-button-hand-border-20260928.jpg").read_bytes()
        buttons = force_auto_self_action_buttons(screenshot, {"width": 1920, "height": 1080})
        self.assertEqual(len(buttons), 1)
        self.assertLess(abs(buttons[0]["center"]["x"] - 1008.5), 3)
        self.assertLess(abs(buttons[0]["center"]["y"] - 824), 2)
        layout = load_json(Path(__file__).resolve().parents[1] / "config/layout.json")
        self.assertTrue(self_turn_draw_visible(screenshot, layout, 0))

    def test_live_red_ron_prompt_is_detected_with_no_draw_tile(self) -> None:
        from auto_operator import self_turn_draw_visible
        root = Path(__file__).resolve().parents[1]
        screenshot = (root / "artifacts/live/red-ron-prompt-20260928.png").read_bytes()
        layout = load_json(root / "config/layout.json")
        self.assertFalse(self_turn_draw_visible(screenshot, layout, 0))
        button = force_auto_reaction_win_button(screenshot, layout["viewport"], layout["actionButtonRegions"]["pass"])
        self.assertIsNotNone(button)
        self.assertLess(abs(button["center"]["x"] - 1002.5), 3)
        self.assertLess(abs(button["center"]["y"] - 828.5), 3)

    def test_result_after_restart_is_saved_without_pending_replays(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.frames = Path(directory)
            operator.pending_round_replays = []
            operator.pending_match_replays = []
            operator.log = Mock()
            self.assertEqual(operator.attach_outcome("round", b"result", 1.0), 0)
            paths = list(operator.frames.glob("*.round_result.png"))
            self.assertEqual(len(paths), 1)
            self.assertEqual(paths[0].read_bytes(), b"result")
            self.assertEqual(operator.log.call_args.args[0], "outcome_observed")
            operator.attach_outcome("round", b"duplicate", 1.0)
            self.assertEqual(len(list(operator.frames.glob("*.round_result.png"))), 1)

    def test_current_hud_riichi_reaches_state_and_rotated_public_cache(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_state = {"seat": "east", "opponents": []}
        operator.log = Mock()
        observation = {"opponentDiscards": [{"seat": "south", "discards": ["N"], "riichiDeclared": False}]}
        metadata = {"verified": True, "seat": "west", "round": "east_2", "scores": {},
                    "honba": 0, "riichiSticks": 1, "riichiSeats": ["north"]}
        with patch("board_metadata.recognize_board", return_value=metadata):
            state, observed, _ = operator.frame_metadata_state(FRAME_FIXTURES / "black-client-20261021.png", observation)
        self.assertTrue(state["opponents"][0]["riichi"])
        self.assertEqual(state["opponents"][0]["seat"], "north")
        self.assertTrue(observed["opponentDiscards"][0]["riichiDeclared"])
        self.assertEqual(operator.public_state["opponents"], [])
        self.assertFalse(observation["opponentDiscards"][0]["riichiDeclared"])

    def test_conserved_riichi_payment_survives_occlusion_and_cached_ocr(self) -> None:
        fixture = load_json(FRAME_FIXTURES / "riichi-declaration-transition-20261021.json")
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_state = {"seat": "east", "opponents": []}
        operator.log = Mock()
        observation = {"opponentDiscards": [{"seat": "north", "discards": ["F", "9p"], "riichiDeclared": False}]}
        operator.current_board_metadata = Mock(side_effect=[fixture["before"], fixture["after"], fixture["after"]])
        frame = FRAME_FIXTURES / "riichi-stick-red-occluded-20261021.jpg"
        operator.frame_metadata_state(frame, observation)
        for _ in range(2):
            state, observed, _ = operator.frame_metadata_state(frame, observation)
            self.assertTrue(next(o for o in state["opponents"] if o["seat"] == "west")["riichi"])
            self.assertTrue(observed["opponentDiscards"][0]["riichiDeclared"])
        self.assertFalse(observation["opponentDiscards"][0]["riichiDeclared"])
        transitions = [c for c in operator.log.call_args_list if c.args == ("riichi_score_transition_verified",)]
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0].kwargs["seats"], ["west"])

    def test_failed_replay_keeps_parallel_timing_and_capture_budget_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.replays = Path(directory)
            operator.pending_round_replays = []
            operator.pending_match_replays = []
            evaluation = {"state": {}, "recognition": {}, "decision": {"selectedActionId": "discard_1m"},
                          "operatorTiming": {"parallelHandRecognitionMs": 1800, "parallelBoardMetadataMs": 1300,
                                             "forceAutoRecognitionAndDecisionMs": 2200},
                          "turnTiming": {"clickBudgetMs": 2600, "captureAgeBeforeDecisionMs": 2786},
                          "publicCache": {"ageMs": 900}}
            path = operator.record_replay(evaluation, Path("frame.jpg"), execution_error="budget expired before click")
            saved = load_json(path)
            self.assertEqual(saved["executionEvidence"]["status"], "failed")
            for key in ("operatorTiming", "turnTiming", "publicCache"):
                self.assertEqual(saved["evidence"][key], evaluation[key])

    def test_public_result_completed_during_ocr_is_promoted_before_seat_remap(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_state = {"seat": "east", "opponents": []}
        operator.log = Mock()
        operator.cached_public_observation = None
        fresh = {"opponentDiscards": [{"seat": "south", "discards": ["N"], "riichiDeclared": False}]}
        operator.poll_public_recognition = Mock(side_effect=lambda: setattr(operator, "cached_public_observation", fresh))
        metadata = {"verified": True, "seat": "west", "round": "east_2", "scores": {},
                    "honba": 0, "riichiSticks": 1, "riichiSeats": ["north"]}
        with patch("board_metadata.recognize_board", return_value=metadata):
            _, observed, _ = operator.frame_metadata_state(FRAME_FIXTURES / "black-client-20261021.png", refresh_public_cache=True)
        operator.poll_public_recognition.assert_called_once()
        self.assertEqual(observed["opponentDiscards"][0]["seat"], "north")
        self.assertEqual(observed["opponentDiscards"][0]["discards"], ["N"])
        self.assertTrue(observed["opponentDiscards"][0]["riichiDeclared"])
        self.assertFalse(fresh["opponentDiscards"][0]["riichiDeclared"])

    def test_reaction_observation_is_not_replaced_by_background_cache(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.public_state = {"seat": "east", "opponents": []}
        operator.log = Mock()
        operator.poll_public_recognition = Mock()
        operator.cached_public_observation = {"ownDiscards": ["1m"]}
        observation = {"ownDiscards": ["1m", "2m"]}
        metadata = {"verified": True, "seat": "east", "round": "east_2", "scores": {},
                    "honba": 0, "riichiSticks": 0}
        with patch("board_metadata.recognize_board", return_value=metadata):
            _, observed, _ = operator.frame_metadata_state(FRAME_FIXTURES / "black-client-20261021.png", observation)
        operator.poll_public_recognition.assert_not_called()
        self.assertEqual(observed["ownDiscards"], ["1m", "2m"])

    def test_force_auto_public_prompt_uses_same_hybrid_backend_as_cache(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.root = Path.cwd()
        operator.layout_path = Path("layout.json")
        operator.templates = Path("templates")
        operator.evaluator_env = {}
        operator.public_state = {"seat": "east"}
        for mode in ("force-auto", "auto"):
            operator.args = argparse.Namespace(mode=mode, evaluation_timeout=30)
            with patch("auto_operator.subprocess.run", return_value=argparse.Namespace(
                    returncode=0, stdout='{"ownDiscards": []}')) as run:
                self.assertEqual(operator.observe_public_board(Path("prompt.png")), {"ownDiscards": []})
                self.assertEqual("--backend=hybrid" in run.call_args.args[0], mode == "force-auto")

    def test_fresh_recognition_disagreement_prevents_click(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(mode="auto", allow_local_discard=False,
                consensus_frames=3, stability_ms=10, evaluation_timeout=30)
            operator.frames = Path(directory)
            operator.root = Path(directory)
            operator.layout_path = Path(directory) / "layout.json"
            operator.templates = Path(directory) / "templates"
            operator.evaluator_env = {}
            page = Mock()
            page.screenshot.return_value = b"image"
            evaluation = {"decision": {"executable": True}, "recognition": {"tiles": ["1m"], "safe": True}}
            for fresh in ({"safe": True, "tiles": ["2m"]}, {"safe": False, "tiles": ["1m"]}):
                with patch("auto_operator.subprocess.run", return_value=argparse.Namespace(returncode=0, stdout=json.dumps(fresh))):
                    with self.assertRaisesRegex(RuntimeError, "disagrees"):
                        operator.execute(page, evaluation)
                page.mouse.click.assert_not_called()

    def test_force_auto_rejects_a_hand_that_changed_since_evaluation_without_rerecognition(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(
            mode="force-auto", allow_local_discard=False, consensus_frames=3,
            stability_ms=10, stability_pixel_delta=1.5, evaluation_timeout=30,
        )
        operator.hand_clip = {"x": 0, "y": 0, "width": 10, "height": 10}
        operator.layout = {
            "clickPoints": [{"x": 5, "y": 5}] * 14,
            "viewport": {"width": 1920, "height": 1080},
        }
        black = io.BytesIO()
        white = io.BytesIO()
        full = io.BytesIO()
        Image.new("RGB", (10, 10), "black").save(black, format="PNG")
        Image.new("RGB", (10, 10), "white").save(white, format="PNG")
        Image.new("RGB", (1920, 1080), "white").save(full, format="PNG")
        page = Mock()
        page.screenshot.side_effect = lambda **kwargs: white.getvalue() if kwargs.get("clip") else full.getvalue()
        evaluation = {
            "decision": {"executable": True, "selectedAction": {"action": "discard", "tile": "1m"}},
            "recognition": {"tiles": ["1m"] * 14, "safe": False},
            "clickIndex": 0,
        }

        with patch("auto_operator.subprocess.run") as run:
            with self.assertRaisesRegex(RuntimeError, "changed since evaluation"):
                operator.execute(page, evaluation, evaluated_hand=black.getvalue())

        run.assert_not_called()
        page.mouse.click.assert_not_called()

    def test_live_open_hand_stream_reaches_discard_receipt_with_equivalent_capture(self) -> None:
        project = Path(__file__).resolve().parents[1]
        source = Image.open(project / "artifacts" / "debug-300-live-now2.png").convert("RGB")
        encoded = io.BytesIO()
        source.save(encoded, format="JPEG", quality=55)
        streamed_full = encoded.getvalue()
        hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        evaluated_hand = crop_screenshot(streamed_full, hand_clip)

        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(
            mode="force-auto", allow_local_discard=False,
            stability_pixel_delta=1.5,
        )
        operator.hand_clip = hand_clip
        operator.river_clip = {"x": 740, "y": 520, "width": 430, "height": 300}
        operator.layout = load_json(project / "config" / "layout.json")
        operator.cached_open_melds = 1
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = streamed_full
        operator.screencast_draw_generation = 4
        operator.log = Mock()
        operator.confirm_discard = Mock(return_value={
            "confirmation": "hand_and_own_river_changed",
            "tileMultisetVerification": {"verified": True},
        })
        page = Mock()
        evaluation = {
            "decision": {
                "selectedAction": {"action": "discard", "tile": "3s"},
            },
            "recognition": {"tiles": ["4m", "1p", "2p", "3p", "4p", "5p",
                                      "6p", "7p", "8s", "8s", "3s"], "safe": True},
            "clickIndex": 10,
            "clickPoint": {"x": 1247, "y": 999},
            "openMelds": 1,
        }

        receipt = operator.execute(
            page, evaluation,
            evaluated_hand=evaluated_hand,
            evaluated_full=streamed_full,
            evaluated_draw_generation=4,
        )

        self.assertTrue(receipt["clicked"])
        self.assertEqual(receipt["confirmation"], "hand_and_own_river_changed")
        self.assertTrue(receipt["tileMultisetVerification"]["verified"])
        operator.confirm_discard.assert_called_once()
        self.assertEqual(page.mouse.click.call_args_list, [call(1247, 999), call(1247, 955, delay=80)])

    def test_post_pon_animation_uses_stable_tile_faces_and_discards_within_clock(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frames = project / "artifacts" / "friend-5-20" / "frames"
        evaluated_full = (frames / "2026-09-21T06-08-02.365938+00-00.jpg").read_bytes()
        current_full = (frames / "2026-09-21T06-08-04.655959+00-00.jpg").read_bytes()
        layout = load_json(project / "config" / "layout.json")
        hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        stable_region = stable_hand_comparison_region(layout, 1)
        self.assertIsNotNone(stable_region)
        self.assertGreater(
            mean_pixel_delta(crop_screenshot(evaluated_full, hand_clip),
                             crop_screenshot(current_full, hand_clip)),
            5.0,
        )
        self.assertLess(
            mean_pixel_delta(crop_screenshot(evaluated_full, stable_region),
                             crop_screenshot(current_full, stable_region)),
            1.5,
        )
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = layout
        operator.hand_clip = hand_clip
        operator.river_clip = {"x": 740, "y": 520, "width": 430, "height": 300}
        operator.cached_open_melds = 1
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = current_full
        operator.screencast_draw_generation = 7
        operator.log = Mock()
        operator.confirm_discard = Mock(return_value={"confirmation": "hand_and_own_river_changed"})
        page = Mock()
        evaluation = {
            "decision": {"selectedAction": {"action": "discard", "tile": "C"}},
            "recognition": {"tiles": ["1m"] * 10 + ["C"], "safe": False},
            "clickIndex": 10,
            "clickPoint": {"x": 1217.5, "y": 996.5},
            "openMelds": 1,
        }

        started = time.monotonic()
        receipt = operator.execute(
            page, evaluation,
            evaluated_hand=crop_screenshot(evaluated_full, hand_clip),
            evaluated_full=evaluated_full,
            evaluated_draw_generation=7,
        )

        self.assertTrue(receipt["clicked"])
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertEqual(page.mouse.click.call_args_list, [call(1217.5, 996.5), call(1217.5, 952.5, delay=80)])

    def test_three_meld_relighting_uses_glyph_structure_and_discards_within_clock(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frames = project / "artifacts" / "friend-5-20" / "frames"
        evaluated_full = (frames / "2026-09-21T06-33-10.603818+00-00.jpg").read_bytes()
        current_full = (frames / "2026-09-21T06-33-12.833862+00-00.jpg").read_bytes()
        layout = load_json(project / "config" / "layout.json")
        hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        stable_region = stable_hand_comparison_region(layout, 3)
        self.assertIsNotNone(stable_region)
        evaluated_faces = crop_screenshot(evaluated_full, stable_region)
        current_faces = crop_screenshot(current_full, stable_region)
        self.assertGreater(mean_pixel_delta(evaluated_faces, current_faces), 1.5)
        self.assertLess(stable_hand_delta(evaluated_faces, current_faces, 3), 1.5)

        changed = io.BytesIO()
        Image.new("RGB", (454, 108), "black").save(changed, format="PNG")
        unchanged = io.BytesIO()
        Image.new("RGB", (454, 108), "white").save(unchanged, format="PNG")
        self.assertGreater(stable_hand_delta(changed.getvalue(), unchanged.getvalue(), 3), 1.5)

        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = layout
        operator.hand_clip = hand_clip
        operator.river_clip = {"x": 740, "y": 520, "width": 430, "height": 300}
        operator.cached_open_melds = 3
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = current_full
        operator.screencast_draw_generation = 11
        operator.log = Mock()
        operator.confirm_discard = Mock(return_value={"confirmation": "hand_and_own_river_changed"})
        page = Mock()
        evaluation = {
            "decision": {"selectedAction": {"action": "discard", "tile": "5p"}},
            "recognition": {"tiles": ["1p", "2p", "3p", "4p", "5p"], "safe": True},
            "clickIndex": 0,
            "clickPoint": {"x": 268.5, "y": 999.5},
            "openMelds": 3,
        }

        started = time.monotonic()
        receipt = operator.execute(
            page, evaluation,
            evaluated_hand=crop_screenshot(evaluated_full, hand_clip),
            evaluated_full=evaluated_full,
            evaluated_draw_generation=11,
        )

        self.assertTrue(receipt["clicked"])
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertEqual(page.mouse.click.call_args_list, [call(268.5, 999.5), call(268.5, 955.5, delay=80)])

    def test_closed_hand_relighting_uses_glyph_structure(self) -> None:
        """A live East-2 retry must not turn static tile faces into a stale turn.

        The paired frames are from the same 14-tile closed hand in the 300+0
        CPU regression.  RGB changes from Mahjong Soul's row relighting,
        whereas the tile glyphs did not change.  This is the false abort that
        previously repeated until a later fresh recognition happened to pass.
        """
        project = Path(__file__).resolve().parents[1]
        frames = project / "artifacts" / "friend-300-038767b-room61662-20261003" / "frames"
        evaluated_full = (frames / "2026-10-02T17-59-05.837878+00-00.jpg").read_bytes()
        current_full = (frames / "2026-10-02T17-59-09.206336+00-00.identity.jpg").read_bytes()
        layout = load_json(project / "config" / "layout-300-regression.json")
        stable_region = stable_hand_comparison_region(layout, 0)
        self.assertIsNotNone(stable_region)
        evaluated_faces = crop_screenshot(evaluated_full, stable_region)
        current_faces = crop_screenshot(current_full, stable_region)

        self.assertGreater(mean_pixel_delta(evaluated_faces, current_faces), 1.5)
        self.assertLess(stable_hand_delta(evaluated_faces, current_faces, 0), 1.5)

        # A real face substitution remains well beyond the same guard.  The
        # adjacent 6p/7p faces in this hand are deliberately compared at the
        # same tile ROI dimensions rather than relying on a synthetic image.
        slots = layout["handSlots"]
        def face(index):
            slot = slots[index]
            return crop_screenshot(evaluated_full, {
                "x": slot["x"] + 10, "y": slot["y"] + 10,
                "width": slot["width"] - 20, "height": slot["height"] - 38,
            })
        self.assertGreater(tile_face_structure_delta(face(7), face(8)), 1.5)

    def test_two_meld_post_pon_sequence_discards_before_calibrated_fallback(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frames = project / "artifacts" / "friend-5-20" / "frames"
        evaluated_full = (frames / "2026-09-21T07-14-38.165982+00-00.jpg").read_bytes()
        current_full = (frames / "2026-09-21T07-14-40.481981+00-00.jpg").read_bytes()
        layout = load_json(project / "config" / "layout.json")
        hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        stable_region = stable_hand_comparison_region(layout, 2)
        evaluated_faces = crop_screenshot(evaluated_full, stable_region)
        current_faces = crop_screenshot(current_full, stable_region)
        self.assertGreater(mean_pixel_delta(evaluated_faces, current_faces), 1.5)
        self.assertLess(stable_hand_delta(evaluated_faces, current_faces, 2), 1.5)

        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = layout
        operator.hand_clip = hand_clip
        operator.river_clip = {"x": 740, "y": 520, "width": 430, "height": 300}
        operator.cached_open_melds = 2
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = current_full
        operator.screencast_draw_generation = 19
        operator.log = Mock()
        operator.confirm_discard = Mock(return_value={"confirmation": "hand_and_own_river_changed"})
        page = Mock()
        evaluation = {
            "decision": {"selectedAction": {"action": "discard", "tile": "8p"}},
            "recognition": {"tiles": ["1m", "3m", "4m", "4p", "7p", "8p", "1s", "5m"], "safe": False},
            "clickIndex": 5,
            "clickPoint": {"x": 743, "y": 996.5},
            "openMelds": 2,
        }

        started = time.monotonic()
        receipt = operator.execute(
            page, evaluation,
            evaluated_hand=crop_screenshot(evaluated_full, hand_clip),
            evaluated_full=evaluated_full,
            evaluated_draw_generation=19,
        )

        self.assertTrue(receipt["clicked"])
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertEqual(page.mouse.click.call_args_list, [call(743, 996.5), call(743, 952.5, delay=80)])

    def test_three_meld_moving_layout_uses_same_generation_selected_tile(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frames = project / "artifacts" / "friend-5-20" / "frames"
        evaluated_full = (frames / "2026-09-21T07-21-29.280894+00-00.jpg").read_bytes()
        settled_full = (frames / "2026-09-21T07-21-32.547775+00-00.jpg").read_bytes()
        layout = load_json(project / "config" / "layout.json")
        hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        stable_region = stable_hand_comparison_region(layout, 3)
        click_point = {"x": 363.5, "y": 996.5}
        selected_region = selected_tile_comparison_region(layout, click_point, 3)
        self.assertGreater(
            stable_hand_delta(crop_screenshot(evaluated_full, stable_region),
                              crop_screenshot(settled_full, stable_region), 3),
            20,
        )
        self.assertLess(
            stable_hand_delta(crop_screenshot(evaluated_full, selected_region),
                              crop_screenshot(settled_full, selected_region), 3),
            1.5,
        )

        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = layout
        operator.hand_clip = hand_clip
        operator.river_clip = {"x": 740, "y": 520, "width": 430, "height": 300}
        operator.cached_open_melds = 3
        # A later compact-hand discard needs the same selected-tile anchor,
        # even when it did not immediately follow a call.
        operator.pending_post_call_discard = False
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = settled_full
        operator.screencast_draw_generation = 23
        operator.log = Mock()
        operator.confirm_discard = Mock(return_value={"confirmation": "hand_and_own_river_changed"})
        page = Mock()
        evaluation = {
            "decision": {"selectedAction": {"action": "discard", "tile": "6p"}},
            "recognition": {"tiles": ["6m", "6p", "1s", "7s", "8s"], "safe": False},
            "clickIndex": 1,
            "clickPoint": click_point,
            "openMelds": 3,
        }

        started = time.monotonic()
        receipt = operator.execute(
            page, evaluation,
            evaluated_hand=crop_screenshot(evaluated_full, hand_clip),
            evaluated_full=evaluated_full,
            evaluated_draw_generation=23,
        )

        self.assertTrue(receipt["clicked"])
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertEqual(page.mouse.click.call_args_list, [call(363.5, 996.5), call(363.5, 952.5, delay=80)])

        changed_target = Image.open(io.BytesIO(settled_full)).convert("RGB")
        ImageDraw.Draw(changed_target).rectangle((328, 936, 399, 1044), fill="white")
        changed_bytes = io.BytesIO()
        changed_target.save(changed_bytes, format="PNG")
        self.assertGreater(
            stable_hand_delta(crop_screenshot(evaluated_full, selected_region),
                              crop_screenshot(changed_bytes.getvalue(), selected_region), 3),
            1.5,
        )

    def test_live_over_inferred_meld_count_and_out_of_hand_click_are_rejected(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        self.assertFalse(discard_point_in_hand_geometry(
            {"x": 1612.5, "y": 821.5}, layout, 1,
        ))

        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = layout
        operator.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        operator.river_clip = {"x": 740, "y": 520, "width": 430, "height": 300}
        operator.cached_open_melds = 1
        operator.screencast_session = Mock()
        frame = (project / "artifacts" / "debug-300" / "frames" /
                 "2026-09-21T04-23-11.396987+00-00.jpg").read_bytes()
        operator.latest_screencast_frame = frame
        operator.screencast_draw_generation = 2
        operator.log = Mock()
        page = Mock()
        evaluation = {
            "decision": {"selectedAction": {"action": "discard", "tile": "6p"}},
            "recognition": {"tiles": ["6p", "6p"], "safe": False},
            "clickIndex": 1,
            "clickPoint": {"x": 1612.5, "y": 821.5},
            "openMelds": 4,
        }

        with self.assertRaisesRegex(RetryableSafetyAbort, "does not match confirmed open meld count"):
            operator.execute(
                page, evaluation,
                evaluated_hand=crop_screenshot(frame, operator.hand_clip),
                evaluated_full=frame,
                evaluated_draw_generation=2,
            )
        page.mouse.click.assert_not_called()

    def test_live_frame_anchors_pre_click_meld_count_to_confirmed_call(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frame = (project / "artifacts" / "debug-300" / "frames" /
                 "2026-09-21T05-03-29.704020+00-00.jpg").read_bytes()
        hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = load_json(project / "config" / "layout.json")
        operator.hand_clip = hand_clip
        operator.river_clip = {"x": 740, "y": 520, "width": 430, "height": 300}
        operator.cached_open_melds = 1
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = frame
        operator.screencast_draw_generation = 9
        operator.log = Mock()
        operator.confirm_discard = Mock(return_value={"confirmation": "live-frame-confirmed"})
        page = Mock()
        evaluation = {
            "decision": {"selectedAction": {"action": "discard", "tile": "7m"}},
            # Eleven tiles prove the compact one-meld self-turn geometry even
            # though the old generic proposal promoted the top-level count.
            "recognition": {"tiles": ["1m"] * 10 + ["7m"], "safe": True},
            "clickIndex": 10,
            "clickPoint": {"x": 1247, "y": 999},
            "openMelds": 4,
        }

        receipt = operator.execute(
            page, evaluation,
            evaluated_hand=crop_screenshot(frame, hand_clip),
            evaluated_full=frame,
            evaluated_draw_generation=9,
        )

        self.assertTrue(receipt["clicked"])
        operator.log.assert_any_call(
            "open_meld_revalidation_anchored",
            confirmedOpenMelds=1,
            rejectedInferredOpenMelds=4,
            recognizedConcealedTiles=11,
        )
        self.assertEqual(page.mouse.click.call_args_list, [call(1247, 999), call(1247, 955, delay=80)])

    def test_pre_click_meld_anchor_rejects_genuine_compact_geometry_change(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frame = (project / "artifacts" / "debug-300" / "frames" /
                 "2026-09-21T05-03-29.704020+00-00.jpg").read_bytes()
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = load_json(project / "config" / "layout.json")
        operator.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        operator.river_clip = {"x": 740, "y": 520, "width": 430, "height": 300}
        operator.cached_open_melds = 1
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = frame
        operator.screencast_draw_generation = 10
        operator.log = Mock()
        page = Mock()
        evaluation = {
            "decision": {"selectedAction": {"action": "discard", "tile": "7m"}},
            "recognition": {"tiles": ["1m"] * 8, "safe": True},
            "clickIndex": 7,
            "clickPoint": {"x": 1100, "y": 999},
            "openMelds": 2,
        }

        with self.assertRaisesRegex(RetryableSafetyAbort, "expected 11 concealed tiles, recognized 8"):
            operator.execute(
                page, evaluation,
                evaluated_hand=crop_screenshot(frame, operator.hand_clip),
                evaluated_full=frame,
                evaluated_draw_generation=10,
            )
        page.mouse.click.assert_not_called()

    def test_open_meld_count_requires_distinct_frames_and_rejects_jump(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.cached_open_melds = 0
        operator.open_meld_candidate = None
        operator.open_meld_candidate_frames = set()
        self.assertIsNone(operator.stable_open_meld_count(1, b"frame-a"))
        self.assertIsNone(operator.stable_open_meld_count(1, b"frame-a"))
        self.assertEqual(operator.stable_open_meld_count(1, b"frame-b"), 1)
        operator.cached_open_melds = 1
        self.assertIsNone(operator.stable_open_meld_count(2, b"frame-c"))

    def test_private_env_loader_passes_only_jev_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.local"
            path.write_text(
                "TYPESAFE_API_KEY=test-secret\nIGNORED=value\nJEV_MODEL=test-model\n"
                "JEV_FORCE_AUTO_DEADLINE_MS=2300\nFORCE_AUTO_CLICK_BUDGET_MS=2600\n",
                encoding="utf-8",
            )
            path.chmod(0o600)
            environment = load_secret_environment(Path(directory), ".env.local")
            self.assertEqual(environment["TYPESAFE_API_KEY"], "test-secret")
            self.assertEqual(environment["JEV_MODEL"], "test-model")
            self.assertEqual(environment["JEV_FORCE_AUTO_DEADLINE_MS"], "2300")
            self.assertEqual(environment["FORCE_AUTO_CLICK_BUDGET_MS"], "2600")
            self.assertNotIn("IGNORED", environment)

    def test_env_loader_rejects_group_readable_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.local"
            path.write_text("TYPESAFE_API_KEY=test-secret\n", encoding="utf-8")
            path.chmod(0o640)
            with patch("auto_operator.sys.platform", "linux"):
                with self.assertRaisesRegex(RuntimeError, "group/world"):
                    load_secret_environment(Path(directory), ".env.local")

    def test_env_loader_uses_acl_managed_secret_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.local"
            path.write_text("TYPESAFE_API_KEY=test-secret\n", encoding="utf-8")
            with patch("auto_operator.sys.platform", "win32"):
                environment = load_secret_environment(Path(directory), ".env.local")
            self.assertEqual(environment["TYPESAFE_API_KEY"], "test-secret")

    def test_detects_dark_popup_with_gold_resume_button(self) -> None:
        viewport = {"width": 1920, "height": 1080}
        image = Image.new("RGB", (1920, 1080), (20, 40, 70))
        button, popup = away_resume_geometry(viewport)
        draw = ImageDraw.Draw(image)
        draw.rectangle((popup["x"], popup["y"], popup["x"] + popup["width"], popup["y"] + popup["height"]), fill=(40, 45, 60))
        draw.rectangle((button["x"], button["y"], button["x"] + button["width"], button["y"] + button["height"]), fill=(230, 190, 90))
        output = io.BytesIO()
        image.save(output, format="PNG")
        self.assertTrue(is_away_resume_dialog(output.getvalue(), viewport))

    def test_rejects_normal_dark_table_without_gold_button(self) -> None:
        viewport = {"width": 1920, "height": 1080}
        image = Image.new("RGB", (1920, 1080), (20, 40, 70))
        output = io.BytesIO()
        image.save(output, format="PNG")
        self.assertFalse(is_away_resume_dialog(output.getvalue(), viewport))

    def test_terminal_latch_allows_verified_away_resume_before_unknown_wait(self) -> None:
        """A terminal result latch cannot hide the strict away-dialog recovery."""
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(resume_away=True)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.round_terminal_latched = True
        operator.round_terminal_result_observed = True
        operator.round_terminal_unknown_since = 123.0
        operator.resume_if_away = Mock(return_value=True)
        operator.log = Mock()
        page = Mock()

        self.assertTrue(operator.wait_for_round_terminal(page, b"away-frame", "unknown"))

        operator.resume_if_away.assert_called_once_with(page, b"away-frame")
        self.assertIsNone(operator.round_terminal_unknown_since)
        operator.log.assert_called_once_with("round_terminal_away_resumed", gameplayClicks=0)

    def test_terminal_latch_unknown_screen_stops_after_bounded_wait(self) -> None:
        """A non-away unknown modal is evidence-preserved, never polled forever."""
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(resume_away=True)
            operator.layout = {"viewport": {"width": 1920, "height": 1080}}
            operator.frames = Path(directory)
            operator.round_terminal_latched = True
            operator.round_terminal_result_observed = True
            operator.round_terminal_unknown_since = None
            operator.resume_if_away = Mock(return_value=False)
            operator.log = Mock()
            page = Mock()
            with patch("auto_operator.time.monotonic", side_effect=[100.0, 130.1]):
                self.assertTrue(operator.wait_for_round_terminal(page, b"unknown", "unknown"))
                with self.assertRaisesRegex(RuntimeError, "unknown screen"):
                    operator.wait_for_round_terminal(page, b"unknown", "unknown")
            stops = [entry for entry in operator.log.call_args_list
                     if entry.args == ("round_terminal_unknown_screen_stop",)]
            self.assertEqual(len(stops), 1)
            self.assertTrue(Path(stops[0].kwargs["screenshot"]).exists())
            self.assertEqual(stops[0].kwargs["gameplayClicks"], 0)

    def test_local_discard_requires_explicit_flag_and_safe_discard(self) -> None:
        evaluation = {"decision": {"recommendedAction": "discard", "confidence": 0.55, "safety": {"allowed": True}}}
        self.assertTrue(local_discard_allowed(argparse.Namespace(allow_local_discard=True, mode="advisor"), evaluation))
        self.assertFalse(local_discard_allowed(argparse.Namespace(allow_local_discard=False, mode="advisor"), evaluation))
        evaluation["decision"]["safety"]["allowed"] = False
        self.assertFalse(local_discard_allowed(argparse.Namespace(allow_local_discard=True, mode="advisor"), evaluation))

    def test_discard_selects_and_confirms_the_same_guarded_coordinate(self) -> None:
        layout = load_json(Path(__file__).resolve().parents[1] / "config/layout-300-regression.json")
        point = layout["clickPoints"][7]
        before, after = self.raised_tile_frames(layout, 7, 28)
        mouse = RecordingMouse()
        settle = Mock()
        confirmation = send_discard_click(
            mouse,
            point,
            {"width": 1920, "height": 1080},
            settle,
            before,
            lambda _: after,
            layout,
            7,
            1.5,
        )
        self.assertEqual(mouse.calls, [
            (933, 999, {}),
            (933, 971, {"delay": 80}),
            ("move", 960, 777.6),
        ])
        self.assertEqual(confirmation["lift"], 28)
        settle.assert_called_once_with(40)

    def test_discard_polls_until_a_later_receipt_proves_lift(self) -> None:
        """A receipt before the client animation must not cause a false abort."""
        layout = load_json(Path(__file__).resolve().parents[1] / "config/layout-300-regression.json")
        point = layout["clickPoints"][13]
        before, after = self.raised_tile_frames(layout, 13, 48)
        mouse = RecordingMouse()
        settle = Mock()
        receipts = iter((before, after))
        confirmation = send_discard_click(
            mouse, point, {"width": 1920, "height": 1080}, settle, before,
            lambda _: next(receipts), layout, 13, 1.5,
        )
        self.assertEqual(confirmation["lift"], 48)
        self.assertEqual(settle.call_args_list, [call(40), call(40)])
        self.assertEqual(mouse.calls[:2], [
            (1532, 999, {}), (1532.0, 951.0, {"delay": 80}),
        ])

    def test_discard_does_not_confirm_after_second_click_budget_expires(self) -> None:
        """A selected tile is latched rather than risk a late second click."""
        layout = load_json(Path(__file__).resolve().parents[1] / "config/layout-300-regression.json")
        point = layout["clickPoints"][7]
        before, after = self.raised_tile_frames(layout, 7, 28)
        mouse = RecordingMouse()
        with self.assertRaisesRegex(SelectionStateUncertainAbort, "confirmation withheld"):
            send_discard_click(
                mouse, point, {"width": 1920, "height": 1080}, Mock(), before,
                lambda _: after, layout, 7, 1.5,
                lambda: (_ for _ in ()).throw(
                    RetryableSafetyAbort("force-auto click budget expired before safe click")
                ),
            )
        self.assertEqual(mouse.calls, [
            (933, 999, {}), ("move", 960, 777.6),
        ])

    def test_discard_unproven_selection_never_retries_as_a_deselect(self) -> None:
        layout = load_json(Path(__file__).resolve().parents[1] / "config/layout-300-regression.json")
        point = layout["clickPoints"][7]
        before, _ = self.raised_tile_frames(layout, 7, 28)
        mouse = RecordingMouse()
        settle = Mock()
        with self.assertRaisesRegex(SelectionStateUncertainAbort, "could not be verified") as caught:
            send_discard_click(
                mouse, point, {"width": 1920, "height": 1080}, settle, before,
                lambda _: before, layout, 7, 1.5,
            )
        self.assertIsInstance(caught.exception, RetryableSafetyAbort)
        self.assertEqual(settle.call_args_list, [
            call(40), call(40), call(60), call(80), call(100), call(120),
        ])
        self.assertEqual(mouse.calls, [
            (933, 999, {}), ("move", 960, 777.6),
        ])

    def test_selection_receipt_rejects_stale_pre_click_screencast_frame(self) -> None:
        """A queued action-gate frame is never proof for the second click."""
        layout = load_json(Path(__file__).resolve().parents[1] / "config/layout-300-regression.json")
        point = layout["clickPoints"][9]
        before, raised = self.raised_tile_frames(layout, 9, 19)
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.latest_screencast_frame = raised
        operator.screencast_sequence = 12
        mouse = RecordingMouse()
        settle = Mock()

        def stale_receipt(first_click_at):
            operator.latest_screencast_captured_at = first_click_at - 0.001
            return operator.fresh_screencast_selection_receipt(11, first_click_at)

        with self.assertRaises(SelectionStateUncertainAbort):
            send_discard_click(
                mouse, point, {"width": 1920, "height": 1080}, settle, before,
                stale_receipt, layout, 9, 1.5,
            )
        self.assertEqual(mouse.calls, [(1122.5, 999, {}), ("move", 960.0, 777.6)])

    def test_selection_receipt_accepts_fresh_compact_hand_lift_without_screenshot(self) -> None:
        """The precise open-meld slot is confirmed from a later stream frame."""
        layout = load_json(Path(__file__).resolve().parents[1] / "config/layout-300-regression.json")
        point = layout["clickPoints"][9]
        before, raised = self.raised_tile_frames(layout, 9, 19)
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.latest_screencast_frame = before
        operator.screencast_sequence = 12
        operator.latest_screencast_captured_at = 0.0
        synchronous_screenshot = Mock(side_effect=AssertionError("selection receipt must not screenshot"))
        mouse = RecordingMouse()

        def wait_for_stream(_):
            operator.latest_screencast_frame = raised
            operator.screencast_sequence = 13
            operator.latest_screencast_captured_at = time.monotonic()

        confirmation = send_discard_click(
            mouse, point, {"width": 1920, "height": 1080}, wait_for_stream, before,
            lambda first_click_at: operator.fresh_screencast_selection_receipt(12, first_click_at),
            layout, 9, 1.5,
        )
        self.assertEqual(confirmation["lift"], 19)
        # The later stream frame supplies the only input hitbox which is
        # known to remain on the selected physical tile.
        self.assertEqual(mouse.calls[:2], [(1122.5, 999, {}), (1122.5, 980.0, {"delay": 80})])
        synchronous_screenshot.assert_not_called()

    def test_selection_receipt_rejects_fresh_unraised_compact_frame(self) -> None:
        layout = load_json(Path(__file__).resolve().parents[1] / "config/layout-300-regression.json")
        point = layout["clickPoints"][9]
        before, unraised = self.raised_tile_frames(layout, 9, 0)
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.latest_screencast_frame = unraised
        operator.screencast_sequence = 13
        mouse = RecordingMouse()
        evidence = Mock()

        def fresh_unraised(first_click_at):
            operator.latest_screencast_captured_at = first_click_at + 0.001
            return operator.fresh_screencast_selection_receipt(12, first_click_at)

        with self.assertRaises(SelectionStateUncertainAbort):
            send_discard_click(
                mouse, point, {"width": 1920, "height": 1080}, Mock(), before,
                fresh_unraised, layout, 9, 1.5, on_unverified_selection=evidence,
            )
        self.assertEqual(mouse.calls, [(1122.5, 999, {}), ("move", 960.0, 777.6)])
        evidence.assert_called_once_with(before, unraised)

    def test_uncertain_selection_does_not_rearm_for_changed_hand_pixels(self) -> None:
        """A raised tile changes the crop, but is still the same selectable tile."""
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.selection_uncertainty_latch = {
            "drawGeneration": 17,
            "ownDiscards": ["1m", "4p"],
        }
        operator.screencast_draw_occupied = True

        # The run loop deliberately calls this before its generic hash based
        # rearm.  A different hand hash must therefore not be an input here.
        self.assertIsNone(operator.selection_uncertainty_rearm_reason(
            17, {"ownDiscards": ["1m", "4p"]},
        ))
        self.assertIsNone(operator.selection_uncertainty_rearm_reason(
            17, {"ownDiscards": ["1m", "4p"], "opponentDiscards": [
                {"seat": "south", "discards": ["9s"]},
            ]},
        ))

    def test_uncertain_selection_rearms_only_for_independent_turn_evidence(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.selection_uncertainty_latch = {
            "drawGeneration": 17,
            "ownDiscards": ["1m", "4p"],
        }

        # Public history is merged/corroborated before this method sees it.
        operator.screencast_draw_occupied = False
        self.assertEqual(operator.selection_uncertainty_rearm_reason(
            17, {"ownDiscards": ["1m", "4p", "9s"]},
        ), "confirmed_own_river_append")

        operator.screencast_draw_occupied = True
        self.assertEqual(operator.selection_uncertainty_rearm_reason(
            18, {"ownDiscards": ["1m", "4p"]},
        ), "new_draw_generation")

    @staticmethod
    def raised_tile_frames(layout, index, lift):
        """Make a unique glyph face move upward without changing neighbours."""
        slot = [*layout["handSlots"], layout["drawSlot"]][index]
        before_image = Image.new("RGB", (1920, 1080), "white")
        after_image = Image.new("RGB", (1920, 1080), "white")
        # A deliberately asymmetric dark glyph prevents an unrelated static
        # neighbouring tile from matching the vertical search.
        glyph = (int(slot["x"] + 29), int(slot["y"] + 31),
                 int(slot["x"] + 62), int(slot["y"] + 83))
        before_image.paste("black", glyph)
        after_image.paste("black", (glyph[0], glyph[1] - lift, glyph[2], glyph[3] - lift))
        before_buffer, after_buffer = io.BytesIO(), io.BytesIO()
        before_image.save(before_buffer, format="PNG")
        after_image.save(after_buffer, format="PNG")
        return before_buffer.getvalue(), after_buffer.getvalue()

    def test_raised_tile_confirmation_uses_observed_closed_hand_lift(self) -> None:
        layout = load_json(Path(__file__).resolve().parents[1] / "config/layout-300-regression.json")
        before, after = self.raised_tile_frames(layout, 11, 31)
        point = layout["clickPoints"][11]
        confirmation = raised_tile_confirmation_point(before, after, layout, 11, point, 1.5)
        self.assertEqual(confirmation, {"x": 1312.5, "y": 968.0, "lift": 31.0,
                                        "faceStructureDelta": 0.0})

    def test_native_9p_lift_with_click_sparkle_requires_unique_glyph_match(self) -> None:
        root = Path(__file__).resolve().parents[1]
        layout = load_json(root / "config/layout-300-regression.json")
        before = (root / "test/fixtures/selection-9p-before-20261028.jpg").read_bytes()
        after = (root / "test/fixtures/selection-9p-lift-20261028.jpg").read_bytes()
        result = raised_tile_confirmation_point(before, after, layout, 13,
                                                layout["clickPoints"][13], 1.5)
        self.assertEqual((result["x"], result["y"], result["lift"]),
                         (1532.0, 951.0, 48.0))
        self.assertIn(result.get("verification"), {None, "dark_glyph_overlap"})
        self.assertIsNone(raised_tile_confirmation_point(before, before, layout, 13,
                                                        layout["clickPoints"][13], 1.5))
        self.assertIsNone(raised_tile_confirmation_point(before, after, layout, 12,
                                                        layout["clickPoints"][12], 1.5))
        with Image.open(io.BytesIO(after)) as image:
            altered = image.convert("RGB")
        ImageDraw.Draw(altered).rectangle((1496, 918, 1566, 1026), fill="white")
        output = io.BytesIO()
        altered.save(output, format="PNG")
        self.assertIsNone(raised_tile_confirmation_point(before, output.getvalue(), layout, 13,
                                                        layout["clickPoints"][13], 1.5))
        # A near-threshold match with a plausible competing vertical offset
        # must not be treated as unique evidence of the selected hitbox.
        deltas = [1.7, 2.0] + [30.0] * 71
        stats = [Mock(sum=[255])] + [Mock(mean=[value * 255 / 100]) for value in deltas]
        with patch("auto_operator.ImageStat.Stat", side_effect=stats):
            self.assertIsNone(raised_tile_confirmation_point(before, after, layout, 13,
                                                            layout["clickPoints"][13], 1.5))

    def test_native_green_and_8s_lifts_ignore_only_small_pink_sparkles(self) -> None:
        root = Path(__file__).resolve().parents[1]
        layout = load_json(root / "config/layout-300-regression.json")
        for name, index in (("8s", 8), ("green", 13)):
            with self.subTest(tile=name):
                before = (root / f"test/fixtures/selection-{name}-before-20261028.jpg").read_bytes()
                after = (root / f"test/fixtures/selection-{name}-lift-20261028.jpg").read_bytes()
                point = layout["clickPoints"][index]
                result = raised_tile_confirmation_point(before, after, layout, index, point, 1.5)
                self.assertEqual(result["lift"], 48.0)
                self.assertLessEqual(result["faceStructureDelta"], 1.5)
                self.assertIsNone(raised_tile_confirmation_point(before, before, layout, index, point, 1.5))
                adjacent = 7 if index == 8 else 12
                self.assertIsNone(raised_tile_confirmation_point(before, after, layout, adjacent,
                                                                layout["clickPoints"][adjacent], 1.5))
                slots = [*layout["handSlots"], layout["drawSlot"]]
                slot = slots[index]
                with Image.open(io.BytesIO(after)) as image:
                    occluded = image.convert("RGB")
                ImageDraw.Draw(occluded).rectangle((slot["x"] + 10, slot["y"] - 38,
                    slot["x"] + slot["width"] - 10, slot["y"] + 55), fill=(255, 100, 220))
                output = io.BytesIO()
                occluded.save(output, format="PNG")
                self.assertIsNone(raised_tile_confirmation_point(before, output.getvalue(), layout,
                                                                index, point, 1.5))

    def test_native_white_lift_requires_moving_edge_and_stable_neighbour(self) -> None:
        root = Path(__file__).resolve().parents[1]
        layout = load_json(root / "config/layout-300-regression.json")
        before = (root / "test/fixtures/selection-white-before-20261028.jpg").read_bytes()
        after = (root / "test/fixtures/selection-white-lift-20261028.jpg").read_bytes()
        point = layout["clickPoints"][12]
        result = raised_tile_confirmation_point(before, after, layout, 12, point, 1.5)
        self.assertEqual(result["lift"], 48.0)
        self.assertEqual(result["verification"], "blank_tile_edge_and_stable_neighbour")
        # The live 300+0 calibration has a 921px slot top while the tile rim
        # begins at 922px and its neutral face at 927px.  That six-pixel crop
        # convention must not override the observed rim/lift evidence.
        live_geometry = json.loads(json.dumps(layout))
        live_geometry["handSlots"][12].update({"y": 921, "height": 151})
        live_geometry["handSlots"][11].update({"y": 921, "height": 151})
        live_point = {"x": 1407, "y": 996.5}
        self.assertEqual(raised_tile_confirmation_point(before, after, live_geometry, 12,
                                                        live_point, 1.5)["lift"], 48.0)
        out_of_range_geometry = json.loads(json.dumps(live_geometry))
        out_of_range_geometry["handSlots"][12]["y"] = 918
        self.assertIsNone(raised_tile_confirmation_point(before, after, out_of_range_geometry, 12,
                                                        live_point, 1.5))
        self.assertIsNone(raised_tile_confirmation_point(before, before, layout, 12, point, 1.5))
        self.assertIsNone(raised_tile_confirmation_point(before, after, layout, 11,
                                                        layout["clickPoints"][11], 1.5))
        for rectangle in ((1375, 860, 1445, 910), (1280, 860, 1350, 910),
                          (1375, 872, 1445, 880),
                          (1375, 860, 1445, 1030)):
            with self.subTest(obstruction=rectangle):
                with Image.open(io.BytesIO(after)) as image:
                    obscured = image.convert("RGB")
                ImageDraw.Draw(obscured).rectangle(rectangle, fill=(240, 240, 240))
                output = io.BytesIO()
                obscured.save(output, format="PNG")
                self.assertIsNone(raised_tile_confirmation_point(before, output.getvalue(), layout,
                                                                12, point, 1.5))
        blank = io.BytesIO()
        Image.new("RGB", (1920, 1080), "white").save(blank, format="PNG")
        self.assertIsNone(raised_tile_confirmation_point(blank.getvalue(), blank.getvalue(), layout,
                                                        12, point, 1.5))

    def test_riichi_white_lift_with_timer_covering_top_edge(self) -> None:
        root = Path(__file__).resolve().parents[1]
        layout = load_json(root / "config/layout-300-regression.json")
        layout["handSlots"][12].update({"y": 921, "height": 151})
        layout["handSlots"][11].update({"y": 921, "height": 151})
        point = {"x": 1407, "y": 996.5}
        before = (root / "test/fixtures/selection-white-riichi-timer-before-20261028.png").read_bytes()
        after = (root / "test/fixtures/selection-white-riichi-timer-lift-20261028.png").read_bytes()
        result = raised_tile_confirmation_point(before, after, layout, 12, point, 1.5)
        self.assertEqual(result["lift"], 47.0)
        self.assertIsNone(raised_tile_confirmation_point(before, before, layout, 12, point, 1.5))
        self.assertIsNone(raised_tile_confirmation_point(before, after, layout, 11, layout["clickPoints"][11], 1.5))
        # A single surviving column or a disturbed neighbour cannot establish
        # the intended tile moved, even when the countdown resembles a rim.
        for rect in ((1385, 870, 1400, 900), (1275, 920, 1350, 935)):
            with self.subTest(obstruction=rect):
                with Image.open(io.BytesIO(after)) as image:
                    altered = image.convert("RGB")
                ImageDraw.Draw(altered).rectangle(rect, fill=(235, 235, 235))
                output = io.BytesIO()
                altered.save(output, format="PNG")
                self.assertIsNone(raised_tile_confirmation_point(before, output.getvalue(), layout, 12, point, 1.5))

    def test_white_draw_lift_with_overlapping_countdown_requires_physical_evidence(self) -> None:
        root = Path(__file__).resolve().parents[1]
        layout = load_json(root / "config/layout-300-regression.json")
        # Live geometry used by the operator in this 300+0 match.
        layout["drawSlot"].update({"y": 921, "height": 151})
        layout["handSlots"][12].update({"y": 921, "height": 151})
        point = {"x": 1532, "y": 996.5}
        before = (root / "test/fixtures/selection-white-draw-timer-before-20261028.png").read_bytes()
        after = (root / "test/fixtures/selection-white-draw-timer-lift-20261028.png").read_bytes()
        result = raised_tile_confirmation_point(before, after, layout, 13, point, 1.5)
        self.assertEqual(result["lift"], 48.0)
        self.assertEqual(result["verification"], "blank_tile_edge_and_stable_neighbour")
        self.assertIsNone(raised_tile_confirmation_point(before, before, layout, 13, point, 1.5))
        self.assertIsNone(raised_tile_confirmation_point(before, after, layout, 12,
                                                        layout["clickPoints"][12], 1.5))
        # Hiding the selected rim or disturbing the stationary neighbour must
        # not turn a bright countdown into evidence of a selected tile.
        for rectangle in ((1490, 872, 1575, 880), (1370, 920, 1450, 935),
                          (1490, 860, 1575, 1000)):
            with self.subTest(obstruction=rectangle):
                with Image.open(io.BytesIO(after)) as image:
                    obscured = image.convert("RGB")
                ImageDraw.Draw(obscured).rectangle(rectangle, fill=(235, 235, 235))
                output = io.BytesIO()
                obscured.save(output, format="PNG")
                self.assertIsNone(raised_tile_confirmation_point(before, output.getvalue(), layout,
                                                                13, point, 1.5))

    def test_draw_8s_click_sparkle_masks_only_a_bounded_obstruction(self) -> None:
        root = Path(__file__).resolve().parents[1]
        layout = load_json(root / "config/layout-300-regression.json")
        point = {"x": 1532, "y": 996.5}
        before = (root / "test/fixtures/selection-8s-sparkle-before-20261028.png").read_bytes()
        after = (root / "test/fixtures/selection-8s-sparkle-lift-20261028.png").read_bytes()
        result = raised_tile_confirmation_point(before, after, layout, 13, point, 1.5)
        self.assertEqual(result["lift"], 48.0)
        self.assertEqual(result["verification"], "sparkle_masked_unique_glyph_and_stable_neighbour")
        self.assertIsNone(raised_tile_confirmation_point(before, before, layout, 13, point, 1.5))
        self.assertIsNone(raised_tile_confirmation_point(before, after, layout, 12,
                                                        layout["clickPoints"][12], 1.5))
        # A neighbour lifting is not evidence for the requested draw slot.
        with Image.open(io.BytesIO(before)) as image:
            neighbour_lifted = image.convert("RGB")
        slot = layout["handSlots"][12]
        bounds = tuple(int(value) for value in (slot["x"], slot["y"],
                                                slot["x"] + slot["width"],
                                                slot["y"] + slot["height"]))
        neighbour_face = neighbour_lifted.crop(bounds)
        ImageDraw.Draw(neighbour_lifted).rectangle(bounds, fill=(35, 55, 78))
        neighbour_lifted.paste(neighbour_face, (bounds[0], bounds[1] - 48))
        output = io.BytesIO()
        neighbour_lifted.save(output, format="PNG")
        self.assertIsNone(raised_tile_confirmation_point(before, output.getvalue(), layout,
                                                        13, point, 1.5))
        for rectangle, color in (((1496, 888, 1567, 960), (245, 245, 245)),
                                 ((1496, 888, 1567, 996), (255, 130, 210)),
                                 ((1370, 936, 1440, 1035), (0, 0, 0))):
            with self.subTest(obstruction=rectangle):
                with Image.open(io.BytesIO(after)) as image:
                    altered = image.convert("RGB")
                ImageDraw.Draw(altered).rectangle(rectangle, fill=color)
                output = io.BytesIO()
                altered.save(output, format="PNG")
                self.assertIsNone(raised_tile_confirmation_point(before, output.getvalue(), layout,
                                                                13, point, 1.5))

    def test_paired_west_sparkle_lift_requires_target_and_stable_neighbour(self) -> None:
        root = Path(__file__).resolve().parents[1]
        layout = load_json(root / "config/layout-300-regression.json")
        before = (root / "test/fixtures/selection-paired-west-before-20261029.png").read_bytes()
        after = (root / "test/fixtures/selection-paired-west-lift-20261029.png").read_bytes()
        point = {"x": 1407.5, "y": 999}
        # An identical neighbouring W moving cannot prove this slot moved.
        with Image.open(io.BytesIO(before)) as image:
            wrong_slot = image.convert("RGB")
        neighbour = layout["handSlots"][11]
        box = tuple(int(v) for v in (neighbour["x"], neighbour["y"],
                                     neighbour["x"] + neighbour["width"],
                                     neighbour["y"] + neighbour["height"]))
        tile = wrong_slot.crop(box)
        ImageDraw.Draw(wrong_slot).rectangle(box, fill=(35, 55, 78))
        wrong_slot.paste(tile, (box[0], box[1] - 48))
        wrong_output = io.BytesIO()
        wrong_slot.save(wrong_output, format="PNG")
        self.assertIsNone(raised_tile_confirmation_point(before, wrong_output.getvalue(), layout,
                                                        12, point, 1.5))
        result = raised_tile_confirmation_point(before, after, layout, 12, point, 1.5)
        self.assertEqual(result["lift"], 48.0)
        self.assertEqual(result["verification"], "sparkle_masked_unique_glyph_and_stable_neighbour")
        second_before = (root / "test/fixtures/selection-paired-west-second-before-20261029.png").read_bytes()
        second_after = (root / "test/fixtures/selection-paired-west-second-lift-20261029.png").read_bytes()
        self.assertEqual(raised_tile_confirmation_point(second_before, second_after, layout, 12, point, 1.5)["lift"], 48.0)
        self.assertIsNone(raised_tile_confirmation_point(second_before, second_before, layout, 12, point, 1.5))
        self.assertIsNone(raised_tile_confirmation_point(second_before, second_after, layout, 11,
                                                        layout["clickPoints"][11], 1.5))
        self.assertIsNone(raised_tile_confirmation_point(before, before, layout, 12, point, 1.5))
        self.assertIsNone(raised_tile_confirmation_point(before, after, layout, 11,
                                                        layout["clickPoints"][11], 1.5))
        for rectangle, color in (((1370, 880, 1445, 1020), (240, 240, 240)),
                                 ((1275, 936, 1350, 1030), (0, 0, 0)),
                                 ((1370, 880, 1445, 1020), (255, 130, 210))):
            with self.subTest(obstruction=rectangle):
                with Image.open(io.BytesIO(after)) as image:
                    altered = image.convert("RGB")
                ImageDraw.Draw(altered).rectangle(rectangle, fill=color)
                output = io.BytesIO()
                altered.save(output, format="PNG")
                self.assertIsNone(raised_tile_confirmation_point(before, output.getvalue(), layout,
                                                                12, point, 1.5))

    def test_glyph_overlap_fallback_requires_a_unique_target_lift(self) -> None:
        """A selection light may hide pixels, but cannot prove a neighbour."""
        layout = load_json(Path(__file__).resolve().parents[1] / "config/layout-300-regression.json")
        index, neighbour, lift = 11, 10, 48
        target = layout["handSlots"][index]
        other = layout["handSlots"][neighbour]

        def frame(selected_index=None):
            image = Image.new("RGB", (1920, 1080), "white")
            for slot_index, slot in ((index, target), (neighbour, other)):
                offset = lift if slot_index == selected_index else 0
                # Sparse asymmetric glyph: a one-pixel wrong lift cannot
                # overlap most of it, unlike a solid rectangle.
                marks = [(18 + (n * 17) % 48, 12 + n * 11) for n in range(8)]
                draw = ImageDraw.Draw(image)
                for x, y in marks:
                    draw.rectangle((int(slot["x"] + x), int(slot["y"] + y - offset),
                                    int(slot["x"] + x + 7), int(slot["y"] + y + 7 - offset)),
                                   fill="black")
                if slot_index == selected_index:
                    # White selection light removes part of the glyph and
                    # defeats raw pixel delta, while leaving >90% identifiable.
                    x, y = marks[0]
                    draw.rectangle((int(slot["x"] + x), int(slot["y"] + y - offset),
                                    int(slot["x"] + x + 7), int(slot["y"] + y + 7 - offset)),
                                   fill="white")
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()

        before, raised = frame(), frame(index)
        slot = layout["handSlots"][index]
        face = {"x": slot["x"] + 10, "y": slot["y"] + 10,
                "width": slot["width"] - 20, "height": slot["height"] - 38}
        # Work at the binary-mask layer used by the fallback: sparse glyph
        # pixels make a wrong one-pixel offset unambiguously distinct.
        baseline = Image.new("L", (int(face["width"]), int(face["height"])))
        for x, y in [(7 + (n * 11) % 55, 7 + n * 9) for n in range(10)]:
            ImageDraw.Draw(baseline).rectangle((x, y, x + 3, y + 3), fill=255)
        after_mask = Image.new("L", (1920, 1080))
        after_mask.paste(baseline, (int(face["x"]), int(face["y"] - lift)))
        result = raised_glyph_overlap_confirmation(baseline, after_mask, face,
                                                    layout["clickPoints"][index])
        self.assertEqual(result["lift"], 48.0)
        self.assertEqual(result["verification"], "dark_glyph_overlap")
        self.assertIsNone(raised_glyph_overlap_confirmation(baseline, baseline, face,
                                                             layout["clickPoints"][index]))
        neighbour_mask = Image.new("L", (1920, 1080))
        neighbour_face = {"x": other["x"] + 10, "y": other["y"] + 10}
        neighbour_mask.paste(baseline, (int(neighbour_face["x"]), int(neighbour_face["y"] - lift)))
        self.assertIsNone(raised_glyph_overlap_confirmation(baseline, neighbour_mask, face,
                                                             layout["clickPoints"][index]))

    def test_raised_tile_optimized_search_matches_original_mask_search(self) -> None:
        layout = load_json(Path(__file__).resolve().parents[1] / "config/layout-300-regression.json")
        for index, lift in ((11, 31), (9, 19), (9, 0)):
            with self.subTest(index=index, lift=lift):
                before, after = self.raised_tile_frames(layout, index, lift)
                slot = layout['handSlots'][index]
                face = {'x': slot['x'] + 10, 'y': slot['y'] + 10,
                        'width': slot['width'] - 20, 'height': slot['height'] - 38}
                baseline = crop_screenshot(before, face)
                delta, old_lift = min((tile_face_structure_delta(baseline, crop_screenshot(
                    after, {**face, 'y': face['y'] - offset})), offset) for offset in range(8, 81))
                result = raised_tile_confirmation_point(before, after, layout, index,
                                                         layout['clickPoints'][index], 1.5)
                if delta > 1.5:
                    self.assertIsNone(result)
                else:
                    self.assertEqual(result['lift'], float(old_lift))
                    self.assertEqual(result['faceStructureDelta'], round(delta, 3))

    def test_raised_tile_confirmation_uses_observed_compact_hand_lift(self) -> None:
        layout = load_json(Path(__file__).resolve().parents[1] / "config/layout-300-regression.json")
        # One open meld uses compact slot 9 (the precise failing geometry).
        before, after = self.raised_tile_frames(layout, 9, 19)
        point = layout["clickPoints"][9]
        confirmation = raised_tile_confirmation_point(before, after, layout, 9, point, 1.5)
        self.assertEqual(confirmation, {"x": 1122.5, "y": 980.0, "lift": 19.0,
                                        "faceStructureDelta": 0.0})

    def test_raised_tile_confirmation_rejects_unmoved_or_other_slot_face(self) -> None:
        layout = load_json(Path(__file__).resolve().parents[1] / "config/layout-300-regression.json")
        # The target's unique glyph did not lift (an adjacent selection must
        # not be accepted as proof for this slot).
        before, after = self.raised_tile_frames(layout, 9, 0)
        self.assertIsNone(raised_tile_confirmation_point(
            before, after, layout, 9, layout["clickPoints"][9], 1.5,
        ))

    def test_startup_clears_tile_hover_before_starting_first_frame_stream(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", max_iterations=-1)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.latest_screencast_frame = b"fresh-frame"
        operator.screencast_session = None
        operator.log = Mock()
        page = Mock()
        sequence = Mock()
        operator.ensure_viewport = Mock()
        operator.start_screencast_gate = Mock()
        sequence.attach_mock(operator.ensure_viewport, "viewport")
        sequence.attach_mock(page.mouse.move, "move")
        sequence.attach_mock(page.wait_for_timeout, "wait")
        sequence.attach_mock(operator.start_screencast_gate, "stream")
        operator.run(page)
        self.assertEqual([call[0] for call in sequence.mock_calls],
                         ["viewport", "move", "wait", "stream"])
        page.mouse.move.assert_called_once_with(960, 777.6)
        page.wait_for_timeout.assert_called_once_with(100)
        page.mouse.click.assert_not_called()

    def test_advisor_startup_does_not_move_users_pointer(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="advisor", max_iterations=-1)
        operator.screencast_session = None
        operator.ensure_viewport = Mock()
        operator.start_screencast_gate = Mock()
        operator.log = Mock()
        page = Mock()
        operator.run(page)
        page.mouse.move.assert_not_called()
        page.wait_for_timeout.assert_not_called()

    def test_all_reaction_prompt_variants_use_the_certified_pass(self) -> None:
        for offered in (["chi", "pass"], ["pon", "pass"], ["kan", "pass"],
                        ["ron", "pass"], ["chi", "pon", "kan", "pass"]):
            with self.subTest(offered=offered):
                operator = PythonAutoOperator.__new__(PythonAutoOperator)
                operator.args = argparse.Namespace(mode="auto", stability_pixel_delta=1.5)
                operator.layout = {
                    "actionButtonRegions": {"pass": {"x": 10, "y": 20, "width": 100, "height": 40}},
                    "actionOperation": {"pass": {
                        "enabled": True, "templateSetFingerprint": "buttons-v1",
                    }},
                }
                operator.log = Mock()
                operator.confirm_action_button = Mock(return_value={"confirmation": "action_button_region_changed"})
                page = Mock()
                page.screenshot.return_value = Image.new("RGB", (100, 40), "black")
                buffer = io.BytesIO()
                page.screenshot.return_value.save(buffer, format="PNG")
                page.screenshot.return_value = buffer.getvalue()
                evaluation = {
                    "status": "reaction_prompt",
                    "recognition": {"safe": True, "tiles": ["1m"] * 13},
                    "availableUiActions": offered,
                    "actionButton": {"action": "pass", "present": True, "confidence": 0.99,
                                     "templateSetFingerprint": "buttons-v1", "center": {"x": 60, "y": 40}},
                }
                receipt = operator.execute_reaction_pass(page, evaluation)
                self.assertEqual(receipt["action"], "pass")
                page.mouse.click.assert_called_once_with(60, 40)

    def test_reaction_prompt_never_clicks_without_auto_and_certificate(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="advisor")
        evaluation = {"recognition": {"safe": True, "tiles": ["1m"] * 13}}
        self.assertFalse(operator.execute_reaction_pass(Mock(), evaluation)["clicked"])

    def test_force_auto_reaction_ignores_confidence_and_certificate(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", stability_pixel_delta=1.5)
        operator.layout = {"actionButtonRegions": {"pass": {"x": 10, "y": 20, "width": 100, "height": 40}}}
        operator.log = Mock()
        operator.confirm_action_button = Mock(return_value={"confirmation": "action_button_region_changed"})
        page = Mock()
        buffer = io.BytesIO()
        Image.new("RGB", (100, 40), "black").save(buffer, format="PNG")
        page.screenshot.return_value = buffer.getvalue()
        evaluation = {
            "recognition": {"safe": False, "tiles": ["1m"] * 13},
            "availableUiActions": ["chi", "pass"],
            "actionButton": {"action": "pass", "present": True, "confidence": 0.2,
                             "center": {"x": 60, "y": 40}},
        }
        receipt = operator.execute_reaction_pass(page, evaluation)
        self.assertEqual(receipt["policy"], "force_auto")
        page.mouse.click.assert_called_once_with(60, 40)

    def test_reaction_pass_stale_evaluation_without_fresh_confirmation_never_clicks(self) -> None:
        """A stale evaluation cannot pass unless its current button check stabilizes."""
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(
            mode="force-auto", stability_pixel_delta=1.5, force_auto_click_budget_ms=2600,
        )
        operator.layout = {"actionButtonRegions": {"pass": {"x": 10, "y": 20, "width": 100, "height": 40}}}
        operator.log = Mock()
        operator.confirm_action_button = Mock()
        page = Mock()
        black = io.BytesIO()
        white = io.BytesIO()
        Image.new("RGB", (100, 40), "black").save(black, format="PNG")
        Image.new("RGB", (100, 40), "white").save(white, format="PNG")
        page.screenshot.side_effect = [black.getvalue(), white.getvalue()]
        evaluation = {
            "recognition": {"safe": False, "tiles": ["1m"] * 13},
            "availableUiActions": ["pass"],
            "actionButton": {"action": "pass", "present": True, "confidence": 1,
                             "center": {"x": 60, "y": 40}},
        }

        with patch("auto_operator.time.monotonic", return_value=12.7):
            with self.assertRaisesRegex(RetryableSafetyAbort, "pass button changed.*reobserve"):
                operator.execute_reaction_pass(page, evaluation, evaluated_captured_at=10.0)
        page.mouse.click.assert_not_called()
        operator.confirm_action_button.assert_not_called()

    def test_reaction_pass_stream_guard_keeps_age_stability_and_fallbacks(self) -> None:
        def frame(offset=0, contextual=False):
            image = Image.new("RGB", (120, 80), "black")
            for x in range(20 + offset, 50 + offset):
                for y in range(25, 45):
                    image.putpixel((x, y), (120, 120, 120) if contextual else (150, 140, 50))
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()

        for case in ("fresh", "changed", "same_timestamp", "stale", "missing_time", "contextual", "missing_call"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                operator = PythonAutoOperator.__new__(PythonAutoOperator)
                operator.args = argparse.Namespace(mode="force-auto", stability_pixel_delta=1.5)
                operator.layout = {"actionButtonRegions": {
                    "pass": {"x": 10, "y": 20, "width": 100, "height": 40}}}
                operator.layout["viewport"] = {"width": 120, "height": 80}
                contextual = case in ("contextual", "missing_call")
                operator.screencast_session = object()
                operator.latest_screencast_frame = frame(20 if case == "changed" else 0, contextual)
                operator.latest_screencast_captured_at = {
                    "same_timestamp": 10.0, "stale": 10.2, "missing_time": None,
                }.get(case, 10.9)
                operator.log = Mock()
                operator.require_action_deadline = Mock()
                operator.require_force_auto_click_budget = Mock()
                operator.confirm_action_button = Mock(return_value={"confirmation": "action_button_region_changed"})
                original = Path(directory) / "prompt.png"
                original.write_bytes(frame(contextual=contextual))
                evaluation = {"reactionFrame": str(original), "actionButton": {
                    "action": "pass", "center": {"x": 60, "y": 40}}}
                page = Mock()
                page.screenshot.return_value = crop_screenshot(frame(), operator.layout["actionButtonRegions"]["pass"])
                with patch("auto_operator.time.monotonic", return_value=11.0), \
                        patch("auto_operator.force_auto_call_buttons", return_value=[] if case == "missing_call" else [{"action": "pon"}]):
                    if case == "changed":
                        with self.assertRaisesRegex(RetryableSafetyAbort, "pass button changed"):
                            operator.execute_reaction_pass(page, evaluation, evaluated_captured_at=10.0)
                        page.mouse.click.assert_not_called()
                    else:
                        operator.execute_reaction_pass(page, evaluation, evaluated_captured_at=10.0)
                        page.mouse.click.assert_called_once_with(60, 40)
                        operator.require_force_auto_click_budget.assert_called_once_with(
                            10.9 if case in ("fresh", "contextual") else 11.0,
                            phase="before_reaction_pass_click", include_action_evidence=False)
                self.assertEqual(page.screenshot.call_count, 0 if case in ("fresh", "changed", "contextual") else 2)

    def test_successful_tsumo_arms_round_terminal_latch(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = {
            "viewport": {"width": 1920, "height": 1080},
            "clickPoints": [],
            "publicTileRegions": {},
        }
        operator.hand_clip = {"x": 0, "y": 0, "width": 10, "height": 10}
        operator.river_clip = {"x": 10, "y": 0, "width": 10, "height": 10}
        operator.screencast_session = Mock()
        frame_buffer = io.BytesIO()
        Image.new("RGB", (1920, 1080), "navy").save(frame_buffer, format="JPEG")
        frame = frame_buffer.getvalue()
        operator.latest_screencast_frame = frame
        operator.screencast_draw_generation = 4
        operator.log = Mock()
        operator.confirm_action_button = Mock(return_value={"confirmation": "action_button_region_changed"})
        button_buffer = io.BytesIO()
        Image.new("RGB", (100, 40), "orange").save(button_buffer, format="PNG")
        page = Mock()
        page.screenshot.return_value = button_buffer.getvalue()
        evaluation = {
            "decision": {"selectedAction": {"action": "tsumo"}},
            "recognition": {"tiles": ["2p", "2p"], "safe": False},
            "actionButton": {
                "action": "tsumo", "x": 1087, "y": 788, "width": 352, "height": 57,
                "center": {"x": 1263, "y": 816.5},
            },
        }

        receipt = operator.execute(
            page, evaluation,
            evaluated_hand=crop_screenshot(frame, operator.hand_clip),
            evaluated_draw_generation=4,
        )

        self.assertTrue(receipt["clicked"])
        self.assertTrue(operator.round_terminal_latched)
        self.assertFalse(operator.round_terminal_result_observed)

    def test_stream_button_guard_uses_distinct_frames_and_rejects_button_changes(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = {
            "viewport": {"width": 1920, "height": 1080},
            "clickPoints": [],
            "publicTileRegions": {},
        }
        operator.hand_clip = {"x": 0, "y": 0, "width": 10, "height": 10}
        operator.river_clip = {"x": 10, "y": 0, "width": 10, "height": 10}
        operator.screencast_session = Mock()
        frame_buffer = io.BytesIO()
        Image.new("RGB", (1920, 1080), "navy").save(frame_buffer, format="JPEG")
        frame = frame_buffer.getvalue()
        operator.latest_screencast_frame = frame
        operator.screencast_draw_generation = 4
        operator.log = Mock()
        operator.confirm_action_button = Mock(return_value={"confirmation": "action_button_region_changed"})
        button_buffer = io.BytesIO()
        Image.new("RGB", (100, 40), "orange").save(button_buffer, format="PNG")
        page = Mock()
        page.screenshot.return_value = button_buffer.getvalue()
        evaluation = {
            "decision": {"selectedAction": {"action": "tsumo"}},
            "recognition": {"tiles": ["2p", "2p"], "safe": False},
            "actionButton": {
                "action": "tsumo", "x": 1087, "y": 788, "width": 352, "height": 57,
                "center": {"x": 1263, "y": 816.5},
            },
        }

        operator.latest_screencast_captured_at = 10.5
        operator.require_force_auto_click_budget = Mock()
        receipt = operator.execute(
            page, evaluation,
            evaluated_hand=crop_screenshot(frame, operator.hand_clip),
            evaluated_full=frame, evaluated_captured_at=10.0,
            evaluated_draw_generation=4,
        )
        self.assertTrue(receipt["clicked"])
        page.screenshot.assert_not_called()
        operator.require_force_auto_click_budget.assert_any_call(
            10.0, phase="before_action_button_click",
        )
        changed = Image.open(io.BytesIO(frame)).convert("RGB")
        changed.paste("orange", (1087, 788, 1439, 845))
        changed_buffer = io.BytesIO()
        changed.save(changed_buffer, format="PNG")
        operator.latest_screencast_frame = changed_buffer.getvalue()
        page.mouse.click.reset_mock()
        with self.assertRaisesRegex(RetryableSafetyAbort, "tsumo button changed"):
            operator.execute(
                page, evaluation,
                evaluated_hand=crop_screenshot(frame, operator.hand_clip),
                evaluated_full=frame, evaluated_captured_at=10.0,
                evaluated_draw_generation=4,
            )
        page.mouse.click.assert_not_called()
        page.screenshot.assert_not_called()
        # A frame too close to the evaluated observation must still sample
        # the button twice, rather than comparing a frame with itself.
        operator.latest_screencast_frame = frame
        operator.latest_screencast_captured_at = 10.05
        operator.execute(
            page, evaluation,
            evaluated_hand=crop_screenshot(frame, operator.hand_clip),
            evaluated_full=frame, evaluated_captured_at=10.0,
            evaluated_draw_generation=4,
        )
        self.assertEqual(page.screenshot.call_count, 2)

    def test_riichi_button_change_retries_without_clicking_or_stopping_table(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = {
            "viewport": {"width": 1920, "height": 1080},
            "clickPoints": [],
            "publicTileRegions": {},
        }
        operator.hand_clip = {"x": 0, "y": 0, "width": 10, "height": 10}
        operator.river_clip = {"x": 10, "y": 0, "width": 10, "height": 10}
        operator.screencast_session = Mock()
        frame_buffer = io.BytesIO()
        Image.new("RGB", (1920, 1080), "navy").save(frame_buffer, format="JPEG")
        frame = frame_buffer.getvalue()
        operator.latest_screencast_frame = frame
        operator.screencast_draw_generation = 4
        operator.log = Mock()
        page = Mock()
        button_buffer = io.BytesIO()
        Image.new("RGB", (100, 40), "orange").save(button_buffer, format="PNG")
        page.screenshot.return_value = button_buffer.getvalue()
        evaluation = {
            "decision": {"selectedAction": {"action": "riichi"}},
            "recognition": {"tiles": ["2p", "2p"], "safe": False},
            "clickIndex": 0,
            "clickPoint": {"x": 100, "y": 100},
            "actionButton": {
                "action": "riichi", "x": 1087, "y": 788, "width": 352, "height": 57,
                "center": {"x": 1263, "y": 816.5},
            },
        }

        with patch("auto_operator.stable_hand_delta", return_value=0.0), \
             patch("auto_operator.mean_pixel_delta", return_value=2.0):
            with self.assertRaisesRegex(RetryableSafetyAbort, "riichi button changed"):
                operator.execute(
                    page, evaluation,
                    evaluated_hand=crop_screenshot(frame, operator.hand_clip),
                    evaluated_draw_generation=4,
                )
        page.mouse.click.assert_not_called()

    def test_tsumo_button_change_retries_without_clicking_or_stopping_table(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = {
            "viewport": {"width": 1920, "height": 1080},
            "clickPoints": [],
            "publicTileRegions": {},
        }
        operator.hand_clip = {"x": 0, "y": 0, "width": 10, "height": 10}
        operator.river_clip = {"x": 10, "y": 0, "width": 10, "height": 10}
        operator.screencast_session = Mock()
        frame_buffer = io.BytesIO()
        Image.new("RGB", (1920, 1080), "navy").save(frame_buffer, format="JPEG")
        frame = frame_buffer.getvalue()
        operator.latest_screencast_frame = frame
        operator.screencast_draw_generation = 4
        operator.log = Mock()
        page = Mock()
        button_buffer = io.BytesIO()
        Image.new("RGB", (100, 40), "orange").save(button_buffer, format="PNG")
        page.screenshot.return_value = button_buffer.getvalue()
        evaluation = {
            "decision": {"selectedAction": {"action": "tsumo"}},
            "recognition": {"tiles": ["2p", "2p"], "safe": False},
            "clickIndex": 0,
            "clickPoint": {"x": 100, "y": 100},
            "actionButton": {
                "action": "tsumo", "x": 1087, "y": 788, "width": 352, "height": 57,
                "center": {"x": 1263, "y": 816.5},
            },
        }

        with patch("auto_operator.stable_hand_delta", return_value=0.0), \
             patch("auto_operator.mean_pixel_delta", return_value=2.0):
            with self.assertRaisesRegex(RetryableSafetyAbort, "tsumo button changed"):
                operator.execute(
                    page, evaluation,
                    evaluated_hand=crop_screenshot(frame, operator.hand_clip),
                    evaluated_draw_generation=4,
                )
        page.mouse.click.assert_not_called()

    def test_pending_discard_requires_one_exact_opponent_river_append(self) -> None:
        previous = {"opponentDiscards": [
            {"seat": "east", "discards": ["1m"]},
            {"seat": "west", "discards": ["2p"]},
        ]}
        current = {"opponentDiscards": [
            {"seat": "east", "discards": ["1m", "5s"]},
            {"seat": "west", "discards": ["2p"]},
        ]}
        self.assertEqual(PythonAutoOperator.infer_pending_discard(previous, current),
                         {"tile": "5s", "fromSeat": "east"})
        current["opponentDiscards"][1]["discards"] = ["2p", "3p", "4p"]
        self.assertIsNone(PythonAutoOperator.infer_pending_discard(previous, current))
        current["opponentDiscards"][1]["discards"] = ["9p"]
        self.assertIsNone(PythonAutoOperator.infer_pending_discard(previous, current))
        current["opponentDiscards"][1]["discards"] = ["2p"]
        current["ownDiscards"] = ["1s"]
        self.assertIsNone(PythonAutoOperator.infer_pending_discard(previous, current))
        del current["ownDiscards"]
        current["opponentDiscards"][1]["discards"].append("3p")
        self.assertIsNone(PythonAutoOperator.infer_pending_discard(previous, current))
        current["opponentDiscards"][0]["discards"] = ["9m", "5s"]
        current["opponentDiscards"][1]["discards"] = ["2p"]
        self.assertIsNone(PythonAutoOperator.infer_pending_discard(previous, current))

    def test_ranked_loop_click_points_cover_bronze_east_navigation_only(self) -> None:
        viewport = {"width": 1920, "height": 1080}
        self.assertEqual(PythonAutoOperator.ranked_loop_click_point("lobby", viewport),
                         {"x": 1390.08, "y": 324.0})
        self.assertEqual(PythonAutoOperator.ranked_loop_click_point("ranked_menu", viewport),
                         {"x": 1390.08, "y": 410.4})
        self.assertEqual(PythonAutoOperator.ranked_loop_click_point("ranked_room", viewport),
                         {"x": 1390.08, "y": 405.0})
        self.assertIsNone(PythonAutoOperator.ranked_loop_click_point("matchmaking", viewport))
        self.assertIsNone(PythonAutoOperator.ranked_loop_click_point("match", viewport))

    def test_current_cherry_lobby_classifies_and_advances_ranked_loop(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frame = project / "artifacts" / "ranked-transition-2.png"
        state, confidence = classify_screen(frame, {})
        self.assertEqual(state, "lobby")
        self.assertEqual(confidence, 1.0)

        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(ranked_loop=True)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.last_ranked_loop_state = None
        operator.last_ranked_loop_click_at = 0.0
        operator.log = Mock()
        page = Mock()

        self.assertTrue(operator.advance_ranked_loop(page, state, confidence))
        page.mouse.click.assert_called_once_with(1390.08, 324.0)
        operator.log.assert_called_once_with(
            "ranked_loop_advanced", state="lobby", confidence=1.0,
            clickPoint={"x": 1390.08, "y": 324.0},
        )

    def test_stale_lobby_screencast_is_rejected_by_current_table_frame(self) -> None:
        """A stale CDP frame must not bypass an already resumed friend table."""
        project = Path(__file__).resolve().parents[1]
        live_table = (project / "test" / "fixtures" / "riichi-stick-red-occluded-20261021.jpg").read_bytes()
        self.assertEqual(classify_screen(live_table, {}), ("match", 1.0))

        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.screen_references = {}
        operator.log = Mock()
        page = Mock()
        page.screenshot.return_value = live_table

        state, confidence, frame, rejected = operator.verify_screencast_non_gameplay_state(
            page, "lobby", 1.0, b"stale-lobby-frame",
        )

        self.assertEqual((state, confidence, frame, rejected), ("match", 1.0, live_table, True))
        page.screenshot.assert_called_once_with(animations="disabled")
        operator.log.assert_called_once_with(
            "screencast_non_gameplay_state_rejected",
            streamedState="lobby", streamedConfidence=1.0,
            currentState="match", currentConfidence=1.0, gameplayClicks=0,
        )

    def test_current_cherry_ranked_menu_is_navigation_not_gameplay(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frame = project / "artifacts" / "ranked-menu-current.png"
        state, confidence = classify_screen(frame, {})
        self.assertEqual((state, confidence), ("ranked_menu", 1.0))

        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(ranked_loop=True)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.last_ranked_loop_state = None
        operator.last_ranked_loop_click_at = 0.0
        operator.log = Mock()
        page = Mock()
        self.assertTrue(operator.advance_ranked_loop(page, state, confidence))
        # The only allowed click is navigation to Bronze Room; no reaction
        # detector is consulted on this classified frame.
        page.mouse.click.assert_called_once_with(1390.08, 410.4)

    def test_current_ranked_reservation_is_matchmaking_and_clicks_nothing(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frame = project / "artifacts" / "ranked-loop-live.png"
        state, confidence = classify_screen(frame, {})
        self.assertEqual((state, confidence), ("matchmaking", 1.0))

        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(ranked_loop=True)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.last_ranked_loop_state = None
        operator.last_ranked_loop_click_at = 0.0
        operator.log = Mock()
        page = Mock()
        self.assertFalse(operator.advance_ranked_loop(page, state, confidence))
        page.mouse.click.assert_not_called()
        operator.log.assert_not_called()

    def test_ranked_result_confirms_once_then_navigation_reaches_reservation(self) -> None:
        project = Path(__file__).resolve().parents[1]
        result = project / "artifacts" / "ranked-current-check.png"
        progress = project / "artifacts" / "ranked-after-confirm.png"
        reward = project / "artifacts" / "ranked-after-progress-confirm.png"
        lobby = project / "artifacts" / "ranked-transition-2.png"
        menu = project / "artifacts" / "ranked-menu-current.png"
        reserved = project / "artifacts" / "ranked-loop-live.png"
        self.assertEqual(classify_screen(result, {}), ("match_result", 1.0))
        self.assertEqual(classify_screen(progress, {}), ("rank_progress", 1.0))
        self.assertEqual(classify_screen(reward, {}), ("post_match_reward", 1.0))
        self.assertEqual(classify_screen(lobby, {}), ("lobby", 1.0))
        self.assertEqual(classify_screen(menu, {}), ("ranked_menu", 1.0))
        self.assertEqual(classify_screen(reserved, {}), ("matchmaking", 1.0))

        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(ranked_loop=True)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.result_screen_advanced = None
        operator.last_ranked_loop_state = None
        operator.last_ranked_loop_click_at = 0.0
        operator.log = Mock()
        page = Mock()
        self.assertTrue(operator.advance_result_screen_once(page, "match_result", 1.0))
        self.assertFalse(operator.advance_result_screen_once(page, "match_result", 1.0))
        self.assertTrue(operator.advance_result_screen_once(page, "rank_progress", 1.0))
        self.assertFalse(operator.advance_result_screen_once(page, "rank_progress", 1.0))
        self.assertTrue(operator.advance_result_screen_once(page, "post_match_reward", 1.0))
        self.assertFalse(operator.advance_result_screen_once(page, "post_match_reward", 1.0))
        operator.result_screen_advanced = None
        self.assertTrue(operator.advance_ranked_loop(page, "lobby", 1.0))
        operator.last_ranked_loop_state = None
        self.assertTrue(operator.advance_ranked_loop(page, "ranked_menu", 1.0))
        self.assertFalse(operator.advance_ranked_loop(page, "matchmaking", 1.0))
        self.assertEqual(page.mouse.click.call_count, 5)

    def test_post_match_reward_uses_yellow_confirmation_exactly_once(self) -> None:
        project = Path(__file__).resolve().parents[1]
        state, confidence = classify_screen(
            project / "artifacts" / "ranked-after-progress-confirm.png", {}
        )
        self.assertEqual((state, confidence), ("post_match_reward", 1.0))
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(ranked_loop=True, advance_screens=False)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.result_screen_advanced = "rank_progress"
        operator.pending_post_call_discard = False
        operator.pending_post_call_started_at = None
        operator.round_terminal_latched = True
        operator.round_terminal_result_observed = True
        operator.log = Mock()
        page = Mock()

        self.assertTrue(operator.handle_early_non_gameplay_screen(page, state, confidence))
        self.assertTrue(operator.handle_early_non_gameplay_screen(page, state, confidence))
        # The yellow confirmation is on the right; the blue replay button is
        # deliberately not selected by the bounded ranked-loop transition.
        page.mouse.click.assert_called_once_with(1747.2, 993.6)

    def test_rank_progress_early_branch_confirms_once_without_gameplay(self) -> None:
        project = Path(__file__).resolve().parents[1]
        state, confidence = classify_screen(project / "artifacts" / "ranked-after-confirm.png", {})
        self.assertEqual((state, confidence), ("rank_progress", 1.0))
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(ranked_loop=True, advance_screens=False)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.result_screen_advanced = "match_result"
        operator.pending_post_call_discard = True
        operator.pending_post_call_started_at = time.monotonic()
        operator.round_terminal_latched = False
        operator.round_terminal_result_observed = False
        operator.log = Mock()
        page = Mock()

        self.assertTrue(operator.handle_early_non_gameplay_screen(page, state, confidence))
        self.assertTrue(operator.handle_early_non_gameplay_screen(page, state, confidence))
        page.mouse.click.assert_called_once_with(1747.2, 993.6)
        self.assertFalse(operator.pending_post_call_discard)

    def test_early_main_loop_result_branch_confirms_once_before_quick_gate(self) -> None:
        project = Path(__file__).resolve().parents[1]
        state, confidence = classify_screen(project / "artifacts" / "ranked-current-check.png", {})
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        # Ranked-loop must advance a static result after restart even when the
        # separate manual --advance-screens option was not supplied.
        operator.args = argparse.Namespace(ranked_loop=True, advance_screens=False)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.result_screen_advanced = False
        operator.last_ranked_loop_state = None
        operator.last_ranked_loop_click_at = 0.0
        operator.pending_post_call_discard = True
        operator.pending_post_call_started_at = time.monotonic()
        operator.round_terminal_latched = False
        operator.round_terminal_result_observed = False
        operator.log = Mock()
        page = Mock()

        self.assertTrue(operator.handle_early_non_gameplay_screen(page, state, confidence))
        self.assertTrue(operator.handle_early_non_gameplay_screen(page, state, confidence))
        page.mouse.click.assert_called_once_with(1747.2, 993.6)
        self.assertFalse(operator.pending_post_call_discard)
        self.assertTrue(operator.round_terminal_result_observed)
        # A lobby-looking result fade is not enough to clear the terminal
        # guard.  Navigation may be clicked, but only a subsequent ranked
        # menu/room observation independently proves re-entry.
        operator.ranked_terminal_transition_pending = True
        self.assertTrue(operator.handle_early_non_gameplay_screen(page, "lobby", 1.0))
        self.assertIsNone(operator.result_screen_advanced)
        self.assertEqual(page.mouse.click.call_count, 2)
        self.assertTrue(operator.ranked_terminal_transition_pending)
        self.assertTrue(operator.handle_early_non_gameplay_screen(page, "ranked_menu", 1.0))
        self.assertFalse(operator.ranked_terminal_transition_pending)

    def test_ranked_result_to_unverified_matchmaking_requests_safe_stop(self) -> None:
        """A result/disconnect transition cannot become an endless reservation poll."""
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(ranked_loop=True, advance_screens=False)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.result_screen_advanced = "match_result"
        operator.ranked_terminal_transition_pending = True
        operator.ranked_terminal_transition_stop_requested = False
        operator.ranked_terminal_matchmaking_seen_at = time.monotonic() - 6
        operator.log = Mock()
        page = Mock()

        self.assertTrue(operator.handle_early_non_gameplay_screen(page, "matchmaking", 1.0))
        self.assertTrue(operator.ranked_terminal_transition_stop_requested)
        page.mouse.click.assert_not_called()
        operator.log.assert_called_once_with(
            "ranked_terminal_transition_stop", state="matchmaking",
            confidence=1.0, gameplayClicks=0,
            reason="result_transition_missing_verified_ranked_navigation",
        )

    def test_native_promotion_opens_and_closes_once_after_verified_match(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(ranked_loop=True)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.ranked_match_finished = True
        operator.ranked_terminal_transition_pending = True
        operator.pending_match_replays = []
        operator.result_screen_advanced = "rank_progress"
        operator.ranked_terminal_matchmaking_seen_at = time.monotonic() - 60
        operator.log = Mock()
        page = Mock()
        root = FRAME_FIXTURES / "rank-promotion-20261023"
        for filename, state, point in (("scroll.png", "rank_promotion", (1400, 550)),
                                       ("certificate.png", "rank_certificate", (1525, 150))):
            frame = (root / filename).read_bytes()
            self.assertEqual(classify_screen(frame, {}), (state, 1.0))
            page.screenshot.return_value = frame
            for _ in range(2):
                self.assertTrue(operator.handle_early_non_gameplay_screen(page, state, 1.0, frame))
            self.assertEqual(page.mouse.click.call_args, call(*point))
        self.assertEqual(page.mouse.click.call_count, 2)
        # A reveal/loading frame may clear the ordinary result-stage latch;
        # it must not make the same promotion control clickable twice.
        operator.result_screen_advanced = None
        page.screenshot.return_value = (root / "scroll.png").read_bytes()
        operator.handle_early_non_gameplay_screen(page, "rank_promotion", 1.0,
                                                 page.screenshot.return_value)
        self.assertEqual(page.mouse.click.call_count, 2)
        self.assertTrue(operator.ranked_terminal_transition_pending)
        self.assertIsNone(operator.ranked_terminal_matchmaking_seen_at)
        # Promotion handling must not manufacture verified ranked re-entry.
        with patch("auto_operator.time.monotonic", return_value=100):
            self.assertFalse(operator.ranked_terminal_transition_requires_stop("matchmaking"))
        with patch("auto_operator.time.monotonic", return_value=106):
            self.assertTrue(operator.ranked_terminal_transition_requires_stop("matchmaking"))

    def test_promotion_controls_refuse_unfinished_or_stale_evidence(self) -> None:
        frame = (FRAME_FIXTURES / "rank-promotion-20261023/scroll.png").read_bytes()
        for ranked, finished, pending, replays, fresh in (
            (False, True, True, [], frame),
            (True, False, True, [], frame),
            (True, True, False, [], frame),
            (True, True, True, [Path("unattached.json")], frame),
            (True, True, True, [], (FRAME_FIXTURES / "ranked-reservation-20261020.png").read_bytes()),
        ):
            with self.subTest(ranked=ranked, finished=finished, pending=pending, replays=replays):
                operator = PythonAutoOperator.__new__(PythonAutoOperator)
                operator.args = argparse.Namespace(ranked_loop=ranked)
                operator.ranked_match_finished = finished
                operator.ranked_terminal_transition_pending = pending
                operator.pending_match_replays = replays
                operator.result_screen_advanced = None
                operator.log = Mock()
                page = Mock()
                page.screenshot.return_value = fresh
                self.assertTrue(operator.handle_early_non_gameplay_screen(page, "rank_promotion", 1.0, frame))
                page.mouse.click.assert_not_called()

    def test_ranked_result_transition_allows_brief_matchmaking_false_positive(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(ranked_loop=True)
        operator.ranked_terminal_transition_pending = True
        self.assertFalse(operator.ranked_terminal_transition_requires_stop("matchmaking"))
        self.assertIsNotNone(operator.ranked_terminal_matchmaking_seen_at)
        self.assertFalse(operator.ranked_terminal_transition_requires_stop("match_result"))
        self.assertIsNone(operator.ranked_terminal_matchmaking_seen_at)

    def test_real_reward_branch_resets_matchmaking_guard_without_verifying_reentry(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frame = (project / "test/fixtures/ranked-progress-before-lobby-loading-20261020.png").read_bytes()
        state, confidence = classify_screen(frame, {})
        self.assertEqual(state, "post_match_reward")
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(ranked_loop=True, advance_screens=False)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.result_screen_advanced = "match_result"
        operator.ranked_terminal_transition_pending = True
        operator.ranked_terminal_transition_stop_requested = False
        operator.ranked_terminal_matchmaking_seen_at = 38.231
        operator.log = Mock()
        page = Mock()
        # Actual first-run times: reward at40.924 interrupted the interval
        # that otherwise caused a premature stop at43.431.
        with patch("auto_operator.time.monotonic", return_value=40.924):
            self.assertTrue(operator.handle_early_non_gameplay_screen(page, state, confidence))
        self.assertIsNone(operator.ranked_terminal_matchmaking_seen_at)
        self.assertTrue(operator.ranked_terminal_transition_pending)
        with patch("auto_operator.time.monotonic", return_value=43.431):
            self.assertFalse(operator.ranked_terminal_transition_requires_stop("matchmaking"))
        with patch("auto_operator.time.monotonic", return_value=48.432):
            self.assertTrue(operator.ranked_terminal_transition_requires_stop("matchmaking"))
        page.mouse.click.assert_called_once_with(1747.2, 993.6)

    def test_real_lobby_loading_bypasses_clicks_and_retains_ranked_guard(self) -> None:
        project = Path(__file__).resolve().parents[1]
        state, confidence = classify_screen(project / "test/fixtures/lobby-loading-after-ranked-result-20261020.png", {})
        self.assertEqual(state, "loading")
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(ranked_loop=True)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.ranked_terminal_transition_pending = True
        operator.ranked_terminal_matchmaking_seen_at = time.monotonic() - 60
        operator.ranked_terminal_transition_stop_requested = False
        operator.log = Mock()
        page = Mock()
        self.assertTrue(operator.handle_early_non_gameplay_screen(page, state, confidence))
        self.assertIsNone(operator.ranked_terminal_matchmaking_seen_at)
        self.assertTrue(operator.ranked_terminal_transition_pending)
        self.assertFalse(operator.ranked_terminal_transition_stop_requested)
        page.mouse.click.assert_not_called()

    def test_ranked_transition_stop_records_actual_frame(self) -> None:
        frame = (Path(__file__).resolve().parents[1] / "test/fixtures/lobby-loading-after-ranked-result-20261020.png").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.frames = Path(directory)
            operator.log = Mock()
            operator.log_ranked_terminal_transition_stop("matchmaking", 1.0, frame)
            evidence = operator.log.call_args.kwargs
            self.assertEqual(Path(evidence["screenshot"]).read_bytes(), frame)
            self.assertEqual(evidence["gameplayClicks"], 0)

    def test_ranked_round_result_does_not_arm_terminal_stop_in_later_hand(self) -> None:
        """A normal hand result must not poison the following in-match screen."""
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(ranked_loop=True, advance_screens=False)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.result_screen_advanced = None
        # A stale value must also be cleared by the independently recognized
        # hand summary, rather than leaking into the hand that follows it.
        operator.ranked_terminal_transition_pending = True
        operator.ranked_terminal_transition_stop_requested = False
        operator.last_ranked_loop_state = None
        operator.last_ranked_loop_click_at = 0.0
        operator.log = Mock()
        page = Mock()

        self.assertTrue(operator.handle_early_non_gameplay_screen(page, "round_result", 1.0))
        self.assertFalse(operator.ranked_terminal_transition_pending)

        # Regression: East 1's result formerly armed this guard, so an
        # in-progress East 2 frame classified as matchmaking stopped the run.
        self.assertTrue(operator.handle_early_non_gameplay_screen(page, "matchmaking", 1.0))
        self.assertFalse(operator.ranked_terminal_transition_stop_requested)
        self.assertFalse(any(
            call.args and call.args[0] == "ranked_terminal_transition_stop"
            for call in operator.log.call_args_list
        ))

    def test_ranked_matchmaking_without_prior_result_remains_a_valid_reservation(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(ranked_loop=True, advance_screens=False)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.result_screen_advanced = None
        operator.ranked_terminal_transition_pending = False
        operator.ranked_terminal_transition_stop_requested = False
        operator.last_ranked_loop_state = None
        operator.last_ranked_loop_click_at = 0.0
        operator.log = Mock()
        page = Mock()

        self.assertTrue(operator.handle_early_non_gameplay_screen(page, "matchmaking", 1.0))
        self.assertFalse(operator.ranked_terminal_transition_stop_requested)
        page.mouse.click.assert_not_called()
        operator.log.assert_called_once_with(
            "screen_state_bypassed", state="matchmaking", confidence=1.0, gameplayClicks=0,
        )

    def test_compact_hand_requires_a_previously_observed_call(self) -> None:
        self.assertTrue(PythonAutoOperator.compact_hand_is_proven(0, False))
        self.assertTrue(PythonAutoOperator.compact_hand_is_proven(1, True))
        self.assertTrue(PythonAutoOperator.compact_hand_is_proven(4, True))
        self.assertFalse(PythonAutoOperator.compact_hand_is_proven(1, False))
        self.assertFalse(PythonAutoOperator.compact_hand_is_proven(3, False))

    def test_session_conflict_is_not_ranked_menu_and_stops_without_click(self) -> None:
        frame = Path(__file__).resolve().parents[1] / "artifacts" / "live" / "session-conflict.png"
        self.assertEqual(classify_screen(frame, {}), ("session_conflict", 1.0))
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.log = Mock()
        page = Mock()
        with self.assertRaisesRegex(RuntimeError, "session_conflict dialog blocks"):
            operator.handle_early_non_gameplay_screen(page, "session_conflict", 1.0)
        page.mouse.click.assert_not_called()

    def test_connection_error_stops_without_click(self) -> None:
        frame = Path(__file__).resolve().parents[1] / "artifacts" / "live" / "connection-error.png"
        self.assertEqual(classify_screen(frame, {}), ("connection_error", 1.0))
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.log = Mock()
        page = Mock()
        with self.assertRaisesRegex(RuntimeError, "connection_error dialog blocks"):
            operator.handle_early_non_gameplay_screen(page, "connection_error", 1.0)
        page.mouse.click.assert_not_called()

    def test_live_300_self_draw_is_not_a_ranked_navigation_screen(self) -> None:
        frame = Path(__file__).resolve().parents[1] / "artifacts" / "live" / "closed-self-draw-20260928.png"
        state, _ = classify_screen(frame, {})
        self.assertNotIn(state, {"ranked_menu", "ranked_room", "lobby", "matchmaking"})

    def test_saved_screens_are_classified_and_unknown_fails_closed(self) -> None:
        expected_files = {
            "login": "result-step-1.png",
            "account_modal": "login-step-1.png",
            "lobby": "lobby-ready.png",
            "ranked_menu": "ranked-menu.png",
            "ranked_room": "ranked-copper.png",
            "matchmaking": "ranked-matchmaking.png",
            "match": "login-step-3.png",
            "away": "away-dialog.png",
            "round_result": "round-result.png",
            "match_result": "match-result.png",
            "exit_confirm": "exit-dialog.png",
        }
        with tempfile.TemporaryDirectory() as directory:
            reference_dir = Path(directory)
            for index, filename in enumerate(expected_files.values(), start=1):
                Image.new("RGB", (64, 36), (index * 17 % 255, index * 31 % 255, index * 47 % 255)).save(reference_dir / filename)
            references = load_references(reference_dir)
            for expected, filename in expected_files.items():
                self.assertEqual(classify_screen(reference_dir / filename, references), (expected, 1))
            blank = io.BytesIO()
            Image.new("RGB", (1920, 1080), "white").save(blank, format="PNG")
            self.assertEqual(classify_screen(blank.getvalue(), references), ("unknown", 0.0))

    def test_round_result_uses_confirm_button_geometry_before_whole_frame_reference(self) -> None:
        image = Image.new("RGB", (1920, 1080), (25, 55, 85))
        draw = ImageDraw.Draw(image)
        draw.rectangle((1650, 950, 1849, 1045), fill=(35, 40, 45))
        draw.rectangle((1650, 950, 1749, 1045), fill=(55, 70, 115))
        draw.rectangle((1680, 975, 1780, 1005), fill=(190, 165, 100))
        output = io.BytesIO()
        image.save(output, format="PNG")

        self.assertEqual(classify_screen(output.getvalue(), {}), ("round_result", 1.0))

    def test_away_dialog_native_thresholds_match_scalar_boundary_cases(self) -> None:
        viewport = {"width": 1920, "height": 1080}
        button, popup = away_resume_geometry(viewport)
        # Each strict RGB boundary and the existing gold/dark proportions
        # must retain the scalar detector's result.
        from auto_operator import fraction_matching
        for color in [(181, 111, 129), (180, 111, 129), (181, 110, 129),
                      (181, 111, 130), (69, 89, 119), (70, 90, 120)]:
            for coverage in [0.64, 0.65, 0.66, 1.0]:
                frame = Image.new("RGB", (1920, 1080), (20, 40, 80))
                draw = ImageDraw.Draw(frame)
                draw.rectangle((button["x"], button["y"],
                                button["x"] + int(button["width"] * coverage) - 1,
                                button["y"] + button["height"] - 1), fill=color)
                def region(clip):
                    return frame.crop((clip["x"], clip["y"], clip["x"] + clip["width"],
                                       clip["y"] + clip["height"]))
                expected = (fraction_matching(region(button), lambda r,g,b: r>180 and g>110 and b<130) >= .65
                            and fraction_matching(region(popup), lambda r,g,b: r<70 and g<90 and b<120) >= .75)
                encoded = io.BytesIO()
                frame.save(encoded, format="PNG")
                with self.subTest(color=color, coverage=coverage):
                    self.assertEqual(is_away_resume_dialog(encoded.getvalue(), viewport), expected)

    def test_resident_request_preserves_capture_age_before_file_write(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(board_metadata=False)
        operator.recognition_request_id = 0
        operator.recognition_server = Mock()
        operator.recognition_server.poll.return_value = None
        operator.recognition_server.stdout.readline.return_value = '{"id":1,"result":{}}'
        operator.action_deadline_remaining_ms = Mock(return_value=300000)
        with patch("auto_operator.time.time", return_value=1000), patch(
            "auto_operator.time.monotonic", return_value=20,
        ):
            operator.recognize_resident(Path("freshly-written.jpg"),
                                        evaluate_force_auto=True, captured_at=18.5)
        request = json.loads(operator.recognition_server.stdin.write.call_args.args[0])
        self.assertEqual(request["frameCapturedAtMs"], 998500)

    def test_force_auto_parallel_recognition_binds_staged_hand_to_metadata_frame(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        screenshot = Path("same-frame.png")
        observation = {"capturedAt": "2026-10-16T00:00:00+00:00"}
        state = {"remainingTiles": 42}
        operator.frame_metadata_state = Mock(return_value=(state, observation, None))
        operator.recognize_resident = Mock(side_effect=[
            {"recognitionId": "same-frame-token"}, {"status": "decision"},
        ])

        result = operator.recognize_force_auto_parallel(
            screenshot, dynamic_layout=True, open_melds=1,
            public_observation=None, force_auto_action_buttons=[{"x": 1}], captured_at=12.5,
        )

        self.assertEqual(result["status"], "decision")
        self.assertEqual(
            set(result["operatorTiming"]),
            {
                "parallelHandRecognitionMs",
                "parallelBoardMetadataMs",
                "forceAutoDecisionAfterParallelMs",
                "forceAutoRecognitionAndDecisionMs",
            },
        )
        self.assertTrue(all(value >= 0 for value in result["operatorTiming"].values()))
        operator.frame_metadata_state.assert_called_once_with(
            screenshot, None, refresh_public_cache=True,
        )
        stage, evaluate = operator.recognize_resident.call_args_list
        self.assertTrue(stage.kwargs["stage_force_auto_recognition"])
        self.assertFalse(stage.kwargs.get("evaluate_force_auto", False))
        self.assertEqual(evaluate.kwargs["force_auto_recognition_id"], "same-frame-token")
        self.assertEqual(evaluate.kwargs["captured_at"], 12.5)
        self.assertEqual(evaluate.kwargs["frame_public_state"], state)
        self.assertEqual(evaluate.kwargs["public_observation"], observation)

    def test_reconciliation_staging_requires_confirmed_public_receipt(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(board_metadata=True)
        operator.force_auto_has_recognition_window = Mock(return_value=True)
        operator.cached_board_metadata = Mock(return_value={"round": "east_1"})
        operator.dynamic_layout_required = True
        operator.cached_open_melds = 1
        operator.recognize_resident = Mock(return_value={"recognitionId": "token"})
        operator.poll_public_recognition = Mock()
        operator.reconcile_own_discard = Mock()
        operator.own_discard_reconciliation_pending = Mock(side_effect=[True, False])
        frame = Path("same-frame.jpg")

        self.assertIsNone(operator.stage_hand_during_discard_reconciliation(frame, 10.0))
        self.assertEqual(operator.stage_hand_during_discard_reconciliation(frame, 10.0),
                         {"recognitionId": "token"})
        self.assertEqual(operator.poll_public_recognition.call_count, 2)
        self.assertEqual(operator.reconcile_own_discard.call_count, 2)
        operator.recognize_resident.assert_called_with(
            frame, dynamic_layout=True, open_melds=1, stage_force_auto_recognition=True,
        )

    def test_reconciliation_staged_hand_uses_fresh_public_state(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        frame = Path("same-frame.jpg")
        state = {"round": "east_1"}
        observation = {"ownDiscards": ["6s", "N", "6p"]}
        operator.frame_metadata_state = Mock(return_value=(state, observation, None))
        operator.recognize_resident = Mock(return_value={"status": "decision"})
        result = operator.recognize_force_auto_parallel(
            frame, dynamic_layout=True, open_melds=1, public_observation=observation,
            force_auto_action_buttons=[], captured_at=10.0,
            staged_recognition={"recognitionId": "same-frame-token"},
        )
        self.assertEqual(result["status"], "decision")
        operator.recognize_resident.assert_called_once()
        request = operator.recognize_resident.call_args
        self.assertEqual(request.args[0], frame)
        self.assertEqual(request.kwargs["force_auto_recognition_id"], "same-frame-token")
        self.assertEqual(request.kwargs["public_observation"], observation)
        self.assertEqual(request.kwargs["frame_public_state"], state)

    def test_metadata_update_abort_reobserves_without_serial_layout_retry(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(board_metadata=True)
        operator.armed = False
        operator.last_processed_hand = "old-hand"
        operator.log = Mock()
        operator.frame_metadata_state = Mock(side_effect=RetryableSafetyAbort("board metadata refresh in progress"))
        operator.recognize_resident = Mock(return_value={"recognitionId": "staged-token"})
        kwargs = dict(dynamic_layout=False, open_melds=None, public_observation=None,
                      force_auto_action_buttons=[], captured_at=12.5)

        result = operator.recognize_force_auto_or_defer(Path("same-frame.jpg"), **kwargs)

        self.assertIsNone(result)
        self.assertTrue(operator.armed)
        self.assertIsNone(operator.last_processed_hand)
        # The real parallel path stages the hand but must never evaluate it
        # or reinterpret the metadata abort as a layout recovery request.
        operator.recognize_resident.assert_called_once_with(
            Path("same-frame.jpg"), dynamic_layout=False, open_melds=None,
            stage_force_auto_recognition=True,
        )
        operator.log.assert_called_once_with(
            "recognition_deferred", screenshot="same-frame.jpg",
            error="board metadata refresh in progress", reason="retryable_safety_abort",
        )
        # A later fresh frame can proceed with the same operator. Its state
        # is rebound by the parallel evaluator, not reused from the abort.
        operator.frame_metadata_state = Mock(return_value=({"remainingTiles": 11}, None, None))
        operator.recognize_resident.reset_mock(side_effect=True)
        operator.recognize_resident.side_effect = [{"recognitionId": "fresh-token"}, {"status": "decision"}]
        fresh = operator.recognize_force_auto_or_defer(Path("fresh-frame.jpg"), **kwargs)
        self.assertEqual(fresh["status"], "decision")
        self.assertEqual(operator.recognize_resident.call_args.kwargs["force_auto_recognition_id"], "fresh-token")

    def test_non_safety_runtime_error_still_reaches_layout_recovery_handler(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(board_metadata=True)
        operator.recognize_force_auto_parallel = Mock(side_effect=RuntimeError("unresolved hand geometry"))
        with self.assertRaisesRegex(RuntimeError, "unresolved hand geometry"):
            operator.recognize_force_auto_or_defer(Path("bad-layout.jpg"))


if __name__ == "__main__":
    unittest.main()
