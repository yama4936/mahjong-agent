import argparse
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from auto_operator import PythonAutoOperator


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "test/fixtures"


class RoundTerminalRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.evidence = json.loads((FIXTURES / "round-terminal-recovery-20261023.json").read_text())
        self.frames = []
        for item in self.evidence["freshFrames"]:
            frame = (FIXTURES / item["file"]).read_bytes()
            self.assertEqual(hashlib.sha256(frame).hexdigest(), item["sha256"])
            self.frames.append(frame)
        self.metadata = self.evidence["freshFrames"][1]["metadata"]
        self.operator = PythonAutoOperator.__new__(PythonAutoOperator)
        op = self.operator
        op.args = argparse.Namespace(mode="force-auto", resume_away=True, ranked_loop=True)
        op.frames = Path(self.directory.name) / "frames"
        op.frames.mkdir()
        op.replays = Path(self.directory.name) / "replays"
        op.replays.mkdir()
        op.layout = json.loads((ROOT / "config/layout-300-regression.json").read_text())
        op.log = Mock()
        op.public_cache_generation = 7
        op.board_metadata_cache = None
        op.round_terminal_latched = True
        op.round_terminal_result_observed = False
        op.current_board_metadata = Mock(return_value=copy.deepcopy(self.metadata))
        self.old_replay = op.replays / "old.json"
        self.old_replay.write_text(json.dumps({"id": "old", "state": self.evidence["previousState"]}))
        op.pending_round_replays = [self.old_replay]
        op.pending_match_replays = [self.old_replay]
        self.page = Mock()

    def reload(self):
        op = self.operator
        # Each subcase is an independent reload scenario. The production
        # one-reload-per-ten-minutes guard remains enabled and separately tested.
        op.black_screen_reload_attempts = []
        op.black_screen_seen_since = 100
        self.page.screenshot.side_effect = [
            (FIXTURES / "black-client-20261021.png").read_bytes(),
            (FIXTURES / "client-startup-logo-20261021.png").read_bytes(),
        ]
        with patch("auto_operator.time.monotonic", return_value=116):
            self.assertTrue(op.recover_black_screen(self.page))
        self.page.screenshot.side_effect = None

    def test_reload_retains_missing_win_context_without_fabricating_a_result(self):
        self.reload()
        op = self.operator
        self.assertTrue(op.round_terminal_latched)
        self.assertFalse(op.round_terminal_result_observed)
        recovery = getattr(op, "round_terminal_recovery", None)
        self.assertIsNotNone(recovery, "a reload must not leave the win latch permanently unresolvable")
        self.assertEqual(recovery["previous"], self.evidence["previousState"])
        self.assertEqual(op.pending_round_replays, [self.old_replay])
        self.page.mouse.click.assert_not_called()

    def test_native_new_round_resumes_and_preserves_result_scopes(self):
        self.reload()
        op = self.operator
        with patch("auto_operator.time.monotonic", return_value=120):
            self.assertTrue(op.wait_for_round_terminal(self.page, self.frames[0], "match"))
            op.current_board_metadata.assert_not_called()
            self.assertFalse(op.wait_for_round_terminal(self.page, self.frames[1], "match"))
        self.assertFalse(op.round_terminal_latched)
        self.assertFalse(op.round_terminal_result_observed)
        self.assertEqual(op.pending_round_replays, [])
        self.assertEqual(op.pending_match_replays, [self.old_replay])
        self.assertNotIn("actualResult", json.loads(self.old_replay.read_text()))
        ledgers = list(op.frames.glob("*.round-terminal-unobserved-result.json"))
        self.assertEqual(len(ledgers), 1)
        ledger = json.loads(ledgers[0].read_text())
        self.assertEqual(ledger["pendingRoundReplays"], [str(self.old_replay)])
        self.assertEqual(ledger["current"], self.metadata)
        self.page.mouse.click.assert_not_called()
        # A later round result belongs only to the new round. The native match
        # result must still reach both rounds' original replay files.
        new_replay = op.replays / "new.json"
        new_replay.write_text(json.dumps({"id": "new"}))
        op.pending_round_replays.append(new_replay)
        op.pending_match_replays.append(new_replay)
        self.assertEqual(op.attach_outcome("round", b"later round", 1), 1)
        self.assertNotIn("actualResult", json.loads(self.old_replay.read_text()))
        self.assertEqual(op.attach_outcome("match", b"native final", 1), 2)
        self.assertNotIn("round", json.loads(self.old_replay.read_text())["actualResult"])
        self.assertEqual(json.loads(self.old_replay.read_text())["actualResult"]["match"],
                         json.loads(new_replay.read_text())["actualResult"]["match"])

    def test_away_dialog_can_resume_even_when_outer_classifier_says_match(self):
        self.reload()
        item = self.evidence["awayFrame"]
        away = (FIXTURES / item["file"]).read_bytes()
        self.assertEqual(hashlib.sha256(away).hexdigest(), item["sha256"])
        self.page.screenshot.return_value = self.frames[0]
        self.assertTrue(self.operator.wait_for_round_terminal(self.page, away, "match"))
        self.page.mouse.click.assert_called_once_with(962.88, 697.14)
        self.assertTrue(self.operator.round_terminal_latched)
        self.assertFalse(self.operator.round_terminal_result_observed)
        self.operator.current_board_metadata.assert_not_called()

    def test_same_hand_unverified_board_wrong_wind_and_new_match_stay_blocked(self):
        variants = [
            {**self.metadata, "round": "east_3", "honba": 0, "seat": "east"},
            {**self.metadata, "verified": False},
            {**self.metadata, "seat": "south"},
            {**self.metadata, "round": "east_1", "honba": 0},
            {**self.metadata, "remainingTiles": 0},
        ]
        for metadata in variants:
            with self.subTest(metadata=metadata):
                self.reload()
                self.operator.current_board_metadata.return_value = metadata
                with patch("auto_operator.time.monotonic", return_value=120):
                    self.assertTrue(self.operator.wait_for_round_terminal(self.page, self.frames[0], "match"))
                    self.assertTrue(self.operator.wait_for_round_terminal(self.page, self.frames[1], "match"))
                self.assertTrue(self.operator.round_terminal_latched)
                self.assertEqual(self.operator.pending_round_replays, [self.old_replay])
        self.page.mouse.click.assert_not_called()

    def test_unverifiable_recovery_stops_with_evidence_instead_of_waiting_forever(self):
        self.reload()
        op = self.operator
        op.current_board_metadata.return_value = {"verified": False}
        with patch("auto_operator.time.monotonic", return_value=120):
            self.assertTrue(op.wait_for_round_terminal(self.page, self.frames[0], "match"))
        with patch("auto_operator.time.monotonic", return_value=151):
            with self.assertRaisesRegex(RuntimeError, "terminal.*recovery"):
                op.wait_for_round_terminal(self.page, self.frames[1], "match")
        stop = next(c.kwargs for c in op.log.call_args_list
                    if c.args == ("round_terminal_recovery_stop",))
        self.assertEqual(Path(stop["screenshot"]).read_bytes(), self.frames[1])
        self.assertEqual(op.pending_match_replays, [self.old_replay])
        self.assertTrue(op.round_terminal_latched)
        self.page.mouse.click.assert_not_called()

    def test_regular_unobserved_win_still_waits_and_observed_result_still_clears(self):
        op = self.operator
        for frame in self.frames:
            self.assertTrue(op.wait_for_round_terminal(self.page, frame, "match"))
        self.assertEqual(op.pending_round_replays, [self.old_replay])
        op.round_terminal_result_observed = True
        self.assertFalse(op.wait_for_round_terminal(self.page, self.frames[1], "match"))
        self.assertFalse(op.round_terminal_latched)
        op.current_board_metadata.assert_not_called()
        self.page.mouse.click.assert_not_called()

    def test_missing_previous_hand_cannot_unlock_a_visible_later_table(self):
        self.old_replay.unlink()
        self.reload()
        with patch("auto_operator.time.monotonic", return_value=120):
            for frame in self.frames:
                self.assertTrue(self.operator.wait_for_round_terminal(self.page, frame, "match"))
        self.assertTrue(self.operator.round_terminal_latched)
        self.assertEqual(self.operator.pending_match_replays, [self.old_replay])
        self.page.mouse.click.assert_not_called()

    def test_dealer_continuation_and_seat_rotation_are_required(self):
        previous = self.evidence["previousState"]
        self.assertTrue(PythonAutoOperator.round_advanced_after_recovery(previous, self.metadata))
        self.assertTrue(PythonAutoOperator.round_advanced_after_recovery(
            previous, {**self.metadata, "round": "east_3", "honba": 1, "seat": "east"}))
        for invalid in (None, "unknown", {**previous, "honba": True}):
            self.assertFalse(PythonAutoOperator.round_advanced_after_recovery(invalid, self.metadata))


if __name__ == "__main__":
    unittest.main()
