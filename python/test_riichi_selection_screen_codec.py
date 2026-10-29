"""Bounded regression for the native riichi-selection JPEG55 lobby collision."""
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image

from screen_state import (
    _distance, _has_bottom_tile_faces, _is_cherry_blossom_lobby,
    _is_reference_supported_riichi_selection, classify_screen,
)


FIXTURES = Path(__file__).resolve().parents[1] / "test/fixtures"
ROOT = FIXTURES.parents[1]
CONTROL = (1387, 798, 1497, 899)
ROW = (223, 930, 1454, 1065)
HUD = (800, 310, 1140, 535)


def opened(path):
    with Image.open(path) as image:
        return image.convert("RGB")


def encoded(image):
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class RiichiSelectionCodecTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = opened(FIXTURES / "riichi-selection-calibrated-match-20260920.jpg")
        cls.references = {"match:fixture": ("match", cls.reference)}
        cls.before = opened(FIXTURES / "riichi-selection-codec-before-jpeg55-20261030.jpg")
        cls.receipt = opened(FIXTURES / "riichi-selection-codec-receipt-20261030.jpg")

    def supported(self, image, references=None, maximum_distance=.16):
        return _is_reference_supported_riichi_selection(
            image, self.references if references is None else references, maximum_distance,
        )

    def test_native_jpeg55_and_original_receipt_reproduce_old_collision_and_recover(self):
        for image in (self.before, self.receipt):
            with self.subTest(frame="before" if image is self.before else "receipt"):
                self.assertEqual(image.size, (1920, 1080))
                self.assertFalse(_has_bottom_tile_faces(image))
                self.assertTrue(_is_cherry_blossom_lobby(image))
                self.assertTrue(self.supported(image))
                with patch("screen_state._is_reference_supported_riichi_selection", return_value=False):
                    self.assertEqual(classify_screen(encoded(image), self.references), ("lobby", 1.0))
                self.assertEqual(classify_screen(encoded(image), self.references), ("match", 1.0))

    def test_requires_native_size_and_a_same_size_match_reference(self):
        for references in ({}, {"lobby": ("lobby", self.reference)},
                           {"small": ("match", self.reference.resize((1280, 720)))}):
            with self.subTest(references=list(references)):
                self.assertFalse(self.supported(self.before, references))
        for image in (self.before.resize((1280, 720)), self.before.crop((0, 0, 1920, 900)),
                      self.before.resize((1919, 1080))):
            with self.subTest(size=image.size):
                self.assertFalse(self.supported(image))

    def test_requires_visible_riichi_return_control_not_gold_or_dark_alone(self):
        for fill in ((35, 50, 60), (220, 170, 90), (127, 127, 127)):
            image = self.before.copy()
            image.paste(fill, CONTROL)
            with self.subTest(fill=fill):
                self.assertFalse(self.supported(image))

    def test_requires_inked_muted_faces_not_a_uniform_gray_or_bright_strip(self):
        for fill in ((127, 127, 127), (220, 220, 220), (20, 30, 40)):
            image = self.before.copy()
            image.paste(fill, ROW)
            with self.subTest(fill=fill):
                self.assertFalse(self.supported(image))

    def test_independent_central_board_evidence_cannot_be_replaced_by_a_hand(self):
        image = self.before.copy()
        image.paste((127, 127, 127), HUD)
        # The hand and the whole-frame match remain, but the HUD does not.
        self.assertLess(_distance(image, self.reference), .085)
        self.assertGreater(_distance(image.crop(HUD), self.reference.crop(HUD)), .05)
        self.assertFalse(self.supported(image))

    def test_similar_hand_and_control_pasted_on_a_real_lobby_are_not_a_table(self):
        lobby = opened(FIXTURES / "black-recovered-lobby-20261021.png")
        for box in (ROW, CONTROL):
            lobby.paste(self.before.crop(box), box)
        self.assertFalse(self.supported(lobby))

    def test_honors_a_stricter_reference_distance(self):
        self.assertGreater(_distance(self.before, self.reference), .05)
        self.assertFalse(self.supported(self.before, maximum_distance=.05))

    def test_does_not_borrow_hud_and_global_evidence_from_different_references(self):
        good_global = self.reference.copy()
        good_global.paste((127, 127, 127), HUD)
        good_hud = Image.new("RGB", self.before.size, (190, 190, 190))
        good_hud.paste(self.reference.crop(HUD), HUD)
        self.assertLess(_distance(self.before, good_global), .085)
        self.assertGreater(_distance(self.before.crop(HUD), good_global.crop(HUD)), .05)
        self.assertFalse(self.supported(self.before, {
            "global": ("match", good_global), "hud": ("match", good_hud),
        }))

    def test_real_lobby_away_results_and_empty_frames_do_not_gain_match_evidence(self):
        paths = [FIXTURES / "black-recovered-lobby-20261021.png",
                 FIXTURES / "startup-away-20261029.jpg",
                 FIXTURES / "round-terminal-recovery-away-20261023.png",
                 ROOT / "artifacts/live/draw-tenpai-result-20260928.png",
                 ROOT / "artifacts/live/south4-loss-result-20260928.png"]
        images = [opened(path) for path in paths]
        images += [Image.new("RGB", (1920, 1080), fill) for fill in ("black", "white", (127, 127, 127))]
        for index, image in enumerate(images):
            with self.subTest(index=index):
                self.assertFalse(self.supported(image))
        self.assertEqual(classify_screen(paths[0], self.references), ("lobby", 1.0))
        # The pre-existing broad tile-face path calls this away frame "match".
        # This codec repair deliberately does not redefine away classification.
        self.assertTrue(_has_bottom_tile_faces(images[1]))
        self.assertEqual(classify_screen(paths[1], self.references), ("match", 1.0))

    def test_rejected_control_performs_no_new_reference_comparisons(self):
        for image in (opened(FIXTURES / "black-recovered-lobby-20261021.png"),
                      opened(FIXTURES / "startup-away-20261029.jpg")):
            with patch("screen_state._distance", side_effect=AssertionError("reference path must be lazy")):
                self.assertFalse(self.supported(image))

    def test_ordinary_tile_face_fast_path_does_not_call_new_helper(self):
        image = opened(FIXTURES / "startup-away-20261029.jpg")
        self.assertTrue(_has_bottom_tile_faces(image))
        with patch("screen_state._is_reference_supported_riichi_selection",
                   side_effect=AssertionError("ordinary tile-face path changed")):
            self.assertEqual(classify_screen(encoded(image), self.references), ("match", 1.0))


if __name__ == "__main__":
    unittest.main()
