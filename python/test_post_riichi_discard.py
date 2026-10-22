"""Locked hands must never send a concealed-tile click after riichi."""
import argparse
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from auto_operator import PythonAutoOperator, RetryableSafetyAbort, require_post_riichi_draw_click


class PostRiichiDiscardTest(unittest.TestCase):
    def setUp(self):
        self.layout = json.loads((Path(__file__).resolve().parents[1] /
                                  "config/layout-300-regression.json").read_text())
        self.hand = ["1m", "1m", "1m", "5m", "6m", "7m", "3p", "4p",
                     "4s", "4s", "0s", "5s", "5s"]
        self.evaluation = {
            "state": {"phase": "self_turn", "riichiDeclared": True,
                      "openMelds": 0, "hand": self.hand, "draw": "6s"},
            "recognition": {"tiles": [*self.hand, "6s"]},
            "decision": {"selectedAction": {"action": "discard", "tile": "6s"}},
            "clickIndex": 13, "clickPoint": self.layout["clickPoints"][13],
        }

    def validate(self, evaluation=None, established=False):
        ev = evaluation or self.evaluation
        require_post_riichi_draw_click(ev, ev["decision"]["selectedAction"], self.layout,
                                      ev["clickIndex"], ev.get("clickPoint"), established)

    def test_live_illegal_4p_attempt_is_rejected_before_mouse_or_frame_work(self):
        ev = copy.deepcopy(self.evaluation)
        ev["decision"]["selectedAction"]["tile"] = "4p"
        ev["clickIndex"] = 7
        ev["clickPoint"] = self.layout["clickPoints"][7]
        op = PythonAutoOperator.__new__(PythonAutoOperator)
        op.args = argparse.Namespace(mode="force-auto", allow_local_discard=False)
        op.layout = self.layout
        page = Mock()
        with self.assertRaisesRegex(RetryableSafetyAbort, "post-riichi"):
            op.execute(page, ev)
        self.assertEqual(page.mock_calls, [])

    def test_duplicate_and_red_draws_require_the_last_physical_slot(self):
        for draw in ["6s", "1m", "0s", "5s"]:
            with self.subTest(draw=draw):
                ev = copy.deepcopy(self.evaluation)
                ev["state"]["draw"] = draw
                ev["recognition"]["tiles"][-1] = draw
                ev["decision"]["selectedAction"]["tile"] = draw
                self.validate(ev)
                ev["clickIndex"] = 0
                with self.assertRaises(RetryableSafetyAbort):
                    self.validate(ev)
                ev["clickIndex"] = 13
                ev["clickPoint"] = self.layout["clickPoints"][0]
                with self.assertRaises(RetryableSafetyAbort):
                    self.validate(ev)

    def test_red_and_normal_five_are_not_interchangeable(self):
        for draw, selected in [("0s", "5s"), ("5s", "0s")]:
            ev = copy.deepcopy(self.evaluation)
            ev["state"]["draw"] = draw
            ev["recognition"]["tiles"][-1] = draw
            ev["decision"]["selectedAction"]["tile"] = selected
            with self.assertRaises(RetryableSafetyAbort):
                self.validate(ev)

    def test_missing_draw_stale_row_and_wrong_phase_are_rejected(self):
        changes = [("draw", None), ("hand", self.hand[:-1]),
                   ("phase", "reaction"), ("openMelds", 1), ("riichiDeclared", False)]
        for key, value in changes:
            with self.subTest(key=key):
                ev = copy.deepcopy(self.evaluation)
                ev["state"][key] = value
                with self.assertRaises(RetryableSafetyAbort):
                    self.validate(ev, established=True)
        ev = copy.deepcopy(self.evaluation)
        ev["recognition"]["tiles"][-1] = "9s"
        with self.assertRaises(RetryableSafetyAbort):
            self.validate(ev)

    def test_win_and_pass_buttons_and_initial_riichi_are_unaffected(self):
        for action in ["tsumo", "ron", "pass", "ankan"]:
            ev = copy.deepcopy(self.evaluation)
            ev["decision"]["selectedAction"] = {"action": action}
            self.validate(ev)
        ev = copy.deepcopy(self.evaluation)
        ev["state"]["riichiDeclared"] = False
        ev["decision"]["selectedAction"] = {"action": "riichi", "tile": "4p"}
        self.validate(ev)

    def test_draw_after_closed_kan_uses_compact_draw_geometry(self):
        from auto_operator import open_hand_draw_slot
        ev = copy.deepcopy(self.evaluation)
        ev["state"]["openMelds"] = 1
        ev["state"]["hand"] = self.hand[:10]
        ev["recognition"]["tiles"] = [*self.hand[:10], "6s"]
        ev["clickIndex"] = 10
        slot = open_hand_draw_slot(self.layout, 1)
        ev["clickPoint"] = {"x": slot["x"] + slot["width"] / 2,
                            "y": slot["y"] + slot["height"] / 2}
        self.validate(ev)


if __name__ == "__main__":
    unittest.main()
