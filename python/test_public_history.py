"""Regression evidence for public history lost between reaction prompts."""
import argparse
import copy
import json
import os
import tempfile
import threading
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import Mock

from auto_operator import PythonAutoOperator, merge_public_observations

FIXTURE = Path(__file__).resolve().parents[1] / "test/fixtures/opponent-river-single-error-20261023.json"


def opponent(observation, seat):
    return next(row for row in observation["opponentDiscards"] if row["seat"] == seat)


class PublicHistoryTest(unittest.TestCase):
    def setUp(self):
        fixture = json.loads(FIXTURE.read_text())
        self.prior = fixture["initialObservation"]
        self.first, self.second = [capture["observation"] for capture in fixture["captures"]]

    def operator(self):
        op = PythonAutoOperator.__new__(PythonAutoOperator)
        op.args = argparse.Namespace(board_metadata=False)
        op.public_state = {"seat": "east"}
        op.cached_open_melds = 0
        op.cached_public_observation = copy.deepcopy(self.prior)
        op.previous_public_observation = None
        op.public_cache_generation = 9
        op.public_recognition_lock = threading.Lock()
        op.public_recognition_result = None
        op.log = Mock()
        op.evaluate = Mock()
        op.observe_public_board = Mock(side_effect=[self.first, self.second])
        return op

    def test_saved_single_error_rivers_recover_after_two_complete_captures(self):
        pending = merge_public_observations(self.prior, self.first)
        for seat in ("south", "west"):
            self.assertEqual(opponent(pending, seat)["discards"], opponent(self.prior, seat)["discards"])
        repaired = merge_public_observations(pending, self.second)
        for seat in ("south", "west"):
            self.assertEqual(opponent(repaired, seat)["discards"], opponent(self.second, seat)["discards"])
        self.assertEqual({item["seat"] for item in repaired["opponentRiverRepairs"]}, {"south", "west"})
        self.assertEqual(len(opponent(repaired, "west")["melds"]), 2)

    def test_unverified_reaction_still_promotes_fresh_public_evidence(self):
        op = self.operator()
        self.assertIsNone(op.evaluate_force_auto_call_policy(Path("first.png"), "pon"))
        self.assertEqual(op.cached_public_observation["capturedAt"], self.first["capturedAt"])
        self.assertIn("south", op.cached_public_observation["_opponentRiverCandidates"])
        self.assertIsNone(op.evaluate_force_auto_call_policy(Path("second.png"), "pon"))
        for seat in ("south", "west"):
            self.assertEqual(opponent(op.cached_public_observation, seat)["discards"],
                             opponent(self.second, seat)["discards"])
        op.evaluate.assert_not_called()
        self.assertEqual(len(opponent(op.cached_public_observation, "west")["melds"]), 2)

    def test_pending_river_correction_does_not_publish_fifth_copy_from_new_meld(self):
        pending = merge_public_observations(self.prior, self.first)
        self.assertEqual(len(opponent(pending, "west")["melds"]), 1)
        self.assertFalse(opponent(pending, "west")["meldsObserved"])
        self.assertEqual(pending["opponentMeldsDeferred"], [{"seat": "west", "conflictingTiles": ["1s"]}])
        repaired = merge_public_observations(pending, self.second)
        self.assertEqual(len(opponent(repaired, "west")["melds"]), 2)
        self.assertEqual(repaired["opponentMeldsDeferred"], [])
        for observation in (pending, repaired):
            tiles = observation["ownDiscards"] + observation["doraIndicators"] + observation["otherVisibleTiles"]
            counts = Counter("5" + tile[1:] if tile.startswith("0") else tile for tile in tiles)
            self.assertLessEqual(max(counts.values()), 4)

    def test_single_error_repair_rejects_unaligned_or_incomplete_captures(self):
        pending = merge_public_observations(self.prior, self.first)
        variants = []
        for field in ("ownDiscards", "doraIndicators"):
            bad = copy.deepcopy(self.second)
            bad[field] = ["9m"]
            variants.append(bad)
        bad = copy.deepcopy(self.second)
        for row in bad["opponentDiscards"]:
            row["discardsObserved"] = False
        variants.append(bad)
        bad = copy.deepcopy(self.second)
        for row in bad["opponentDiscards"]:
            row["discards"][0] = "C"
        variants.append(bad)
        for bad in variants:
            with self.subTest(observation=bad):
                result = merge_public_observations(pending, bad)
                self.assertEqual(result["opponentRiverRepairs"], [])
                for seat in ("south", "west"):
                    self.assertEqual(opponent(result, seat)["discards"], opponent(self.prior, seat)["discards"])

    def test_single_error_repair_rejects_duplicate_old_and_expired_captures(self):
        pending = merge_public_observations(self.prior, self.first)
        for stamp in (self.first["capturedAt"], self.prior["capturedAt"],
                      "2026-10-22T19:33:00+00:00", None):
            bad = {**self.second, "capturedAt": stamp}
            result = merge_public_observations(pending, bad)
            self.assertEqual(result["opponentRiverRepairs"], [])

    def test_reaction_promotion_invalidates_older_async_envelope(self):
        op = self.operator()
        op.evaluate_force_auto_call_policy(Path("first.png"), "pon")
        promoted = copy.deepcopy(op.cached_public_observation)
        op.public_recognition_result = {"generation": 9, "result": self.prior}
        op.poll_public_recognition()
        self.assertEqual(op.cached_public_observation, promoted)
        self.assertEqual(op.public_cache_generation, 10)

    def test_verified_call_uses_pre_promotion_river_baseline(self):
        op = self.operator()
        prior = {"capturedAt": "2026-10-22T19:32:00+00:00", "opponentDiscards": [
            {"seat": "south", "discards": ["E"]},
        ]}
        fresh = {"capturedAt": "2026-10-22T19:32:02+00:00", "opponentDiscards": [
            {"seat": "south", "discards": ["E", "P"], "discardsObserved": True},
        ]}
        for observation in (prior, fresh):
            observation["ownDiscardsObserved"] = True
            observation["opponentDiscards"].extend([
                {"seat": "west", "discards": [], "discardsObserved": True},
                {"seat": "north", "discards": [], "discardsObserved": True},
            ])
            for row in observation["opponentDiscards"]:
                row["discardsObserved"] = True
        op.cached_public_observation = prior
        op.observe_public_board = Mock(return_value=fresh)
        op.recognize_reaction_hand = Mock(return_value={"tiles": ["1m"] * 13})
        approved = {"status": "decision", "decision": {
            "selectedAction": {"id": "pon_P", "action": "pon"},
            "callAssessments": [{"actionId": "pon_P", "approved": True}],
        }}
        op.evaluate.return_value = approved
        result = op.evaluate_force_auto_call_policy(Path("call.png"), "pon")
        self.assertIs(result, approved)
        self.assertEqual(result["verifiedCallDiscard"], {"tile": "P", "fromSeat": "south"})
        self.assertIs(op.previous_public_observation, prior)
        self.assertEqual(opponent(op.cached_public_observation, "south")["discards"], ["E", "P"])

    def test_reaction_promotion_keeps_two_capture_own_receipt_guard(self):
        op = self.operator()
        op.pending_own_discard = {"tile": "P", "before": self.prior["ownDiscards"]}
        op.pending_own_river_confirmation = None
        op.evaluate_force_auto_call_policy(Path("first.png"), "pon")
        candidate = list(self.first["ownDiscards"])
        self.assertEqual(op.cached_public_observation["ownDiscards"], self.prior["ownDiscards"])
        self.assertEqual(op.pending_own_river_confirmation, candidate)
        # Reusing the same observation cannot certify a second receipt.
        op.observe_public_board = Mock(return_value=self.first)
        op.evaluate_force_auto_call_policy(Path("same.png"), "pon")
        self.assertEqual(op.cached_public_observation["ownDiscards"], self.prior["ownDiscards"])
        op.observe_public_board = Mock(return_value={**self.first, "capturedAt": self.second["capturedAt"]})
        op.evaluate_force_auto_call_policy(Path("later.png"), "pon")
        self.assertEqual(op.cached_public_observation["ownDiscards"], candidate)
        self.assertIsNone(op.pending_own_river_confirmation)

    def test_obsolete_reaction_capture_does_not_rewind_public_cache(self):
        op = self.operator()
        op.cached_public_observation = copy.deepcopy(self.second)
        op.evaluate_force_auto_call_policy(Path("old.png"), "pon")
        self.assertEqual(op.cached_public_observation, self.second)
        self.assertEqual(op.public_cache_generation, 9)

    def test_unverified_hud_does_not_promote_prompt_history(self):
        op = self.operator()
        op.args.board_metadata = True
        op.recognize_reaction_context = Mock(return_value=(self.first, {}, {"verified": False}))
        op.evaluate_force_auto_call_policy(Path("unverified.png"), "pon")
        self.assertEqual(op.cached_public_observation, self.prior)

    def test_resident_prompt_request_uses_frame_time_before_recognition(self):
        op = self.operator()
        op.args.mode = "force-auto"
        op.public_recognition_server = Mock()
        op.public_recognition_server.poll.return_value = None
        op.public_recognition_request_id = 0
        op.request_public_recognition = Mock(return_value={})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old-prompt.png"
            path.write_bytes(b"saved frame")
            os.utime(path, (1_700_000_000, 1_700_000_000))
            PythonAutoOperator.observe_public_board(op, path, reaction_highlight=True)
        request = op.request_public_recognition.call_args.args[0]
        self.assertEqual(request["capturedAt"], "2023-11-14T22:13:20+00:00")


if __name__ == "__main__":
    unittest.main()
