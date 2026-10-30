import hashlib
import unittest
from unittest.mock import Mock, patch

from sanma_friend_discard_experiment import execute_friend_discard, execute_friend_draw_candidate


class FriendDiscardExperimentTests(unittest.TestCase):
    def setUp(self):
        self.frame = b"frame"
        self.page = Mock()
        self.page.screenshot.return_value = self.frame
        self.session = {"mode": "cpu_friend", "rules": "sanma", "clock": "300+0",
                        "actionDeadlineMs": 300000, "ranked": False, "cpuCount": 2, "roomVerified": True}
        self.point = {"x": 200, "y": 1000}
        self.observation = {"status": "candidate", "phase": "self_turn", "promptStatus": "none",
                            "handStatus": "candidate", "layoutStatus": "candidate",
                            "slots": [{"tile": "1m", **self.point}],
                            "frameSha256": hashlib.sha256(self.frame).hexdigest()}
        self.plan = {"scope": "offline_untrusted_sanma_discard_plan", "operationAuthorized": False,
                     "tile": "1m", "clickIndex": 0, "clickPoint": self.point}
        self.logs = []
        self.kwargs = dict(session=self.session, observation=self.observation, plan=self.plan,
                           layout={"viewport": {"width": 1920, "height": 1080}}, log=self.logs.append,
                           turn_started_monotonic=100, clock=lambda: 101)

    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_dispatches_selected_slot_and_records_unverified_result(self, send):
        send.return_value = {"lift": 48}
        result = execute_friend_discard(self.page, **self.kwargs)
        self.assertEqual(send.call_args.args[1], self.point)
        self.assertEqual([item["status"] for item in self.logs], ["attempted", "selection_confirmed"])
        self.assertEqual(result["result"], "discard_not_verified")

    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_ambiguous_prompts_ranked_changed_frame_and_expired_turn_are_blocked(self, send):
        variants = [dict(observation={**self.observation, "promptStatus": "unknown"}),
                    dict(session={**self.session, "ranked": True}),
                    dict(observation={**self.observation, "frameSha256": "0" * 64}),
                    dict(clock=lambda: 401),
                    dict(plan={**self.plan, "tile": "9m"})]
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                execute_friend_discard(self.page, **{**self.kwargs, **variant})
        send.assert_not_called()

    @patch("sanma_friend_discard_experiment.send_discard_click", side_effect=RuntimeError("selection uncertain"))
    def test_failed_selection_is_logged_and_propagated(self, send):
        with self.assertRaisesRegex(RuntimeError, "selection uncertain"):
            execute_friend_discard(self.page, **self.kwargs)
        self.assertEqual(self.logs[-1]["status"], "failed")
        self.assertEqual(self.logs[-1]["result"], "discard_not_verified")


if __name__ == "__main__":
    unittest.main()


class FriendDrawBridgeTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        self.operator = Mock()
        self.operator.args = SimpleNamespace(experimental_sanma_friend=True, rules="sanma", mode="force-auto",
                                             action_deadline_ms=300000, ranked_loop=False)
        self.operator.verified_friend_300_active = True
        self.operator.verified_friend_300_started_at = 100
        self.point = {"x": 1000, "y": 1000}
        digest = "a" * 64
        self.receipt = {"scope": "sanma_self_turn_observation", "digest": digest,
                        "freshness": {"status": "identical_pixels_candidate"},
                        "drawCandidate": {"status": "candidate", "digest": digest, "index": 13,
                                          "tile": "1m", "point": self.point},
                        "sourceObservation": {"digest": digest, "report": {"digest": digest,
                            "hand": {"status": "candidate", "value": {"safe": True, "turnReady": True, "tiles": ["1m"] * 14}},
                            "handGeometry": {"status": "candidate", "value": {"clickPoints": [self.point] * 14}},
                            "buttonRow": {"status": "candidate", "value": {"slots": [{"status": "empty_candidate"}] * 3}}}}}

    @patch("sanma_friend_discard_experiment.execute_friend_discard")
    def test_uses_draw_candidate_and_friend_config(self, execute):
        execute_friend_draw_candidate(self.operator, Mock(), self.receipt)
        self.assertEqual(execute.call_args.kwargs["plan"]["clickPoint"], self.point)
        self.assertEqual(execute.call_args.kwargs["plan"]["tile"], "1m")
        self.assertEqual(execute.call_args.kwargs["turn_started_monotonic"], 100)

    @patch("sanma_friend_discard_experiment.execute_friend_discard")
    def test_prompt_or_ranked_never_dispatches(self, execute):
        self.receipt["sourceObservation"]["report"]["buttonRow"]["value"]["slots"][0] = {"status": "unresolved"}
        with self.assertRaises(ValueError):
            execute_friend_draw_candidate(self.operator, Mock(), self.receipt)
        self.operator.args.ranked_loop = True
        with self.assertRaises(ValueError):
            execute_friend_draw_candidate(self.operator, Mock(), self.receipt)
        execute.assert_not_called()
