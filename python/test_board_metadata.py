import unittest
from board_metadata import parse_board_tokens


class BoardMetadataTest(unittest.TestCase):
    def tokens(self):
        return [{"text": text, "x": x, "y": y, "confidence": 0.999}
                for text, x, y in [("南", 824, 514), ("東4局", 960, 405),
                                  ("19500", 960, 482), ("34100", 1047, 419),
                                  ("28500", 958, 364), ("15900", 876, 423),
                                  ("余60", 959, 443)]]

    def test_relative_scores_rotate_with_verified_seat(self):
        result = parse_board_tokens(self.tokens())
        self.assertTrue(result["verified"])
        self.assertEqual(result["seat"], "south")
        self.assertEqual(result["round"], "east_4")
        self.assertEqual(result["scores"], {"south": 19500, "west": 34100,
                                            "north": 28500, "east": 15900})
        self.assertEqual(result["remainingTiles"], 60)

    def test_missing_ambiguous_or_low_confidence_fields_are_rejected(self):
        tokens = self.tokens()
        self.assertFalse(parse_board_tokens(tokens[1:])["verified"])
        self.assertFalse(parse_board_tokens(tokens + [tokens[0]])["verified"])
        tokens[2]["confidence"] = 0.8
        self.assertFalse(parse_board_tokens(tokens)["verified"])
