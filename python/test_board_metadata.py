import unittest
import tempfile
import importlib.util
import json
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from PIL import Image
from board_metadata import parse_board_tokens, recognize_board, recognize_remaining_count, recognize_right_score, recognize_score, recognize_round_counters, recognize_riichi_sticks, remap_seats, reconcile_riichi_metadata


class BoardMetadataTest(unittest.TestCase):
    def test_round_counter_ocr_requires_one_confident_numeric_reading_each(self):
        frame = Path(__file__).resolve().parents[1] / "test/fixtures/board-right-highlight-after-20261029.jpg"
        for readings, expected in [([("0", .99), ("0", .99)], (0, 0)),
                                   ([("1", .99), ("0", .99)], (1, 0)),
                                   ([("0", .99), ("1", .99)], (0, 1)),
                                   ([("0", .97)], None), ([("?", .99)], None),
                                   ([("0", .99), ("0", .97)], None),
                                   ([("0", .99), ("?", .99)], None)]:
            with self.subTest(readings=readings), patch("board_metadata.ocr_engine") as engine:
                engine.return_value.side_effect = [SimpleNamespace(txts=[text], scores=[confidence])
                                                   for text, confidence in readings]
                self.assertEqual(recognize_round_counters(frame), expected)

    @unittest.skipUnless(importlib.util.find_spec("rapidocr"), "rapidocr unavailable")
    def test_round_counter_occlusion_fails_closed(self):
        frame = Path(__file__).resolve().parents[1] / "test/fixtures/board-right-highlight-after-20261029.jpg"
        with Image.open(frame) as source:
            original = source.convert("RGB")
        with tempfile.TemporaryDirectory() as directory:
            for box in ((110, 132, 155, 178), (250, 132, 285, 178)):
                obscured = original.copy()
                obscured.paste((20, 20, 20), box)
                path = Path(directory) / "obscured.png"
                obscured.save(path)
                self.assertIsNone(recognize_round_counters(path))

    @unittest.skipUnless(importlib.util.find_spec("rapidocr"), "rapidocr unavailable")
    def test_actual_score_images_detect_changes_and_occlusion(self):
        root = Path(__file__).resolve().parents[1] / "test/fixtures"
        stable = root / "board-multipanel-after-20261029.jpg"
        different = root / "board-multipanel-different-score-20261029.jpg"
        boxes = {"own": (905, 456, 1015, 500), "right": (1031, 368, 1063, 471),
                 "opposite": (905, 345, 1015, 383), "left": (859, 371, 891, 474)}
        with tempfile.TemporaryDirectory() as directory:
            for position, box in boxes.items():
                with self.subTest(position=position):
                    self.assertEqual(recognize_score(stable, position), 25000)
                    self.assertNotEqual(recognize_score(different, position), 25000)
                    with Image.open(stable) as source:
                        obscured = source.convert("RGB")
                    obscured.paste((20, 20, 20), box)
                    path = Path(directory) / "obscured.png"
                    obscured.save(path)
                    self.assertIsNone(recognize_score(path, position))
    def test_individual_score_reads_fail_closed_for_all_seats(self):
        frame = Path(__file__).resolve().parents[1] / "test/fixtures/board-right-highlight-after-20261029.jpg"
        for position in ("own", "right", "opposite", "left"):
            for text, confidence, expected in [("25000", 0.99, 25000), ("24000", 0.99, 24000),
                                               ("25000", 0.97, None), ("2S000", 0.99, None),
                                               ("", 0.99, None)]:
                with self.subTest(position=position, text=text, confidence=confidence), patch(
                    "board_metadata.ocr_engine",
                    return_value=lambda *args, **kwargs: SimpleNamespace(txts=[text], scores=[confidence]),
                ):
                    self.assertEqual(recognize_score(frame, position), expected)
    def test_isolated_right_score_rejects_ambiguous_or_low_confidence(self):
        frame = Path(__file__).resolve().parents[1] / "test/fixtures/board-right-highlight-after-20261029.jpg"
        for text, confidence, expected in [("25000", 0.99, 25000), ("22500", 0.99, 22500),
                                           ("25000", 0.97, None), ("2S000", 0.99, None),
                                           ("0", 0.99, None)]:
            with self.subTest(text=text, confidence=confidence), patch(
                "board_metadata.ocr_engine",
                return_value=lambda *args, **kwargs: SimpleNamespace(txts=[text], scores=[confidence]),
            ):
                self.assertEqual(recognize_right_score(frame), expected)

    def test_isolated_wall_counter_requires_confident_bounded_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            frame = Path(directory) / "frame.png"
            Image.new("RGB", (1920, 1080)).save(frame)
            for text, confidence, expected in [("余01", 0.99, 1), ("余00", 0.99, 0),
                                               ("余70", 0.99, 70), ("余71", 0.99, None),
                                               ("余69", 0.97, None), ("69", 0.99, None)]:
                with self.subTest(text=text, confidence=confidence), patch(
                    "board_metadata.ocr_engine",
                    return_value=lambda *args, **kwargs: SimpleNamespace(txts=[text], scores=[confidence]),
                ):
                    self.assertEqual(recognize_remaining_count(frame), expected)
            Image.new("RGB", (100, 100)).save(frame)
            self.assertIsNone(recognize_remaining_count(frame))

    def declaration_fixture(self):
        return json.loads((Path(__file__).resolve().parents[1]
                           / "test/fixtures/riichi-declaration-transition-20261021.json").read_text())

    def test_real_occluded_red_stick_has_no_positive_pixel_label(self):
        frame = Path(__file__).resolve().parents[1] / "test/fixtures/riichi-stick-red-occluded-20261021.jpg"
        with Image.open(frame) as image:
            self.assertEqual(recognize_riichi_sticks(image, "north"), [])
        fixture = self.declaration_fixture()
        result = reconcile_riichi_metadata(fixture["before"], fixture["after"])
        self.assertEqual(result["riichiSeats"], ["west"])
        self.assertEqual(result["riichiScoreDeclarations"], ["west"])
        repeated = reconcile_riichi_metadata(result, fixture["after"])
        self.assertEqual(repeated["riichiSeats"], ["west"])
        self.assertEqual(repeated["riichiScoreDeclarations"], [])
        self.assertEqual(fixture["after"]["riichiSeats"], [])

    @unittest.skipUnless(importlib.util.find_spec("rapidocr"), "optional OCR dependencies not installed")
    def test_real_occluded_stick_score_and_counter_are_verified_without_ocr_relaxation(self):
        frame = Path(__file__).resolve().parents[1] / "test/fixtures/riichi-stick-red-occluded-20261021.jpg"
        recognized = recognize_board(frame)
        expected = self.declaration_fixture()["after"]
        self.assertTrue(recognized["verified"], recognized)
        for key in ("scores", "seat", "round", "honba", "riichiSticks"):
            self.assertEqual(recognized[key], expected[key])
        self.assertEqual(recognized["riichiSeats"], [])

    def test_score_payment_needs_matching_hand_and_verified_conserved_totals(self):
        fixture = self.declaration_fixture()
        before, after = fixture["before"], fixture["after"]
        invalid = [
            {**after, "seat": "east"}, {**after, "round": "east_2"}, {**after, "honba": 2},
            {**after, "verified": False}, {**after, "riichiSticks": 0},
            {**after, "riichiSticks": True}, {**after, "scores": None},
            {**after, "scores": {**after["scores"], "west": 16300.0}},
            {**after, "scores": {**after["scores"], "east": 33700, "south": 24000}},
        ]
        for current in invalid:
            with self.subTest(current=current):
                self.assertEqual(reconcile_riichi_metadata(before, current)["riichiScoreDeclarations"], [])
        self.assertEqual(reconcile_riichi_metadata({**before, "verified": False}, after)["riichiSeats"], [])

    def test_multiple_conserved_declarations_are_preserved_until_hand_changes(self):
        before = self.declaration_fixture()["before"]
        after = {**before, "scores": {**before["scores"], "west": 16300, "south": 24000}, "riichiSticks": 2}
        confirmed = reconcile_riichi_metadata(before, after)
        self.assertEqual(confirmed["riichiSeats"], ["south", "west"])
        self.assertEqual(confirmed["riichiScoreDeclarations"], ["south", "west"])
        for current in [{**after, "honba": 2}, {**after, "round": "east_2"},
                        {**before, "scores": {**before["scores"], "west": 16300, "east": 33700}}]:
            self.assertEqual(reconcile_riichi_metadata(confirmed, current)["riichiSeats"], [])

    def test_friend_room_that_contaminated_public_cache_is_not_a_verified_board(self):
        frame = Path(__file__).resolve().parents[1] / "artifacts/live/friend-room-public-cache-contamination-20260929.png"
        result = recognize_board(frame)
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "not_gameplay_screen")
        self.assertEqual(result["screenState"], "unknown")

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

    @unittest.skipUnless(importlib.util.find_spec("rapidocr"), "optional OCR dependencies not installed")
    def test_low_confidence_seat_wind_recovers_with_isolated_crop(self):
        frame = (Path(__file__).resolve().parents[1]
                 / "artifacts/live/board-seat-wind-low-confidence-20260929.jpg")
        result = recognize_board(frame)
        self.assertTrue(result["verified"], result)
        self.assertEqual(result["seat"], "east")
        self.assertEqual(result["round"], "east_2")
        self.assertEqual(result["remainingTiles"], 41)
        fallback = [token for token in result["tokens"]
                    if token.get("source") == "isolated_seat_wind_crop"]
        self.assertEqual(len(fallback), 1)
        self.assertEqual(fallback[0]["text"], "東")
        self.assertGreaterEqual(fallback[0]["confidence"], 0.98)

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
            self.assertEqual(recognize_board(path, sanma_compact_candidate=True)["reason"], "not_gameplay_screen")
            Image.new("RGB", (960, 540), "black").save(path)
            self.assertEqual(recognize_board(path)["reason"], "uncalibrated_viewport")
            self.assertEqual(recognize_board(path, sanma_compact_candidate=True)["reason"], "uncalibrated_viewport")

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

    def test_zero_score_real_frame_confidence_is_admitted_only_with_conservation(self):
        # room 74709, East 3: the opposite player was at 0 while one riichi
        # stick was on the table.  RapidOCR read the visual zero at 0.97473,
        # below the ordinary multi-digit threshold.  Its exact scoreboard
        # total is still required before this reading is usable by policy.
        tokens = self.tokens()
        values = ["24000", "27000", "0", "48000"]
        for token, value in zip(tokens[2:6], values):
            token["text"] = value
        tokens[4]["confidence"] = 0.97473
        tokens[7]["text"] = "1"
        result = parse_board_tokens(tokens)
        self.assertTrue(result["verified"], result)
        self.assertEqual(result["scores"], {"south": 24000, "west": 27000,
                                             "north": 0, "east": 48000})
        self.assertEqual(result["riichiSticks"], 1)

        tokens[4]["confidence"] = 0.949
        self.assertEqual(parse_board_tokens(tokens)["reason"], "four_scores_not_verified")
        tokens[4]["confidence"] = 0.97473
        tokens[2]["text"] = "25000"
        self.assertEqual(parse_board_tokens(tokens)["reason"],
                         "scores_and_riichi_sticks_total_mismatch")

    @unittest.skipUnless(importlib.util.find_spec("rapidocr"), "optional OCR dependencies not installed")
    def test_room_74709_zero_score_frame_recovers_with_conservation(self):
        frame = (Path(__file__).resolve().parents[1]
                 / "artifacts/friend-300-628c989-room74709-20261003/frames"
                 / "2026-10-02T15-51-12.615825+00-00.jpg")
        result = recognize_board(frame)
        self.assertTrue(result["verified"], result)
        self.assertEqual(result["seat"], "east")
        self.assertEqual(result["round"], "east_3")
        self.assertEqual(result["scores"], {"east": 24000, "south": 27000,
                                             "west": 0, "north": 48000})
        self.assertEqual(result["riichiSticks"], 1)

    def test_score_retry_does_not_accept_ambiguous_or_malformed_numbers(self):
        tokens = self.tokens()
        right = tokens[3]
        self.assertFalse(parse_board_tokens(tokens + [dict(right)])["verified"])
        for text in ["34O00", "34100pts", "1234567", "--1000"]:
            with self.subTest(text=text):
                changed = [dict(token) for token in tokens]
                changed[3]["text"] = text
                self.assertFalse(parse_board_tokens(changed)["verified"])
