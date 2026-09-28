import unittest
import tempfile
import importlib.util
from pathlib import Path
from PIL import Image
from board_metadata import parse_board_tokens, recognize_board, remap_seats


class BoardMetadataTest(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("rapidocr"), "optional OCR dependencies not installed")
    def test_consecutive_real_ocr_calls_reset_detection_after_counter_reads(self):
        frame = Path(__file__).resolve().parents[1] / "artifacts/live/board-metadata-east4-south-20260928.png"
        for _ in range(2):
            result = recognize_board(frame)
            self.assertTrue(result["verified"], result)
            self.assertEqual(result["seat"], "south")
            self.assertEqual(result["riichiSticks"], 2)
            self.assertEqual(result["honba"], 1)

    def test_seat_rotation_preserves_relative_rivers_and_meld_sources(self):
        source = {"opponentDiscards": [{"seat": "south", "discards": ["P"],
                  "melds": [{"fromSeat": "west"}]}]}
        target = remap_seats(source, "east", "west")
        self.assertEqual(target["opponentDiscards"][0]["seat"], "north")
        self.assertEqual(target["opponentDiscards"][0]["melds"][0]["fromSeat"], "east")
        self.assertEqual(source["opponentDiscards"][0]["seat"], "south")
        self.assertIsNone(remap_seats(None, "east", "south"))
    def test_non_gameplay_and_wrong_viewport_fail_before_loading_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "screen.png"
            Image.new("RGB", (1920, 1080), "black").save(path)
            self.assertEqual(recognize_board(path)["reason"], "not_gameplay_screen")
            Image.new("RGB", (960, 540), "black").save(path)
            self.assertEqual(recognize_board(path)["reason"], "uncalibrated_viewport")

    def tokens(self):
        return [{"text": text, "x": x, "y": y, "confidence": 0.999}
                for text, x, y in [("南", 824, 514), ("東4局", 960, 405),
                                  ("19500", 960, 482), ("34100", 1047, 419),
                                  ("28500", 958, 364), ("15900", 876, 423),
                                  ("余60", 959, 443), ("2", 132, 155), ("1", 268, 155)]]

    def test_relative_scores_rotate_with_verified_seat(self):
        result = parse_board_tokens(self.tokens())
        self.assertTrue(result["verified"])
        self.assertEqual(result["seat"], "south")
        self.assertEqual(result["round"], "east_4")
        self.assertEqual(result["scores"], {"south": 19500, "west": 34100,
                                            "north": 28500, "east": 15900})
        self.assertEqual(result["remainingTiles"], 60)
        self.assertEqual(result["honba"], 1)
        self.assertEqual(result["riichiSticks"], 2)

    def test_missing_ambiguous_or_low_confidence_fields_are_rejected(self):
        tokens = self.tokens()
        self.assertFalse(parse_board_tokens(tokens[1:])["verified"])
        self.assertFalse(parse_board_tokens(tokens + [tokens[0]])["verified"])
        self.assertFalse(parse_board_tokens(tokens[:-1])["verified"])
        tokens[2]["confidence"] = 0.8
        self.assertFalse(parse_board_tokens(tokens)["verified"])

    def test_high_confidence_digit_error_is_rejected_by_point_conservation(self):
        tokens = self.tokens()
        tokens[2]["text"] = "29500"
        result = parse_board_tokens(tokens)
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "scores_and_riichi_sticks_total_mismatch")
        self.assertTrue(parse_board_tokens(tokens, expected_total_points=110000)["verified"])
