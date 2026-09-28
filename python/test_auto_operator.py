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
from unittest.mock import Mock, patch

from auto_operator import PythonAutoOperator, RetryableSafetyAbort, action_deadline_timing, away_resume_geometry, closed_concealed_row_visible, crop_screenshot, discard_point_in_hand_geometry, force_auto_call_buttons, force_auto_chi_choice_points, force_auto_reaction_win_button, force_auto_self_action_buttons, geometric_open_meld_count, is_away_resume_dialog, is_contextual_reaction_pass, is_draw_slot_occupied, is_force_auto_pass_prompt, load_json, load_secret_environment, local_discard_allowed, mean_pixel_delta, merge_public_observations, open_hand_draw_slot, own_meld_surface_visible, post_call_transition, selected_tile_comparison_region, send_discard_click, should_guard_tenpai_reaction, should_process_reaction_prompt, stable_hand_comparison_region, stable_hand_delta
from screen_state import classify_screen, load_references
from auto_operator import geometric_reaction_open_meld_count
from auto_operator import configure_evaluator_click_budget


class EvaluatorClickBudgetTest(unittest.TestCase):
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
                operator.args = argparse.Namespace(confirmation_timeout=0.02, action_pixel_delta=3)
                page = Mock()
                page.screenshot.side_effect = lambda **kwargs: unchanged_button if "clip" in kwargs else current
                if accepted:
                    receipt = operator.confirm_action_button(page, "pass", unchanged_button, screen_before=prior)
                    self.assertEqual(receipt["confirmation"], "reaction_to_self_draw")
                    self.assertEqual(receipt["buttonPixelDelta"], 0)
                else:
                    with self.assertRaisesRegex(RuntimeError, "not confirmed"):
                        operator.confirm_action_button(page, "pass", unchanged_button, screen_before=prior)

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


class RecordingMouse:
    def __init__(self) -> None:
        self.calls = []

    def click(self, x, y, **kwargs) -> None:
        self.calls.append((x, y, kwargs))

    def move(self, x, y) -> None:
        self.calls.append(("move", x, y))


class ActionDeadlineTest(unittest.TestCase):
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
            with patch("auto_operator.stable_hand_delta", return_value=3.0):
                if same_generation and verified:
                    self.assertTrue(operator.execute(page, evaluation, crop_screenshot(before, operator.hand_clip),
                                                    before, 5)["clicked"])
                    page.mouse.click.assert_called_once()
                else:
                    with self.assertRaises(RetryableSafetyAbort):
                        operator.execute(page, evaluation, crop_screenshot(before, operator.hand_clip), before, 5)
                    page.mouse.click.assert_not_called()
            if not same_generation:
                operator.verify_closed_hand_identity.assert_not_called()

    def test_closed_hand_identity_requires_safe_ordered_red_aware_consensus(self) -> None:
        expected = ["3m", "3m", "0m", "7m", "3p", "4p", "5p", "6p", "8p", "8p", "2s", "3s", "4s", "6p"]
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(evaluation_timeout=20)
            operator.frames = Path(directory)
            operator.root = Path.cwd()
            operator.layout_path = Path("layout.json")
            operator.templates = Path("templates")
            operator.evaluator_env = {}
            operator.screencast_draw_generation = 5
            operator.screencast_draw_occupied = True
            operator.cached_open_melds = 0
            operator.action_deadline_remaining_ms = Mock(return_value=300000)
            operator.log = Mock()
            for tiles, safe, accepted in [(expected, True, True), (expected, False, False),
                    (["5m" if t == "0m" else t for t in expected], True, False),
                    ([expected[3], *expected[1:3], expected[0], *expected[4:]], True, False),
                    (expected[:-1], True, False)]:
                with patch("auto_operator.subprocess.run", return_value=argparse.Namespace(
                        returncode=0, stdout=json.dumps({"safe": safe, "tiles": tiles}))) as run:
                    self.assertEqual(operator.verify_closed_hand_identity(Mock(), expected, b"frame", 5), accepted)
                    self.assertIn("--backend=hybrid", run.call_args.args[0])
                    detail = operator.log.call_args.kwargs
                    self.assertEqual(detail["observedCount"], len(tiles))
                    self.assertEqual(detail["recognitionSafe"], safe)
                    if tiles == expected:
                        self.assertEqual(detail["mismatches"], [])
                    else:
                        self.assertTrue(detail["mismatches"])
            seven_pin_hand = [*expected[:8], "7p", *expected[9:]]
            misread_hand = [*seven_pin_hand[:8], "6p", *seven_pin_hand[9:]]
            with patch("auto_operator.subprocess.run", return_value=argparse.Namespace(
                    returncode=0, stdout=json.dumps({"safe": True, "tiles": misread_hand, "confidence": 0.699727}))):
                self.assertFalse(operator.verify_closed_hand_identity(Mock(), seven_pin_hand, b"frame", 5))
                self.assertEqual(operator.log.call_args.kwargs["mismatches"],
                                 [{"index": 8, "expected": "7p", "observed": "6p"}])
            page = Mock()
            page.wait_for_timeout.side_effect = lambda _: setattr(operator, "screencast_draw_generation", 6)
            with patch("auto_operator.subprocess.run", return_value=argparse.Namespace(
                    returncode=0, stdout=json.dumps({"safe": True, "tiles": expected}))):
                self.assertFalse(operator.verify_closed_hand_identity(page, expected, b"frame", 5))
            with patch("auto_operator.subprocess.run") as run:
                self.assertFalse(operator.verify_closed_hand_identity(Mock(), expected, b"frame", 5))
                run.assert_not_called()
            operator.screencast_draw_generation = 5
            operator.latest_screencast_frame = b"frame"
            operator.layout = {"viewport": {"width": 1920, "height": 1080}}
            with patch("auto_operator.subprocess.run", return_value=argparse.Namespace(
                    returncode=0, stdout=json.dumps({"safe": True, "tiles": expected}))), \
                    patch("auto_operator.is_away_resume_dialog", return_value=True):
                self.assertFalse(operator.verify_closed_hand_identity(Mock(), expected, b"frame", 5))

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
        operator.screencast_sequence = 4
        operator.screencast_draw_occupied = True
        operator.screencast_draw_generation = 2
        operator.rejected_screencast_size = None
        operator.log = Mock()
        resized = io.BytesIO()
        Image.new("RGB", (1058, 1080), "white").save(resized, format="JPEG")

        self.assertFalse(operator.accept_screencast_frame(resized.getvalue()))

        self.assertIsNone(operator.latest_screencast_frame)
        self.assertIsNone(operator.screencast_draw_occupied)
        self.assertEqual(operator.screencast_draw_generation, 2)
        self.assertEqual(operator.screencast_sequence, 5)
        operator.log.assert_called_once_with(
            "screencast_frame_rejected", expected=[1920, 1080], actual=[1058, 1080],
        )

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

    def test_open_hand_draw_slot_shifts_three_tile_pitches_per_meld(self) -> None:
        layout = {
            "viewport": {"width": 1920, "height": 1080},
            "handSlots": [
                {"x": 223, "y": 926, "width": 92, "height": 146},
                {"x": 318, "y": 926, "width": 92, "height": 146},
                {"x": 413, "y": 926, "width": 92, "height": 146},
            ],
            "drawSlot": {"x": 1486, "y": 926, "width": 92, "height": 146},
        }

        self.assertEqual(open_hand_draw_slot(layout, 1), {
            "x": 1201.0, "y": 926.0, "width": 92.0, "height": 146.0,
        })
        self.assertEqual(open_hand_draw_slot(layout, 2), {
            "x": 916.0, "y": 926.0, "width": 92.0, "height": 146.0,
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
            operator.force_auto_reaction_fallback = Mock(return_value=None)
            operator.log = Mock()
            page = Mock()
            page.url = "https://mahjongsoul.game.yo-star.com/"

            with patch("auto_operator.classify_screen", return_value=("match", 1.0)):
                operator.run(page)

            operator.recognize_resident.assert_called_once()
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
            state, observed, _ = operator.frame_metadata_state(Path("frame.png"), observation)
        self.assertTrue(state["opponents"][0]["riichi"])
        self.assertEqual(state["opponents"][0]["seat"], "north")
        self.assertTrue(observed["opponentDiscards"][0]["riichiDeclared"])
        self.assertEqual(operator.public_state["opponents"], [])
        self.assertFalse(observation["opponentDiscards"][0]["riichiDeclared"])

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
            _, observed, _ = operator.frame_metadata_state(Path("frame.png"), refresh_public_cache=True)
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
            _, observed, _ = operator.frame_metadata_state(Path("frame.png"), observation)
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
        page.mouse.click.assert_called_once_with(1247, 999, click_count=2, delay=80)

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
        page.mouse.click.assert_called_once_with(1217.5, 996.5, click_count=2, delay=80)

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
        page.mouse.click.assert_called_once_with(268.5, 999.5, click_count=2, delay=80)

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
        page.mouse.click.assert_called_once_with(743, 996.5, click_count=2, delay=80)

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
        operator.pending_post_call_discard = True
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
        page.mouse.click.assert_called_once_with(363.5, 996.5, click_count=2, delay=80)

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
        page.mouse.click.assert_called_once_with(1247, 999, click_count=2, delay=80)

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

    def test_local_discard_requires_explicit_flag_and_safe_discard(self) -> None:
        evaluation = {"decision": {"recommendedAction": "discard", "confidence": 0.55, "safety": {"allowed": True}}}
        self.assertTrue(local_discard_allowed(argparse.Namespace(allow_local_discard=True, mode="advisor"), evaluation))
        self.assertFalse(local_discard_allowed(argparse.Namespace(allow_local_discard=False, mode="advisor"), evaluation))
        evaluation["decision"]["safety"]["allowed"] = False
        self.assertFalse(local_discard_allowed(argparse.Namespace(allow_local_discard=True, mode="advisor"), evaluation))

    def test_discard_selects_and_confirms_the_same_guarded_coordinate(self) -> None:
        mouse = RecordingMouse()
        send_discard_click(mouse, {"x": 933, "y": 996.5}, {"width": 1920, "height": 1080})
        self.assertEqual(mouse.calls, [
            (933, 996.5, {"click_count": 2, "delay": 80}),
            ("move", 960, 777.6),
        ])

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
        # Once the resulting lobby is visible, the result latch clears and
        # ranked navigation resumes rather than issuing a gameplay action.
        self.assertTrue(operator.handle_early_non_gameplay_screen(page, "lobby", 1.0))
        self.assertIsNone(operator.result_screen_advanced)
        self.assertEqual(page.mouse.click.call_count, 2)

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


if __name__ == "__main__":
    unittest.main()
