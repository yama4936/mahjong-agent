import unittest
import tempfile
import importlib.util
from pathlib import Path
from PIL import Image
from board_metadata import parse_board_tokens, recognize_board, recognize_riichi_sticks, remap_seats


class BoardMetadataTest(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("rapidocr"), "optional OCR dependencies not installed")
    def test_upside_down_opposite_score_recovers_without_lowering_threshold(self):
        frame = Path(__file__).resolve().parents[1] / "artifacts/live/board-score-opposite-low-confidence-20260928.png"
        for _ in range(2):
            result = recognize_board(frame)
            self.assertTrue(result["verified"], result)
            self.assertEqual(result["seat"], "south")
            self.assertEqual(result["round"], "east_1")
            self.assertEqual(result["scores"], dict.fromkeys(["east", "south", "west", "north"], 25000))
            self.assertEqual(result["honba"], 0)
            self.assertEqual(result["riichiSticks"], 0)
            self.assertEqual(result["remainingTiles"], 9)
            fallback = [token for token in result["tokens"]
                        if token.get("source") == "upright_opposite_score_crop"]
            self.assertEqual(len(fallback), 1)
            self.assertGreaterEqual(fallback[0]["confidence"], 0.98)

    @unittest.skipUnless(importlib.util.find_spec("rapidocr"), "optional OCR dependencies not installed")
    def test_vertical_right_score_recovers_with_point_conservation(self):
        frame = Path(__file__).resolve().parents[1] / "artifacts/live/board-score-right-low-confidence-20260928.jpg"
        for _ in range(2):
            result = recognize_board(frame)
            self.assertTrue(result["verified"], result)
            self.assertEqual(result["seat"], "north")
            self.assertEqual(result["round"], "south_1")
            self.assertEqual(result["scores"], {"north": 27500, "east": 40000,
                                                "south": 12500, "west": 19000})
            self.assertEqual(result["riichiSticks"], 1)
            self.assertEqual(result["honba"], 2)
            self.assertEqual(result["remainingTiles"], 54)
            fallback = [token for token in result["tokens"]
                        if token.get("source") == "upright_right_score_crop"]
            self.assertEqual(len(fallback), 1)
            self.assertGreaterEqual(fallback[0]["confidence"], 0.98)

    @unittest.skipUnless(importlib.util.find_spec("rapidocr"), "optional OCR dependencies not installed")
    def test_vertical_left_score_low_confidence_recovers_without_lowering_threshold(self):
        frame = Path(__file__).resolve().parents[1] / "artifacts/live/board-score-left-low-confidence-20260928.jpg"
        for _ in range(2):
            result = recognize_board(frame)
            self.assertTrue(result["verified"], result)
            self.assertEqual(result["seat"], "south")
            self.assertEqual(result["scores"], {"south": 25500, "west": 41000,
                                                "north": 13500, "east": 20000})
            self.assertEqual(result["remainingTiles"], 33)
            fallback = [token for token in result["tokens"]
                        if token.get("source") == "upright_left_score_crop"]
            self.assertEqual(len(fallback), 1)
            self.assertGreaterEqual(fallback[0]["confidence"], 0.98)

    @unittest.skipUnless(importlib.util.find_spec("rapidocr"), "optional OCR dependencies not installed")
    def test_four_digit_right_score_recovers_with_second_scale(self):
        frame = Path(__file__).resolve().parents[1] / "artifacts/live/board-score-right-four-digit-low-confidence-20260928.jpg"
        result = recognize_board(frame)
        self.assertTrue(result["verified"], result)
        self.assertEqual(result["seat"], "south")
        self.assertEqual(result["round"], "east_4")
        self.assertEqual(result["scores"], {"south": 43600, "west": 3400,
                                            "north": 14400, "east": 38600})
        self.assertEqual(result["riichiSticks"], 0)
        self.assertEqual(result["honba"], 0)
        self.assertEqual(result["remainingTiles"], 68)
        fallback = [token for token in result["tokens"]
                    if token.get("source") == "upright_right_score_crop"]
        self.assertEqual([token["cropWidth"] for token in fallback], [412, 328])
        self.assertLess(fallback[0]["confidence"], 0.98)
        self.assertEqual(fallback[1]["text"], "3400")
        self.assertGreaterEqual(fallback[1]["confidence"], 0.98)

    def test_verified_hud_stick_rotates_with_actual_own_wind(self):
        root = Path(__file__).resolve().parents[1]
        with Image.open(root / "artifacts/live/opponent-riichi-missed-20260928.jpg") as image:
            self.assertEqual(recognize_riichi_sticks(image, "west"), ["north"])
        with Image.open(root / "artifacts/live/red-ron-prompt-20260928.png") as image:
            self.assertEqual(recognize_riichi_sticks(image, "north"), ["north"])
        with Image.open(root / "artifacts/live/ron-next-round-score-20260928.png") as image:
            self.assertEqual(recognize_riichi_sticks(image, "west"), [])

    def test_left_hud_stick_real_frame_and_all_seat_rotations(self):
        root = Path(__file__).resolve().parents[1] / "artifacts/live"
        with Image.open(root / "left-river-three-man-border-20260928.png") as image:
            for own, left in [("east", "north"), ("south", "east"),
                              ("west", "south"), ("north", "west")]:
                with self.subTest(own=own):
                    self.assertEqual(recognize_riichi_sticks(image, own), [left])

    def test_opposite_hud_stick_real_frames_and_all_seat_rotations(self):
        root = Path(__file__).resolve().parents[1] / "artifacts/live"
        for filename in ["opposite-riichi-stick-missed-20260928.jpg",
                         "left-melds-chi-pon-20260928.jpg"]:
            with self.subTest(frame=filename), Image.open(root / filename) as image:
                for own, opposite in [("east", "west"), ("south", "north"),
                                      ("west", "east"), ("north", "south")]:
                    self.assertEqual(recognize_riichi_sticks(image, own), [opposite])

    def test_opposite_hud_stick_absent_real_frames(self):
        root = Path(__file__).resolve().parents[1] / "artifacts/live"
        for filename in ["ron-next-round-score-20260928.png",
                         "dora-two-man-clipped-20260928.jpg",
                         "adjacent-opposite-melds-20260928.jpg",
                         "south4-riichi-before-loss-20260928.jpg"]:
            with self.subTest(frame=filename), Image.open(root / filename) as image:
                self.assertEqual(recognize_riichi_sticks(image, "east"), [])

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

    def test_score_retry_does_not_accept_ambiguous_or_malformed_numbers(self):
        tokens = self.tokens()
        right = tokens[3]
        self.assertFalse(parse_board_tokens(tokens + [dict(right)])["verified"])
        for text in ["34O00", "34100pts", "1234567", "--1000"]:
            with self.subTest(text=text):
                changed = [dict(token) for token in tokens]
                changed[3]["text"] = text
                self.assertFalse(parse_board_tokens(changed)["verified"])
