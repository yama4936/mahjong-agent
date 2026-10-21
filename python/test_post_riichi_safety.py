import argparse
import copy
import io
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from auto_operator import PythonAutoOperator

FIXTURES = Path(__file__).resolve().parents[1] / "test/fixtures"


class PostRiichiSafetyTest(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((FIXTURES / "post-riichi-passed-tile-20261021.json").read_text())
        self.before = self.fixture["priorPassedDiscard"]["state"]
        self.following = self.fixture["followingDecision"]["state"]
        self.op = PythonAutoOperator.__new__(PythonAutoOperator)
        self.op.log = Mock()
        self.op.screencast_session = object()
        self.op.screencast_draw_generation = 10
        self.op.screencast_draw_occupied = False
        self.op.apply_post_riichi_safety(copy.deepcopy(self.before), self_turn=True)
        self.op.riichi_metadata_history = {**copy.deepcopy(self.before), "verified": True, "riichiSeats": ["south"]}

    def pending(self):
        return {"tile": "1s", "before": list(self.before["ownDiscards"]),
                "riichiContext": self.op.own_discard_riichi_context({"state": self.before})}

    def confirm(self, actual="1s"):
        self.op.pending_own_discard = self.pending()
        self.op.cached_public_observation = {"ownDiscards": [*self.before["ownDiscards"], actual]}
        self.op.reconcile_own_discard()

    def applied(self, *, self_turn=True):
        state = copy.deepcopy(self.following)
        self.op.apply_post_riichi_safety(state, self_turn=self_turn)
        return next(opponent for opponent in state["opponents"] if opponent["seat"] == "south")

    def test_confirmed_river_is_not_safe_until_a_later_own_draw(self):
        self.confirm()
        self.assertIsNone(self.op.pending_own_discard)
        self.assertNotIn("postRiichiSafeTiles", self.applied())
        self.op.screencast_draw_occupied = True
        self.assertNotIn("postRiichiSafeTiles", self.applied())
        self.op.screencast_draw_generation = 11
        self.assertNotIn("postRiichiSafeTiles", self.applied(self_turn=False))
        self.op.screencast_draw_occupied = False
        self.assertNotIn("postRiichiSafeTiles", self.applied())
        self.op.screencast_draw_occupied = True
        self.assertEqual(self.applied()["postRiichiSafeTiles"], ["1s"])
        # Once proved, the history also accompanies later reaction decisions.
        self.assertEqual(self.applied(self_turn=False)["postRiichiSafeTiles"], ["1s"])
        self.assertEqual(len(self.op.post_riichi_pass_candidates), 0)
        self.assertEqual(sum(call.args[0] == "post_riichi_pass_verified" for call in self.op.log.call_args_list), 1)

    def test_predeclaration_unverified_or_wrong_round_evidence_is_not_recorded(self):
        for changes in ({"riichiSeats": []}, {"verified": False}, {"honba": 2}, {"seat": "east"}):
            with self.subTest(changes=changes):
                self.op.riichi_metadata_history = {**self.before, "verified": True, "riichiSeats": ["south"], **changes}
                self.assertIsNone(self.op.own_discard_riichi_context({"state": self.before}))
        self.op.riichi_metadata_history = {**self.before, "verified": True, "riichiSeats": ["south"]}
        state = copy.deepcopy(self.before)
        state["opponents"][1]["riichi"] = False
        self.assertIsNone(self.op.own_discard_riichi_context({"state": state}))

    def test_mismatched_or_unconfirmed_discard_does_not_create_safety(self):
        self.op.pending_own_discard = self.pending()
        self.op.cached_public_observation = {"ownDiscards": self.before["ownDiscards"]}
        self.op.reconcile_own_discard()
        self.assertEqual(self.op.post_riichi_pass_candidates, [])
        self.confirm("2s")
        self.assertEqual(self.op.post_riichi_pass_candidates, [])
        self.op.screencast_draw_generation = 11
        self.op.screencast_draw_occupied = True
        self.assertNotIn("postRiichiSafeTiles", self.applied())

    def test_round_seat_and_result_boundaries_invalidate_pending_proofs(self):
        for changes in ({"honba": 2}, {"round": "east_2"}, {"seat": "east"}):
            with self.subTest(changes=changes):
                self.setUp()
                old_pending = self.pending()
                self.confirm()
                state = {**copy.deepcopy(self.following), **changes}
                self.op.apply_post_riichi_safety(state, self_turn=True)
                self.op.record_post_riichi_pass_candidate(old_pending, "1s")
                self.assertEqual(self.op.post_riichi_pass_candidates, [])
                self.assertEqual(self.op.post_riichi_safe_tiles, {})
        for outcome in ("round", "match"):
            with self.subTest(outcome=outcome):
                self.setUp()
                old_pending = self.pending()
                self.confirm()
                self.op.observe_ranked_outcome(outcome)
                self.op.record_post_riichi_pass_candidate(old_pending, "1s")
                self.op.screencast_draw_generation = 11
                self.op.screencast_draw_occupied = True
                self.assertNotIn("postRiichiSafeTiles", self.applied())

    def test_no_screencast_proof_and_configured_markers_are_not_trusted(self):
        self.op.screencast_session = None
        self.confirm()
        self.assertEqual(self.op.post_riichi_pass_candidates, [])
        state = copy.deepcopy(self.following)
        state["opponents"][1]["postRiichiSafeTiles"] = ["3m"]
        self.op.apply_post_riichi_safety(state, self_turn=True)
        self.assertNotIn("postRiichiSafeTiles", state["opponents"][1])

    def test_verified_marker_reaches_actual_resident_request_without_mutating_config(self):
        self.confirm()
        self.op.screencast_draw_generation = 11
        self.op.screencast_draw_occupied = True
        self.op.public_state = copy.deepcopy(self.following)
        original = copy.deepcopy(self.op.public_state)
        self.op.args = argparse.Namespace(board_metadata=True)
        self.op.poll_public_recognition = Mock()
        self.op.current_board_metadata = lambda _path: {**copy.deepcopy(self.following), "verified": True, "riichiSeats": ["south"]}
        self.op.action_deadline_remaining_ms = lambda: 300000
        self.op.recognition_request_id = 0
        self.op.recognition_server = Mock()
        self.op.recognition_server.poll.return_value = None
        self.op.recognition_server.stdin = io.StringIO()
        self.op.recognition_server.stdout = io.StringIO('{"id":1,"result":{}}\n')
        with patch("board_metadata.recognize_riichi_sticks", return_value=["south"]):
            self.op.recognize_resident(FIXTURES / "black-client-20261021.png", evaluate_force_auto=True)
        request = json.loads(self.op.recognition_server.stdin.getvalue())
        opponent = next(opponent for opponent in request["publicState"]["opponents"] if opponent["seat"] == "south")
        self.assertEqual(opponent["postRiichiSafeTiles"], ["1s"])
        self.assertEqual(self.op.public_state, original)
        self.assertEqual(opponent["discards"], original["opponents"][1]["discards"])

    def test_metadata_remaps_calibrated_regions_but_keeps_the_actual_riichi_target(self):
        from board_metadata import remap_seats
        self.confirm()
        self.op.screencast_draw_generation = 11
        self.op.screencast_draw_occupied = True
        self.op.public_state = remap_seats(copy.deepcopy(self.following), "north", "east")
        original = copy.deepcopy(self.op.public_state)
        metadata = {**copy.deepcopy(self.following), "verified": True, "riichiSeats": ["south"]}
        with patch("board_metadata.recognize_riichi_sticks", return_value=["south"]):
            state, _, _ = self.op.frame_metadata_state(
                FIXTURES / "black-client-20261021.png", prepared_metadata=metadata)
        self.assertEqual(state["seat"], "north")
        self.assertEqual(next(opponent for opponent in state["opponents"] if opponent["seat"] == "south")["postRiichiSafeTiles"], ["1s"])
        self.assertTrue(all("postRiichiSafeTiles" not in opponent for opponent in state["opponents"] if opponent["seat"] != "south"))
        self.assertEqual(self.op.public_state, original)


if __name__ == "__main__":
    unittest.main()
