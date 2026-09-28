import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))
from score_closed_waits import score_waits, score_scenarios, convert


class ClosedWaitScoringTests(unittest.TestCase):
    def test_live_nobetan_dama_has_no_ordinary_ron_yaku(self):
        state = json.loads((ROOT / "artifacts/live/south4-riichi-replay-20260928.json").read_text(encoding="utf-8"))["state"]
        report = score_waits(state, "5m", ["6m", "9m"])
        for wait in ("6m", "9m"):
            rows = {(row["riichi"], row["tsumo"]): row for row in report["rows"] if row["wait"] == wait}
            self.assertEqual(rows[False, False]["error"], "no_yaku")
            self.assertEqual((rows[False, True]["han"], rows[False, True]["fu"]), (1, 30))
            self.assertEqual(rows[False, True]["cost"]["total"], 1500)
            self.assertEqual((rows[True, False]["han"], rows[True, False]["fu"]), (1, 40))
            self.assertEqual(rows[True, False]["cost"]["total"], 2000)
            self.assertEqual(rows[True, True]["cost"]["total"], 3000)
            self.assertEqual(rows[False, False]["scoreScenarios"], [])
            for key in ((False, True), (True, False), (True, True)):
                for scenario in rows[key]["scoreScenarios"]:
                    self.assertEqual(scenario["rankRange"], [2, 2])
                    self.assertEqual(sum(scenario["scores"].values()), sum(state["scores"].values()))
                    self.assertTrue(scenario["dealer_win"])

    def test_closed_pinfu_dama_is_valid_and_red_tiles_are_unique(self):
        state = {"hand": ["1m", "2m", "3m", "4m", "5m", "6m", "1p", "2p", "3p", "4s", "5s", "E", "E"],
                 "draw": "9p", "seat": "south", "round": "east_1"}
        # East pair is valued: replace it with a non-valued west pair.
        state["hand"][-2:] = ["W", "W"]
        row = score_waits(state, "9p", ["6s"])["rows"][0]
        self.assertIsNone(row["error"])
        self.assertIn("Pinfu", row["yaku"])
        self.assertEqual(len(set(convert(["0m", "5m", "5m", "5m"]))), 4)
        with self.assertRaises(ValueError):
            convert(["5m"] * 4)
        with self.assertRaises(ValueError):
            convert(["E"] * 5)

    def test_rejects_open_or_unknown_wind_input(self):
        with self.assertRaises(ValueError):
            score_waits({"openMelds": 1}, "1m", ["2m"])
        with self.assertRaises(ValueError):
            score_waits({"seat": "east", "round": "unknown"}, "1m", ["2m"])

    def test_nondealer_tsumo_and_tie_rank_are_not_assumed_final(self):
        state = {"seat": "south", "scores": {"east": 27000, "south": 24000, "west": 25000, "north": 24000}}
        scenario = score_scenarios(state, {"main": 1000, "additional": 500}, True)[0]
        self.assertEqual(scenario["scores"], {"east": 26000, "south": 26000, "west": 24500, "north": 23500})
        self.assertEqual(scenario["rankRange"], [1, 2])
        self.assertFalse(scenario["dealer_win"])
        self.assertEqual(score_scenarios({"seat": "south", "scores": {}}, {}, True), [])


if __name__ == "__main__":
    unittest.main()
