"""An unknown initial turn may accept a named win, never arm ordinary play."""
import argparse
import base64
import hashlib
import io
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from auto_operator import PythonAutoOperator, load_json
from startup_turn_guard import StartupTurnGuard
from synchronous_capture import CaptureReceipt


ROOT = Path(__file__).resolve().parents[1]
TSUMO = ROOT / "test/fixtures/startup-tsumo-native-20261030.json"
RON = ROOT / "artifacts/live/red-ron-prompt-20260928.png"


class StartupTerminalWinTest(unittest.TestCase):
    def setUp(self):
        self.clock = 100.0
        clock = patch("auto_operator.time.monotonic", side_effect=lambda: self.clock)
        clock.start()
        self.addCleanup(clock.stop)
        self.operator = PythonAutoOperator.__new__(PythonAutoOperator)
        self.operator.args = argparse.Namespace(mode="force-auto", force_auto_click_budget_ms=2600,
                                                action_deadline_ms=300000, ranked_loop=False)
        self.operator.layout = load_json(ROOT / "config/layout-runtime.json")
        self.operator.layout["actionButtonRegions"] = load_json(ROOT / "config/layout.json")["actionButtonRegions"]
        # Native bottom-row evidence is sufficient; a private screen-reference
        # directory must not make these mandatory regressions pass or skip.
        self.operator.screen_references = {}
        self.operator.cached_open_melds = 0
        self.operator.action_evidence_started_at = None
        self.operator.action_budget_started_at = None
        self.operator.action_evidence_kind = None
        self.operator.log = Mock()
        self.operator.start_self_win_capture = Mock()
        self.page = Mock()
        self.guard = StartupTurnGuard()
        self.guard.observe(verified_match=True, action_visible=True, now=99)

    def read(self, path):
        if path == TSUMO:
            native = load_json(path)
            image = Image.new("RGB", tuple(native["size"]), (20, 40, 70))
            for part in native["parts"]:
                pixels = base64.b64decode(part["pngBase64"], validate=True)
                self.assertEqual(hashlib.sha256(pixels).hexdigest(), part["sha256"])
                image.paste(Image.open(io.BytesIO(pixels)), tuple(part["box"][:2]))
            encoded = io.BytesIO()
            image.save(encoded, "PNG")
            return encoded.getvalue()
        return path.read_bytes()

    def captures(self, frames, delay=.25):
        sequence = iter(frames)
        def capture(_page, _purpose):
            # Distinct requests retain the work of every earlier capture.
            self.clock += .01
            started = self.clock
            self.clock += delay
            return CaptureReceipt(next(sequence), started, started, self.clock, 1920, 1080, "mock_sync")
        self.operator.capture_full_action_frame = Mock(side_effect=capture)

    def run_candidate(self, frame, observed=99.9):
        return self.operator.try_startup_terminal_win(self.page, self.guard, frame, observed)

    def assert_quarantine_and_clocks_unchanged(self, started=None, budget=None, kind=None):
        self.assertTrue(self.guard.quarantined)
        self.assertFalse(self.guard.ready)
        self.assertEqual(self.operator.action_evidence_started_at, started)
        self.assertEqual(self.operator.action_budget_started_at, budget)
        self.assertEqual(self.operator.action_evidence_kind, kind)

    def test_named_native_win_controls_are_distinct_from_riichi_kan_and_unknown(self):
        template = load_json(ROOT / "templates/screens/startup-win-buttons.json")
        self.assertEqual(template["buttons"][0]["sourceSha256"], load_json(TSUMO)["sourceSha256"])
        for action, path in (("tsumo", TSUMO), ("ron", RON)):
            with self.subTest(action=action):
                button = self.operator.startup_terminal_win_button(self.read(path))
                self.assertEqual(button["action"], action)
                self.assertGreaterEqual(button["labelSimilarity"], .98)
        for name in ("test/fixtures/riichi-before-selection-20261020.jpg",
                     "artifacts/live/riichi-button-hand-border-20260928.jpg",
                     "test/fixtures/riichi-kan-prompt-20261022.jpg"):
            with self.subTest(name=name):
                self.assertIsNone(self.operator.startup_terminal_win_button(self.read(ROOT / name)))

    def test_two_independent_native_tsumo_captures_click_once_without_releasing_guard(self):
        frame = self.read(TSUMO)
        # A lossy streamed candidate can trigger verification, but only the
        # two native synchronous label matches authorize the eventual input.
        encoded = io.BytesIO()
        Image.open(io.BytesIO(frame)).convert("RGB").save(encoded, "JPEG", quality=55)
        self.captures([frame, frame])
        self.assertTrue(self.run_candidate(encoded.getvalue()))
        self.assertEqual(self.operator.capture_full_action_frame.call_count, 2)
        self.page.mouse.click.assert_called_once_with(1012.5, 817.0)
        self.operator.start_self_win_capture.assert_called_once_with("tsumo")
        self.assert_quarantine_and_clocks_unchanged()
        self.assertFalse(self.run_candidate(frame, self.clock))
        self.assertEqual(self.page.mouse.click.call_count, 1)

    def test_ron_is_terminal_only_and_preserves_an_existing_clock(self):
        frame = self.read(RON)
        self.operator.action_evidence_started_at = 99.0
        self.operator.action_budget_started_at = 99.1
        self.operator.action_evidence_kind = "win"
        self.captures([frame, frame])
        self.assertTrue(self.run_candidate(frame))
        self.assert_quarantine_and_clocks_unchanged(99.0, 99.1, "win")
        self.operator.start_self_win_capture.assert_called_once_with("ron")

    def test_unknown_or_changed_prompt_never_clicks_or_restarts_candidate_clock(self):
        frame = self.read(TSUMO)
        riichi = self.read(ROOT / "test/fixtures/riichi-before-selection-20261020.jpg")
        self.captures([frame, riichi, frame, frame])
        self.assertFalse(self.run_candidate(frame))
        self.clock += 1
        self.assertFalse(self.run_candidate(frame, self.clock))
        self.assertEqual(self.operator.startup_terminal_win_candidate["observedAt"], 99.9)
        self.assertEqual(self.operator.capture_full_action_frame.call_count, 2)
        self.page.mouse.click.assert_not_called()
        self.assert_quarantine_and_clocks_unchanged()

    def test_slow_captures_and_original_deadline_are_charged_before_any_input(self):
        frame = self.read(TSUMO)
        for case in ("slow", "existing_deadline", "local_deadline"):
            with self.subTest(case=case):
                self.operator.startup_terminal_win_candidate = None
                self.clock = 100
                self.operator.args.action_deadline_ms = 300000
                self.operator.action_evidence_started_at = None
                self.operator.action_budget_started_at = None
                if case == "existing_deadline":
                    self.operator.action_evidence_started_at = 99
                    self.operator.action_budget_started_at = 99
                    self.operator.args.action_deadline_ms = 1500
                elif case == "local_deadline":
                    self.operator.args.action_deadline_ms = 500
                self.captures([frame, frame], delay=1.4 if case == "slow" else .4)
                self.assertFalse(self.run_candidate(frame))
                self.page.mouse.click.assert_not_called()
                original = 99 if case == "existing_deadline" else None
                self.assert_quarantine_and_clocks_unchanged(original, original)

    def test_stale_stream_no_live_prompt_wrong_dimensions_draw_or_multiple_actions_abstain(self):
        frame = self.read(TSUMO)
        for case in ("gone", "dimensions", "draw", "multiple"):
            with self.subTest(case=case):
                self.operator.startup_terminal_win_candidate = None
                self.clock = 100
                image = Image.open(io.BytesIO(frame)).convert("RGB")
                if case == "gone":
                    ImageDraw.Draw(image).rectangle((880, 760, 1130, 880), fill=(35, 65, 90))
                elif case == "dimensions":
                    image = image.crop((0, 0, 1800, 1000))
                elif case == "draw":
                    slot = self.operator.layout["drawSlot"]
                    ImageDraw.Draw(image).rectangle((slot["x"], slot["y"], slot["x"] + slot["width"],
                                                    slot["y"] + slot["height"]), fill=(35, 65, 90))
                else:
                    ImageDraw.Draw(image).rectangle((690, 785, 850, 850), fill=(190, 90, 35))
                encoded = io.BytesIO()
                image.save(encoded, "PNG")
                self.captures([encoded.getvalue(), encoded.getvalue()])
                self.assertFalse(self.run_candidate(frame))
                self.page.mouse.click.assert_not_called()
                self.assert_quarantine_and_clocks_unchanged()

    def test_bad_observation_or_unordered_capture_times_fail_closed(self):
        frame = self.read(TSUMO)
        for timestamp in (None, float("nan"), float("inf"), 101, -1, True):
            with self.subTest(timestamp=timestamp):
                self.operator.startup_terminal_win_candidate = None
                self.captures([frame, frame])
                self.assertFalse(self.run_candidate(frame, timestamp))
                self.operator.capture_full_action_frame.assert_not_called()
        for stamp in (99, 1000, float("nan")):
            with self.subTest(stamp=stamp):
                self.operator.startup_terminal_win_candidate = None
                self.operator.capture_full_action_frame = Mock(return_value=
                    CaptureReceipt(frame, stamp, stamp, stamp, 1920, 1080, "mock_sync"))
                self.assertFalse(self.run_candidate(frame))
        self.page.mouse.click.assert_not_called()

    def test_missing_first_timestamp_cannot_rearm_same_win_three_seconds_later(self):
        frame = self.read(TSUMO)
        self.captures([frame, frame])
        self.assertFalse(self.run_candidate(frame, None))
        self.clock = 103
        self.assertFalse(self.run_candidate(frame, 103))
        self.operator.capture_full_action_frame.assert_not_called()
        self.page.mouse.click.assert_not_called()
        self.assert_quarantine_and_clocks_unchanged()

    def test_original_clock_cannot_change_between_win_captures(self):
        frame = self.read(TSUMO)
        self.operator.action_evidence_started_at = 99
        self.operator.action_budget_started_at = 99
        self.captures([frame, frame])
        capture = self.operator.capture_full_action_frame.side_effect
        def changed(*args):
            receipt = capture(*args)
            self.operator.action_evidence_started_at = self.clock
            return receipt
        self.operator.capture_full_action_frame.side_effect = changed
        self.assertFalse(self.run_candidate(frame))
        self.page.mouse.click.assert_not_called()
        self.assertTrue(self.guard.quarantined)
        self.assertFalse(self.guard.ready)

    def test_riichi_or_kan_cannot_leave_quarantine_and_capture_errors_do_not_click(self):
        for name in ("test/fixtures/riichi-before-selection-20261020.jpg", "test/fixtures/riichi-kan-prompt-20261022.jpg"):
            frame = self.read(ROOT / name)
            self.operator.startup_terminal_win_candidate = None
            self.captures([frame, frame])
            self.assertFalse(self.run_candidate(frame))
            self.assert_quarantine_and_clocks_unchanged()
        frame = self.read(TSUMO)
        self.operator.startup_terminal_win_candidate = None
        self.operator.capture_full_action_frame = Mock(side_effect=RuntimeError("capture failed"))
        with self.assertRaisesRegex(RuntimeError, "capture failed"):
            self.run_candidate(frame)
        self.page.mouse.click.assert_not_called()
        self.assert_quarantine_and_clocks_unchanged()


if __name__ == "__main__":
    unittest.main()
