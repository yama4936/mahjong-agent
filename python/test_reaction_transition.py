"""A new live ron must not inherit an abandoned discard's action clock."""
import argparse
import io
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from auto_operator import PythonAutoOperator, RetryableSafetyAbort, load_json
from screen_state import load_references
from synchronous_capture import CaptureReceipt


class ReactionTransitionTest(unittest.TestCase):
    def setUp(self):
        fixed_time = patch("auto_operator.time.monotonic", return_value=100)
        fixed_time.start()
        self.addCleanup(fixed_time.stop)

    def make_operator(self):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", force_auto_click_budget_ms=2600,
                                           action_deadline_ms=300000, confirmation_timeout=3)
        operator.layout = {
            "viewport": {"width": 1600, "height": 900},
            "actionButtonRegions": {"pass": {"x": 1170, "y": 650, "width": 275, "height": 105}},
            "drawSlot": {"x": 1450, "y": 780, "width": 80, "height": 100},
        }
        operator.cached_open_melds = 0
        operator.screen_references = {}
        operator.pending_post_call_discard = False
        operator.log = Mock()
        def capture(page, _purpose):
            started = time.monotonic()
            png = page.screenshot(animations="disabled")
            with Image.open(io.BytesIO(png)) as image:
                width, height = image.size
            return CaptureReceipt(png, started, started, time.monotonic(), width, height, "mock_png")
        operator.capture_full_action_frame = Mock(side_effect=capture)
        operator.mark_action_evidence("discard", observed_at=96.329)
        return operator

    def prompt(self, *, draw=False, win=True):
        image = Image.new("RGB", (1600, 900), (25, 55, 85))
        paint = ImageDraw.Draw(image)
        if win:
            paint.rectangle((850, 650, 1050, 743), fill=(190, 90, 35))
        paint.rectangle((1170, 650, 1445, 755), fill=(35, 40, 45))
        paint.rectangle((1210, 675, 1240, 690), fill=(180, 150, 70))
        paint.rectangle((1260, 675, 1320, 690), fill=(150, 145, 90))
        if draw:
            paint.rectangle((1450, 780, 1530, 880), fill=(240, 235, 210))
        result = io.BytesIO()
        image.save(result, format="PNG")
        return result.getvalue()

    def test_verified_ron_gets_first_capture_clock_and_can_click(self):
        operator = self.make_operator()
        prompt = self.prompt()
        page = Mock()
        page.screenshot.side_effect = [prompt, prompt, self.prompt(win=False)]
        operator.start_self_win_capture = Mock()
        with patch("auto_operator.classify_screen", return_value=("match", 1)), \
             patch("auto_operator.time.monotonic", return_value=100):
            operator.observe_discard_to_win_trigger(99.6)
            result = operator.execute_force_auto_reaction_win(
                page, prompt, {"center": {"x": 950, "y": 696.5}},
                # First receipt contributes the 400ms already spent before
                # synchronous verification, without proving image freshness.
                evaluated_captured_at=99.95,
            )
        self.assertTrue(result["clicked"])
        self.assertEqual(operator.action_evidence_kind, "win")
        self.assertEqual(operator.action_evidence_started_at, 99.6)
        page.mouse.click.assert_called_once_with(950, 696.5)

    def test_two_slow_captures_cannot_extend_budget(self):
        operator = self.make_operator()
        now = [100.0]
        page = Mock()

        def slow_capture(**kwargs):
            now[0] += 1.4
            return self.prompt()

        page.screenshot.side_effect = slow_capture
        with patch("auto_operator.classify_screen", return_value=("match", 1)), \
             patch("auto_operator.time.monotonic", side_effect=lambda: now[0]):
            for _ in range(2):
                with self.assertRaisesRegex(RetryableSafetyAbort, "click budget expired"):
                    operator.confirm_discard_to_win_transition(page, triggered_at=100)
        self.assertEqual(page.screenshot.call_count, 2)
        self.assertEqual(operator.discard_to_win_candidate["startedAt"], 100)
        self.assertEqual(operator.action_evidence_started_at, 96.329)
        page.mouse.click.assert_not_called()

    def test_missing_first_capture_and_repeated_stream_trigger_keep_first_observation(self):
        operator = self.make_operator()
        page = Mock()
        page.screenshot.return_value = self.prompt(win=False)
        with patch("auto_operator.classify_screen", return_value=("match", 1)):
            operator.observe_discard_to_win_trigger(99.6)
            with self.assertRaisesRegex(RetryableSafetyAbort, "absent"):
                operator.confirm_discard_to_win_transition(page, triggered_at=100)
        page.screenshot.return_value = self.prompt()
        with patch("auto_operator.time.monotonic", return_value=103):
            operator.observe_discard_to_win_trigger(103)
            with self.assertRaisesRegex(RetryableSafetyAbort, "click budget expired"):
                operator.confirm_discard_to_win_transition(page, triggered_at=103)
        self.assertEqual(operator.discard_to_win_candidate["startedAt"], 99.6)
        self.assertEqual(page.screenshot.call_count, 1)
        page.mouse.click.assert_not_called()

    def test_missing_future_and_nonfinite_timestamps_fail_before_capture(self):
        for timestamp in (None, float("nan"), float("inf"), 100.01, -1, True):
            with self.subTest(timestamp=timestamp):
                operator = self.make_operator()
                page = Mock()
                with self.assertRaisesRegex(RetryableSafetyAbort, "valid observation timestamp"):
                    operator.confirm_discard_to_win_transition(page, triggered_at=timestamp)
                page.screenshot.assert_not_called()
                page.mouse.click.assert_not_called()

    def test_reobserving_confirmed_win_does_not_refresh_its_clock(self):
        operator = self.make_operator()
        page = Mock()
        prompt = self.prompt()
        page.screenshot.return_value = prompt
        with patch("auto_operator.classify_screen", return_value=("match", 1)), \
             patch("auto_operator.time.monotonic", return_value=100):
            operator.confirm_discard_to_win_transition(page, triggered_at=100)
        with patch("auto_operator.time.monotonic", return_value=103):
            operator.mark_action_evidence("win", observed_at=103)
            with self.assertRaisesRegex(RetryableSafetyAbort, "click budget expired"):
                operator.execute_force_auto_reaction_win(
                    page, prompt, {"center": {"x": 950, "y": 696.5}}, evaluated_captured_at=103,
                )
        self.assertEqual(operator.action_evidence_started_at, 100)
        self.assertEqual(page.screenshot.call_count, 2)
        page.mouse.click.assert_not_called()

    def test_stale_stream_cannot_create_candidate_if_live_prompt_is_gone(self):
        operator = self.make_operator()
        page = Mock()
        page.screenshot.return_value = self.prompt(win=False)
        with patch("auto_operator.classify_screen", return_value=("match", 1)):
            with self.assertRaisesRegex(RetryableSafetyAbort, "absent"):
                operator.confirm_discard_to_win_transition(page, triggered_at=100)
        self.assertIsNone(operator.discard_to_win_candidate["button"])
        self.assertEqual(operator.action_evidence_started_at, 96.329)
        page.mouse.click.assert_not_called()

    def test_draw_nonmatch_or_pending_discard_do_not_authorize_new_win(self):
        for draw, state, pending in ((True, "match", False), (False, "lobby", False),
                                     (False, "match", True)):
            with self.subTest(draw=draw, state=state, pending=pending):
                operator = self.make_operator()
                operator.pending_post_call_discard = pending
                page = Mock()
                page.screenshot.return_value = self.prompt(draw=draw)
                with patch("auto_operator.classify_screen", return_value=(state, 1)):
                    with self.assertRaisesRegex(RetryableSafetyAbort, "absent"):
                        operator.confirm_discard_to_win_transition(page, triggered_at=100)
                self.assertEqual(operator.action_evidence_kind, "discard")
                page.mouse.click.assert_not_called()

    def test_wrong_viewport_cannot_authorize_clock_replacement(self):
        operator = self.make_operator()
        page = Mock()
        page.screenshot.return_value = self.prompt()
        operator.layout["viewport"]["width"] = 1920
        with patch("auto_operator.classify_screen", return_value=("match", 1)):
            with self.assertRaisesRegex(RetryableSafetyAbort, "absent"):
                operator.confirm_discard_to_win_transition(page, triggered_at=100)
        self.assertEqual(operator.action_evidence_kind, "discard")

    def test_capture_exception_keeps_original_candidate_time(self):
        operator = self.make_operator()
        page = Mock()
        page.screenshot.side_effect = [self.prompt(), RuntimeError("capture failed"), self.prompt()]
        with patch("auto_operator.classify_screen", return_value=("match", 1)), \
             patch("auto_operator.time.monotonic", return_value=100):
            with self.assertRaisesRegex(RuntimeError, "capture failed"):
                operator.confirm_discard_to_win_transition(page, triggered_at=100)
        with patch("auto_operator.time.monotonic", return_value=103):
            with self.assertRaisesRegex(RetryableSafetyAbort, "click budget expired"):
                operator.confirm_discard_to_win_transition(page, triggered_at=100)
        self.assertEqual(page.screenshot.call_count, 2)
        self.assertEqual(operator.discard_to_win_candidate["startedAt"], 100)

    def test_real_riichi_and_kan_images_do_not_authorize_new_ron(self):
        root = Path(__file__).resolve().parents[1]
        images = [root / "artifacts/live/riichi-button-hand-border-20260928.jpg",
                  root / "test/fixtures/riichi-kan-prompt-20261022.jpg"]
        for image in images:
            with self.subTest(image=image.name):
                if not image.exists():
                    self.skipTest("local negative match recording is unavailable")
                operator = self.make_operator()
                operator.layout = load_json(root / "config/layout.json")
                operator.screen_references = load_references(root / "artifacts/live")
                page = Mock()
                page.screenshot.return_value = image.read_bytes()
                with self.assertRaisesRegex(RetryableSafetyAbort, "absent"):
                    operator.confirm_discard_to_win_transition(page, triggered_at=100)
                self.assertEqual(operator.action_evidence_kind, "discard")
                page.mouse.click.assert_not_called()

    def test_disappearance_does_not_rearm_same_reaction_after_generation_changes(self):
        operator = self.make_operator()
        page = Mock()
        page.screenshot.side_effect = [self.prompt(), self.prompt(win=False)]
        with patch("auto_operator.classify_screen", return_value=("match", 1)), \
             patch("auto_operator.time.monotonic", return_value=100):
            with self.assertRaisesRegex(RetryableSafetyAbort, "changed"):
                operator.confirm_discard_to_win_transition(page, triggered_at=100)
            operator.action_evidence_generation = 999
            with self.assertRaisesRegex(RetryableSafetyAbort, "ambiguous"):
                operator.confirm_discard_to_win_transition(page, triggered_at=100)
        self.assertEqual(page.screenshot.call_count, 2)
        self.assertEqual(operator.discard_to_win_candidate["startedAt"], 100)
        page.mouse.click.assert_not_called()

    def test_only_a_new_discard_action_can_rearm_a_rejected_candidate(self):
        operator = self.make_operator()
        page = Mock()
        page.screenshot.side_effect = [self.prompt(), self.prompt(win=False), self.prompt(), self.prompt()]
        with patch("auto_operator.classify_screen", return_value=("match", 1)):
            with self.assertRaisesRegex(RetryableSafetyAbort, "changed"):
                operator.confirm_discard_to_win_transition(page, triggered_at=99.5)
            operator.mark_action_evidence("discard", observed_at=99.8, supersede=True)
            operator.confirm_discard_to_win_transition(page, triggered_at=99.9)
        self.assertEqual(operator.action_evidence_kind, "win")
        self.assertEqual(operator.action_evidence_started_at, 99.9)
        self.assertEqual(page.screenshot.call_count, 4)

    def test_uncertain_raised_hand_and_inconsistent_open_cache_are_not_ron(self):
        root = Path(__file__).resolve().parents[1]
        frame = root / "test/fixtures/selection-white-riichi-timer-lift-20261028.png"
        for cached_open in (0, 1):
            with self.subTest(cached_open=cached_open):
                operator = self.make_operator()
                operator.layout = load_json(root / "config/layout.json")
                operator.cached_open_melds = cached_open
                operator.selection_uncertainty_latch = {"firstClickAt": 99}
                operator.screen_references = load_references(root / "artifacts/live")
                page = Mock()
                page.screenshot.return_value = frame.read_bytes()
                with self.assertRaisesRegex(RetryableSafetyAbort, "absent"):
                    operator.confirm_discard_to_win_transition(page, triggered_at=99.8)
                self.assertEqual(operator.action_evidence_kind, "discard")
                page.mouse.click.assert_not_called()

    def test_tracked_live_ron_image_verifies_two_independent_captures(self):
        root = Path(__file__).resolve().parents[1]
        frame = root / "artifacts/live/red-ron-prompt-20260928.png"
        operator = self.make_operator()
        operator.layout = load_json(root / "config/layout.json")
        operator.screen_references = load_references(root / "artifacts/live")
        # A failed previous selection may remain latched when the game has
        # automatically discarded. Only the current verified win is allowed;
        # the unresolved tile must never be clicked again.
        operator.selection_uncertainty_latch = {"firstClickAt": 98}
        page = Mock()
        page.screenshot.return_value = frame.read_bytes()
        _, _, button = operator.confirm_discard_to_win_transition(page, triggered_at=99.6)
        self.assertEqual(operator.action_evidence_started_at, 99.6)
        self.assertAlmostEqual(button["center"]["x"], 1002.5, delta=3)
        self.assertEqual(page.screenshot.call_count, 2)

    def test_replay_saved_a5daa23_ron_after_failed_discard(self):
        root = Path(__file__).resolve().parents[1]
        frame = root / ("artifacts/practice-5plus20-a5daa23-retry-20261030/frames/"
                        "2026-10-29T17-03-43.505695+00-00.png")
        if not frame.exists():
            self.skipTest("local a5daa23 match recording is unavailable")
        operator = self.make_operator()
        operator.layout = load_json(root / "config/layout.json")
        # The saved match reference enables the actual screen and button
        # detectors. Only capture I/O and monotonic time are reproduced.
        operator.screen_references = load_references(root / "artifacts/live")
        page = Mock()
        page.screenshot.return_value = frame.read_bytes()
        with patch("auto_operator.time.monotonic", return_value=100):
            second, captured, button = operator.confirm_discard_to_win_transition(page, triggered_at=100)
        self.assertEqual(second, frame.read_bytes())
        self.assertEqual(captured, 100)
        self.assertEqual(operator.action_evidence_started_at, 100)
        self.assertEqual(page.screenshot.call_count, 2)
        self.assertTrue(850 < button["center"]["x"] < 1100)


if __name__ == "__main__":
    unittest.main()
