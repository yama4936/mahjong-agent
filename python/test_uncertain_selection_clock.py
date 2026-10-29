import argparse
import unittest
from unittest.mock import Mock

from auto_operator import PythonAutoOperator


class UncertainSelectionClockTest(unittest.TestCase):
    def setUp(self):
        self.op = PythonAutoOperator.__new__(PythonAutoOperator)
        self.op.args = argparse.Namespace(action_deadline_ms=300000)
        self.op.log = Mock()
        self.op.action_evidence_started_at = 10.0
        self.op.action_evidence_last_seen_at = 11.0
        self.op.action_evidence_kind = "discard"
        self.op.action_evidence_generation = 2
        self.op.screencast_draw_occupied = True
        self.op.selection_uncertainty_latch = {
            "drawGeneration": 35, "ownDiscards": ["1m"],
            "abortedAt": "2026-10-28T07:05:06+00:00",
        }

    def observation(self, seconds, river=("1m", "8s"), observed=True):
        return {"capturedAt": f"2026-10-28T07:05:{seconds:02d}+00:00",
                "ownDiscards": list(river), "ownDiscardsObserved": observed}

    def test_new_draw_requires_two_later_independent_river_observations(self):
        self.assertFalse(self.op.rearm_uncertain_selection_clock(36, 30.0))
        self.op.observe_uncertain_selection_river(self.observation(27))
        self.assertFalse(self.op.rearm_uncertain_selection_clock(36, 31.0))
        self.op.observe_uncertain_selection_river(self.observation(28))
        self.assertTrue(self.op.rearm_uncertain_selection_clock(36, 32.0))
        # The first draw receipt, not the later confirmation, bounds freshness.
        self.assertEqual(self.op.action_evidence_started_at, 30.0)
        self.assertEqual(self.op.action_evidence_generation, 36)

    def test_untrusted_river_or_false_draw_cannot_refresh_the_clock(self):
        cases = [
            (self.observation(5), self.observation(6)),
            (self.observation(27, observed=False), self.observation(28, observed=False)),
            (self.observation(27), self.observation(27)),
            (self.observation(27), self.observation(28, river=("1m", "7s"))),
            (self.observation(27, river=("9m", "8s")), self.observation(28, river=("9m", "8s"))),
        ]
        for first, second in cases:
            with self.subTest(first=first, second=second):
                self.setUp()
                self.op.observe_uncertain_selection_river(first)
                self.op.observe_uncertain_selection_river(second)
                self.assertFalse(self.op.rearm_uncertain_selection_clock(36, 30.0))
                self.assertEqual(self.op.action_evidence_started_at, 10.0)
        self.setUp()
        self.op.observe_uncertain_selection_river(self.observation(27))
        self.op.observe_uncertain_selection_river(self.observation(28))
        self.assertFalse(self.op.rearm_uncertain_selection_clock(35, 30.0))
        self.op.screencast_draw_occupied = None
        self.assertFalse(self.op.rearm_uncertain_selection_clock(36, 30.0))
        self.assertEqual(self.op.action_evidence_started_at, 10.0)

    def test_withdrawn_candidate_cannot_refresh_clock(self):
        self.op.observe_uncertain_selection_river(self.observation(27))
        self.op.observe_uncertain_selection_river(self.observation(28))
        self.op.observe_uncertain_selection_river(self.observation(29, river=("1m",)))
        self.assertFalse(self.op.rearm_uncertain_selection_clock(36, 30.0))
        self.assertEqual(self.op.action_evidence_started_at, 10.0)

    def test_new_clock_is_not_reset_on_repeated_draw_frames(self):
        self.assertFalse(self.op.rearm_uncertain_selection_clock(36, 30.0))
        self.assertFalse(self.op.rearm_uncertain_selection_clock(37, 40.0))
        self.op.observe_uncertain_selection_river(self.observation(27))
        self.op.observe_uncertain_selection_river(self.observation(28))
        self.assertTrue(self.op.rearm_uncertain_selection_clock(37, 40.0))
        self.assertEqual(self.op.action_evidence_started_at, 30.0)

    def test_draw_generation_animation_cannot_rearm_or_extend_deadline(self):
        # Occupancy can toggle during an animation.  Even several resulting
        # generations are not an own-river receipt and must not enable clicks.
        self.assertFalse(self.op.rearm_uncertain_selection_clock(37, 40.0))
        self.assertEqual(self.op.action_evidence_started_at, 10.0)

    def test_unconfirmed_later_draw_stops_after_grace_from_observation(self):
        # The receipt time is delivery/observation time, not the unknown game
        # turn-start time.  It only bounds a no-click grace period.
        self.assertFalse(self.op.rearm_uncertain_selection_clock(36, 30.0))
        self.assertFalse(self.op.selection_uncertainty_stop_due(32.99))
        self.assertTrue(self.op.selection_uncertainty_stop_due(33.0))

    def test_river_diagnostics_distinguish_failure_modes_without_tile_values(self):
        observations = [
            self.observation(27, observed=False),
            self.observation(5),
            self.observation(27, river=("1m",)),
            self.observation(27, river=("9m", "8s")),
            self.observation(27),
            self.observation(27),
            self.observation(28, river=("1m", "7s")),
            self.observation(29, river=("1m", "7s")),
        ]
        for observation in observations:
            self.op.observe_uncertain_selection_river(observation)
        calls = self.op.log.call_args_list
        self.assertEqual([call.kwargs["reason"] for call in calls], [
            "river_not_observed", "capture_not_after_abort", "no_extension",
            "baseline_prefix_mismatch", "candidate_started", "candidate_too_soon",
            "candidate_changed", "confirmed",
        ])
        for call in calls:
            self.assertEqual(call.args, ("selection_uncertainty_river_observation",))
            self.assertNotIn("river", call.kwargs)
            self.assertNotIn("ownDiscards", call.kwargs)


if __name__ == "__main__":
    unittest.main()
