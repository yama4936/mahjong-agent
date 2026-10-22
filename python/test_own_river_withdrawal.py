"""A called confirmed own discard must not freeze the rest of the river."""
import argparse
import copy
import datetime
import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from auto_operator import PythonAutoOperator, merge_public_observations


class OwnRiverWithdrawalTest(unittest.TestCase):
    def setUp(self):
        fixture = json.loads((Path(__file__).resolve().parents[1] /
            "test/fixtures/own-river-called-away-20261023.json").read_text())
        self.prior = fixture["initialObservation"]
        self.first, self.second, self.late = [c["observation"] for c in fixture["captures"]]

    def test_native_called_7m_releases_own_river_after_two_captures(self):
        pending = merge_public_observations(self.prior, self.first, 0)
        self.assertEqual(pending["ownDiscards"], ["7m"])
        repaired = merge_public_observations(pending, self.second, 0)
        self.assertEqual(repaired["ownDiscards"], ["1p"])
        self.assertEqual(repaired["ownRiverWithdrawals"][0]["tile"], "7m")
        self.assertEqual(merge_public_observations(repaired, self.late, 0)["ownDiscards"],
                         self.late["ownDiscards"])

    def operator(self):
        op = PythonAutoOperator.__new__(PythonAutoOperator)
        op.args = argparse.Namespace(board_metadata=False)
        op.cached_open_melds = 0
        op.cached_public_observation = copy.deepcopy(self.prior)
        op.previous_public_observation = None
        op.cached_concealed_tiles = ["9p"]
        op.pending_own_discard = {"tile": "1p", "before": ["7m"]}
        op.pending_own_river_confirmation = None
        op.log = Mock()
        return op

    def test_pending_receipt_still_needs_two_observations_after_rebase(self):
        op = self.operator()
        op.accept_public_observation(copy.deepcopy(self.first))
        op.accept_public_observation(copy.deepcopy(self.second))
        self.assertEqual(op.cached_public_observation["ownDiscards"], [])
        self.assertEqual(op.pending_own_discard["before"], [])
        self.assertIsNone(op.cached_concealed_tiles)
        self.assertFalse(any(c.args[0] == "public_own_river_append_confirmed"
                             for c in op.log.call_args_list))
        third = copy.deepcopy(self.second)
        third["capturedAt"] = "2026-10-22T21:21:12.000000+00:00"
        op.accept_public_observation(third)
        self.assertEqual(op.cached_public_observation["ownDiscards"], ["1p"])
        self.assertEqual(sum(c.args[0] == "public_own_river_append_confirmed"
                             for c in op.log.call_args_list), 1)

    def repaired(self, prior=None, first=None, second=None):
        pending = merge_public_observations(prior or self.prior, first or self.first, 0)
        return merge_public_observations(pending, second or self.second, 0)

    def test_partial_rows_and_unobserved_melds_cannot_withdraw(self):
        for mutation in ("ownDiscardsObserved", "ownMeldsObserved", "meldsObserved"):
            first, second = copy.deepcopy(self.first), copy.deepcopy(self.second)
            for row in (first, second):
                if mutation == "meldsObserved":
                    next(o for o in row["opponentDiscards"] if o["seat"] == "west")[mutation] = False
                else:
                    row[mutation] = False
            with self.subTest(mutation=mutation):
                self.assertEqual(self.repaired(first=first, second=second)["ownDiscards"], ["7m"])

    def test_preexisting_call_does_not_explain_withdrawal(self):
        prior = copy.deepcopy(self.prior)
        next(o for o in prior["opponentDiscards"] if o["seat"] == "west")["melds"] = \
            copy.deepcopy(next(o for o in self.first["opponentDiscards"] if o["seat"] == "west")["melds"])
        self.assertEqual(self.repaired(prior=prior)["ownDiscards"], ["7m"])

    def test_duplicate_reversed_close_and_expired_captures_do_not_corroborate(self):
        first = datetime.datetime.fromisoformat(self.first["capturedAt"])
        for seconds in (0, -1, 0.1, 31):
            second = copy.deepcopy(self.second)
            second["capturedAt"] = (first + datetime.timedelta(seconds=seconds)).isoformat()
            with self.subTest(seconds=seconds):
                self.assertEqual(self.repaired(second=second)["ownDiscards"], ["7m"])

    def test_new_call_witness_survives_initial_empty_incomplete_own_crop(self):
        first = copy.deepcopy(self.first)
        first["ownDiscards"], first["ownDiscardsObserved"] = [], False
        initial = merge_public_observations(self.prior, first, 0)
        pending = merge_public_observations(initial, self.second, 0)
        third = copy.deepcopy(self.second)
        third["capturedAt"] = "2026-10-22T21:21:12.000000+00:00"
        self.assertEqual(merge_public_observations(pending, third, 0)["ownDiscards"], ["1p"])

    def test_still_visible_tile_and_unrelated_or_invalid_chi_do_not_withdraw(self):
        for variant in ("visible", "unrelated", "invalid", "wrong_seat"):
            first, second = copy.deepcopy(self.first), copy.deepcopy(self.second)
            for row in (first, second):
                west = next(o for o in row["opponentDiscards"] if o["seat"] == "west")
                if variant == "visible":
                    row["ownDiscards"] = ["7m", "1p"]
                elif variant == "unrelated":
                    west["melds"][0]["tiles"] = ["1m", "2m", "3m"]
                elif variant == "invalid":
                    west["melds"][0]["tiles"] = ["2m", "5m", "7m"]
                else:
                    east = next(o for o in row["opponentDiscards"] if o["seat"] == "east")
                    east["melds"], west["melds"] = west["melds"], []
            with self.subTest(variant=variant):
                result = self.repaired(first=first, second=second)
                self.assertFalse(result.get("ownRiverWithdrawals"))

    def test_misaligned_dora_and_fifth_copy_block_repair(self):
        for variant in ("dora", "fifth_copy", "different_row"):
            second = copy.deepcopy(self.second)
            if variant == "dora":
                second["doraIndicators"] = ["9m"]
            elif variant == "fifth_copy":
                second["ownDiscards"] = ["1p"] * 5
            else:
                second["ownDiscards"] = ["2p"]
            with self.subTest(variant=variant):
                self.assertEqual(self.repaired(second=second)["ownDiscards"], ["7m"])

    def test_no_missing_earlier_prefix_or_ambiguous_duplicate_rewrite(self):
        for before in (["7m", "N"], ["7m", "7m"]):
            prior = copy.deepcopy(self.prior)
            prior["ownDiscards"] = before
            first, second = copy.deepcopy(self.first), copy.deepcopy(self.second)
            for row in (first, second):
                row["ownDiscards"] = (["N"] if before[-1] == "N" else ["7m"]) + ["1p"]
            self.assertEqual(self.repaired(prior, first, second)["ownDiscards"], before)

    def test_red_identity_and_riichi_are_preserved(self):
        for called_tile in ("5m", "0m"):
            prior = copy.deepcopy(self.prior)
            prior["ownDiscards"], prior["ownRiichiDeclared"] = ["0m"], True
            first, second = copy.deepcopy(self.first), copy.deepcopy(self.second)
            for row in (first, second):
                next(o for o in row["opponentDiscards"] if o["seat"] == "west")["melds"] = [
                    {"type": "chi", "tiles": ["4m", called_tile, "6m"]}]
            result = self.repaired(prior, first, second)
            self.assertEqual(result["ownDiscards"], ["1p"] if called_tile == "0m" else ["0m"])
            self.assertTrue(result["ownRiichiDeclared"])

    def test_queued_receipt_baselines_rebase_without_certification(self):
        op = self.operator()
        op.pending_own_discard = {"tile": "1s", "before": ["7m"],
            "earlierReceipts": [{"tile": "1p", "before": ["7m"]}]}
        for observation in (self.first, self.second):
            op.accept_public_observation(copy.deepcopy(observation))
        self.assertEqual(op.pending_own_discard["before"], [])
        self.assertEqual(op.pending_own_discard["earlierReceipts"][0]["before"], [])
        self.assertEqual(op.cached_public_observation["ownDiscards"], [])
        self.assertFalse(any(c.args[0] == "own_discard_reconciled" for c in op.log.call_args_list))

    def test_incompatible_pending_baseline_is_retired_uncertified(self):
        op = self.operator()
        op.pending_own_discard["before"] = ["3m"]
        for observation in (self.first, self.second):
            op.accept_public_observation(copy.deepcopy(observation))
        self.assertIsNone(op.pending_own_discard)
        self.assertIsNone(op.cached_concealed_tiles)
        self.assertTrue(any(c.args[0] == "own_discard_reconciliation_unresolved"
            and c.kwargs.get("reason") == "called_discard_withdrawal_baseline_incompatible"
            for c in op.log.call_args_list))

    def test_ambiguous_new_call_and_expired_witness_are_rejected(self):
        first, second = copy.deepcopy(self.first), copy.deepcopy(self.second)
        for row in (first, second):
            next(o for o in row["opponentDiscards"] if o["seat"] == "north")["melds"] = [
                {"type": "pon", "tiles": ["7m"] * 3}]
        self.assertFalse(self.repaired(first=first, second=second).get("ownRiverWithdrawals"))
        empty = copy.deepcopy(self.first)
        empty["ownDiscards"], empty["ownDiscardsObserved"] = [], False
        pending = merge_public_observations(self.prior, empty, 0)
        late = copy.deepcopy(self.second)
        late["capturedAt"] = "2026-10-22T21:24:00.000000+00:00"
        self.assertFalse(merge_public_observations(pending, late, 0).get("_ownRiverCallWitnesses"))


if __name__ == "__main__":
    unittest.main()
