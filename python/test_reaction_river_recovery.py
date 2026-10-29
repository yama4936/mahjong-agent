"""A recovered old river tile must not become the active call target."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock

from auto_operator import PythonAutoOperator, merge_public_observations


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/reaction-river-recovery-20261030.json"


class ReactionRiverRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text())
        self.partial = self.fixture["cachedPartial"]
        self.recovered = self.fixture["recoveredPrompt"]

    @staticmethod
    def opponent(observation, seat):
        return next(item for item in observation["opponentDiscards"] if item["seat"] == seat)

    def complete_append(self):
        after = copy.deepcopy(self.recovered)
        before = copy.deepcopy(after)
        before["capturedAt"] = "2026-10-29T20:47:27.750252+00:00"
        self.opponent(before, "south")["discards"].pop()
        return before, after

    def operator(self, before, after, previous=None):
        op = PythonAutoOperator.__new__(PythonAutoOperator)
        op.args = argparse.Namespace(mode="force-auto", board_metadata=True)
        op.public_state = {"seat": "east"}
        op.cached_open_melds = 0
        op.cached_public_observation = copy.deepcopy(before)
        op.previous_public_observation = copy.deepcopy(previous)
        op.public_cache_generation = 0
        op.log = Mock()
        op.recognize_reaction_context = Mock(return_value=(copy.deepcopy(after),
            {"tiles": self.fixture["hand"]}, {"verified": True}))
        op.evaluate = Mock(return_value={"status": "decision", "decision": {
            "selectedAction": {"id": "pon_5p", "action": "pon"},
            "callAssessments": [{"actionId": "pon_5p", "approved": True}],
        }})
        return op

    def test_recorded_four_to_five_recovery_reproduces_old_false_append_but_is_not_verified(self):
        self.assertEqual(PythonAutoOperator.infer_pending_discard(self.partial, self.recovered),
                         self.fixture["oldFalsePending"])
        self.assertIsNone(PythonAutoOperator.pending_reaction_discard(self.partial, self.recovered))
        self.assertEqual(self.opponent(self.partial, "south")["discards"],
                         self.opponent(self.recovered, "south")["discards"])

    def test_same_pon_prompt_abstains_without_reusing_5p_or_evaluating_unverified_5s(self):
        op = self.operator(self.partial, self.recovered)
        self.assertIsNone(op.evaluate_force_auto_call_policy(Path("same-pon.png"), "pon"))
        op.evaluate.assert_not_called()
        self.assertEqual(op.log.call_args.kwargs["reason"], "pending_discard_not_verified_on_prompt_frame")
        # A later complete view must not resurrect the partial baseline's old
        # tile as a second opportunity, even after public-cache promotion.
        later = copy.deepcopy(self.recovered)
        later["capturedAt"] = "2026-10-29T20:47:31.000000+00:00"
        op.recognize_reaction_context.return_value = (later, {"tiles": self.fixture["hand"]}, {"verified": True})
        self.assertIsNone(op.evaluate_force_auto_call_policy(Path("same-pon-later.png"), "pon"))
        op.evaluate.assert_not_called()

    def test_current_independent_highlight_can_still_verify_correct_5p(self):
        current = copy.deepcopy(self.recovered)
        current["highlightedDiscard"] = self.fixture["correctPending"]
        op = self.operator(self.partial, current)
        result = op.evaluate_force_auto_call_policy(Path("highlighted-pon.png"), "pon")
        self.assertEqual(op.evaluate.call_args.args[1], self.fixture["correctPending"])
        self.assertEqual(result["verifiedCallDiscard"], self.fixture["correctPending"])

    def test_genuine_complete_one_tile_append_and_next_opportunity_remain_distinct(self):
        before, after = self.complete_append()
        self.assertEqual(PythonAutoOperator.pending_reaction_discard(before, after),
                         self.fixture["correctPending"])
        later = copy.deepcopy(after)
        later["capturedAt"] = "2026-10-29T20:47:35.000000+00:00"
        self.opponent(later, "north")["discards"].append("9p")
        self.assertEqual(PythonAutoOperator.pending_reaction_discard(after, later),
                         {"tile": "9p", "fromSeat": "north"})
        self.assertIsNone(PythonAutoOperator.pending_reaction_discard(after, after))

    def test_every_river_requires_explicit_complete_observation_before_and_after(self):
        before, after = self.complete_append()
        for side in (0, 1):
            for seat in (None, "south", "west", "north"):
                for value in (False, None):
                    first, second = copy.deepcopy(before), copy.deepcopy(after)
                    target = (first, second)[side]
                    key = "ownDiscardsObserved" if seat is None else "discardsObserved"
                    target = target if seat is None else self.opponent(target, seat)
                    if value is None:
                        target.pop(key)
                    else:
                        target[key] = value
                    with self.subTest(side=side, seat=seat, value=value):
                        self.assertIsNone(PythonAutoOperator.pending_reaction_discard(first, second))

    def test_duplicate_reversed_missing_and_invalid_capture_times_cannot_prove_play(self):
        before, after = self.complete_append()
        for stamp in (before["capturedAt"], "2026-10-29T20:47:20+00:00", None, "invalid"):
            current = {**after, "capturedAt": stamp}
            with self.subTest(stamp=stamp):
                self.assertIsNone(PythonAutoOperator.pending_reaction_discard(before, current))

    def test_simultaneous_other_river_change_shrink_and_replacement_reject_inference(self):
        before, after = self.complete_append()
        for river in (["7s", "N", "E", "1s", "C", "9p"], ["7s", "N"], ["7s", "N", "E", "1s", "9p"]):
            current = copy.deepcopy(after)
            self.opponent(current, "north")["discards"] = river
            with self.subTest(river=river):
                self.assertIsNone(PythonAutoOperator.pending_reaction_discard(before, current))
        current = copy.deepcopy(after)
        current["ownDiscards"].append("2s")
        self.assertIsNone(PythonAutoOperator.pending_reaction_discard(before, current))
        current = copy.deepcopy(after)
        current["doraIndicators"].append("P")
        self.assertIsNone(PythonAutoOperator.pending_reaction_discard(before, current))

    def test_complete_async_cache_can_use_only_its_exact_matching_previous_baseline(self):
        before, after = self.complete_append()
        op = self.operator(after, after, previous=before)
        result = op.evaluate_force_auto_call_policy(Path("async-current.png"), "pon")
        self.assertEqual(result["verifiedCallDiscard"], self.fixture["correctPending"])
        self.assertEqual(op.log.call_args.kwargs["baseline"], "previous")

    def test_previous_baseline_cannot_jump_over_partial_changed_or_newer_cache(self):
        before, after = self.complete_append()
        partial = copy.deepcopy(after)
        self.opponent(partial, "west")["discardsObserved"] = False
        changed = copy.deepcopy(after)
        self.opponent(changed, "north")["discards"].append("9p")
        newer = {**after, "capturedAt": "2026-10-29T20:47:35+00:00"}
        for cache in (partial, changed, newer):
            with self.subTest(cache=cache):
                op = self.operator(cache, after, previous=before)
                self.assertIsNone(op.evaluate_force_auto_call_policy(Path("not-same-cache.png"), "pon"))
                op.evaluate.assert_not_called()

    def test_retained_cache_histories_do_not_keep_false_direct_observation_flags(self):
        prior = copy.deepcopy(self.recovered)
        current = copy.deepcopy(prior)
        current["capturedAt"] = "2026-10-29T20:47:35+00:00"
        current["ownDiscards"].pop()
        self.opponent(current, "west")["discards"].pop()
        merged = merge_public_observations(prior, current)
        self.assertEqual(merged["ownDiscards"], prior["ownDiscards"])
        self.assertFalse(merged["ownDiscardsObserved"])
        self.assertEqual(self.opponent(merged, "west")["discards"], self.opponent(prior, "west")["discards"])
        self.assertFalse(self.opponent(merged, "west")["discardsObserved"])
        self.assertIsNone(PythonAutoOperator.complete_reaction_river_signature(merged))

    def test_unconfirmed_own_append_is_history_not_direct_evidence(self):
        prior = copy.deepcopy(self.recovered)
        current = copy.deepcopy(prior)
        current["capturedAt"] = "2026-10-29T20:47:35+00:00"
        current["ownDiscards"].append("2s")
        op = self.operator(prior, current)
        op.pending_own_discard = {"tile": "2s", "before": prior["ownDiscards"]}
        op.pending_own_river_confirmation = None
        self.assertTrue(op.accept_public_observation(current))
        self.assertEqual(op.cached_public_observation["ownDiscards"], prior["ownDiscards"])
        self.assertFalse(op.cached_public_observation["ownDiscardsObserved"])

    def test_incomplete_or_duplicate_opponent_set_cannot_certify_a_unique_append(self):
        before, after = self.complete_append()
        for seats in (("south", "west"), ("south", "west", "west")):
            current = copy.deepcopy(after)
            current["opponentDiscards"] = [copy.deepcopy(self.opponent(after, seat)) for seat in seats]
            self.assertIsNone(PythonAutoOperator.pending_reaction_discard(before, current))

    def test_saved_hand_loses_legal_pon_only_when_the_false_5s_pending_is_injected(self):
        # Only the pure legal-action generator runs: no model, browser, API,
        # image recognition or full benchmark is invoked by this regression.
        script = """
import { readFileSync } from 'node:fs';
import { generateReactionActions } from './dist/src/game/actions.js';
const data=JSON.parse(readFileSync(0,'utf8'));
console.log(JSON.stringify([data.correctPending,data.oldFalsePending].map(pendingDiscard =>
  generateReactionActions({phase:'reaction',seat:'east',hand:data.hand,openMelds:0,
    availableUiActions:data.availableUiActions,pendingDiscard}))));
"""
        result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT,
                                input=json.dumps(self.fixture), text=True, capture_output=True, check=True)
        correct, false_pending = json.loads(result.stdout)
        self.assertEqual([item["id"] for item in correct], ["pon_5p", "pass"])
        self.assertEqual(correct[0]["consumedTiles"], ["0p", "5p"])
        self.assertEqual([item["id"] for item in false_pending], ["pass"])


if __name__ == "__main__":
    unittest.main()
