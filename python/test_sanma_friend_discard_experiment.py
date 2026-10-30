import hashlib
import unittest
from unittest.mock import Mock, patch

from sanma_friend_discard_experiment import execute_friend_discard


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
