import unittest
from sanma_closed_experiment import score_sanma_closed_tsumo, ordinary_basic_points

class SanmaClosedTests(unittest.TestCase):
    def setUp(self):
        self.case = {"hand": ["9m", "9m", "0p", "5p", "5p", "6p", "7p", "8p", "2s", "3s", "4s", "S", "S", "S"], "winner": "3s", "seat": "west", "roundWind": "east", "riichi": True, "indicators": ["W"], "uraIndicators": ["N"], "kita": 1, "honba": 0, "deposits": 0, "pao": False, "melds": [], "tsumoLoss": True, "situationalYakuExcluded": True}

    def test_recorded_east_one_hand_excludes_two_deposits(self):
        result = score_sanma_closed_tsumo(self.case)
        self.assertEqual((result["baseHan"], result["extraHan"], result["han"], result["fu"], result["basicPoints"]), (3, 2, 5, 40, 2000))
        self.assertEqual(set(result["baseYaku"]), {"Riichi", "Menzen Tsumo", "Aka Dora 1"})

    def test_red_winner_is_selected_as_the_physical_red_copy(self):
        from unittest.mock import patch
        from mahjong.constants import AKA_DORAS
        from sanma_closed_experiment import HandCalculator
        original = HandCalculator.estimate_hand_value
        calls = []
        def capture(tiles, winner, **kwargs):
            calls.append(winner)
            return original(tiles, winner, **kwargs)
        with patch.object(HandCalculator, "estimate_hand_value", side_effect=capture):
            score_sanma_closed_tsumo({**self.case, "winner": "0p"})
            score_sanma_closed_tsumo({**self.case, "winner": "5p"})
        self.assertIn(calls[0], AKA_DORAS)
        self.assertNotIn(calls[1], AKA_DORAS)

    def test_multiple_north_west_and_ura_are_counted_once(self):
        result = score_sanma_closed_tsumo({**self.case, "kita": 2, "indicators": ["W"], "uraIndicators": ["W"]})
        self.assertEqual((result["baseHan"], result["extraHan"], result["han"]), (3, 6, 9))
        self.assertNotIn("Dora 6", result["baseYaku"])
        result = score_sanma_closed_tsumo({**self.case, "uraIndicators": ["4p"]})
        self.assertEqual(result["extraHan"], 5)  # two for extracted north, three hand fives incl. red
        hand = ["1p", "2p", "3p", "4p", "5p", "6p", "1s", "2s", "3s", "4s", "5s", "6s", "N", "N"]
        result = score_sanma_closed_tsumo({**self.case, "hand": hand, "winner": "6s", "indicators": ["P"], "uraIndicators": ["W"]})
        self.assertEqual((result["fu"], result["extraHan"]), (20, 4))  # two hand norths + extracted north twice

    def test_seven_pairs_25_fu(self):
        hand = ["1m", "1m", "9m", "9m", "1p", "1p", "3p", "3p", "5p", "5p", "7s", "7s", "9s", "9s"]
        result = score_sanma_closed_tsumo({**self.case, "hand": hand, "winner": "9s", "indicators": ["P"], "uraIndicators": ["C"], "kita": 0})
        self.assertEqual(result["fu"], 25)
        self.assertEqual(result["han"], 4)
        self.assertEqual(result["basicPoints"], 1600)

    def test_yakuman_counted_yakuman_and_bad_tiles_rejected(self):
        kokushi = ["1m", "9m", "1p", "9p", "1s", "9s", "E", "S", "W", "N", "P", "F", "C", "1m"]
        with self.assertRaises(ValueError): score_sanma_closed_tsumo({**self.case, "hand": kokushi, "winner": "1m", "indicators": ["4p"], "uraIndicators": ["6p"], "kita": 0})
        seven_pairs = ["1p", "1p", "2p", "2p", "3p", "3p", "4p", "4p", "5p", "5p", "6p", "6p", "7p", "7p"]
        with self.assertRaisesRegex(ValueError, "yakuman"): score_sanma_closed_tsumo({**self.case, "hand": seven_pairs, "winner": "7p", "kita": 3})
        for replacement in ["0p", "10p", "2m"]:
            bad = self.case["hand"][:]
            bad[0] = replacement
            with self.subTest(replacement=replacement):
                with self.assertRaises(ValueError): score_sanma_closed_tsumo({**self.case, "hand": bad})

    def test_limit_boundaries(self):
        self.assertEqual([ordinary_basic_points(h, 30) for h in [3, 4, 5, 6, 8, 11]], [960, 1920, 2000, 3000, 4000, 6000])
        with self.assertRaises(ValueError): ordinary_basic_points(13, 30)

    def test_missing_and_unverified_conditions_rejected(self):
        for field, value in [("uraIndicators", []), ("indicators", ["1m"]), ("honba", 1), ("deposits", 1), ("kita", 5), ("pao", True), ("tsumoLoss", False), ("melds", ["pon"]), ("winner", "1s")]:
            with self.subTest(field=field):
                with self.assertRaises(ValueError): score_sanma_closed_tsumo({**self.case, field: value})
        with self.assertRaises(ValueError): score_sanma_closed_tsumo({**self.case, "hand": self.case["hand"][:-1] + ["2m"]})
        with self.assertRaises(ValueError): score_sanma_closed_tsumo({**self.case, "uraIndicators": ["N"], "kita": 4})
