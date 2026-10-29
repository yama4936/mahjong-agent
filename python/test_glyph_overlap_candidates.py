from pathlib import Path
import random
import unittest

from PIL import Image, ImageDraw

from auto_operator import glyph_overlap_candidates, raised_glyph_overlap_confirmation


def legacy_candidates(baseline, after_mask, face):
    """Independent pre-optimization pixel oracle; retain every candidate."""
    baseline_pixels = list(baseline.getdata())
    glyph_pixels = sum(value > 0 for value in baseline_pixels)
    if glyph_pixels == 0:
        return []
    left, top = int(face["x"]), int(face["y"])
    right, bottom = int(face["x"] + face["width"]), int(face["y"] + face["height"])
    result = []
    for lift in range(8, 81):
        shifted_pixels = list(after_mask.crop((left, top - lift, right, bottom - lift)).getdata())
        overlap = sum(a > 0 and b > 0 for a, b in zip(baseline_pixels, shifted_pixels))
        density = sum(value > 0 for value in shifted_pixels)
        result.append((overlap / glyph_pixels, density / glyph_pixels, lift))
    return result


class GlyphOverlapCandidatesTest(unittest.TestCase):
    def assert_all_candidates_equal(self, baseline, after_mask, face):
        actual = glyph_overlap_candidates(baseline, after_mask, face)
        self.assertEqual(actual, legacy_candidates(baseline, after_mask, face))
        if actual:
            self.assertEqual([entry[2] for entry in actual], list(range(8, 81)))
        return actual

    def test_real_receipts_unchanged_neighbours_and_occluded_masks(self):
        root = Path(__file__).resolve().parents[1]
        fixtures = root / "test/fixtures"
        cases = [
            ("7p", "20261029.png", 981, 926, 93, 146),
            ("green", "20261028.jpg", 1486, 926, 92, 146),
            ("8s-sparkle", "20261028.png", 1486, 926, 92, 146),
            ("9m-inset", "20261030.png", 1486, 921, 92, 151),
        ]
        lookup = [255 if value < 120 else 0 for value in range(256)]
        for name, suffix, x, y, width, height in cases:
            before_path = fixtures / f"selection-{name}-before-{suffix}"
            receipt_kind = "receipt" if name == "7p" else "lift"
            after_path = fixtures / f"selection-{name}-{receipt_kind}-{suffix}"
            with Image.open(before_path) as image:
                before = image.convert("L").point(lookup)
            with Image.open(after_path) as image:
                after = image.convert("L").point(lookup)
            face = {"x": x + 10, "y": y + 10, "width": width - 20, "height": height - 38}
            bounds = (int(face["x"]), int(face["y"]),
                      int(face["x"] + face["width"]), int(face["y"] + face["height"]))
            baseline = before.crop(bounds)
            for variant, mask in (("receipt", after), ("unchanged", before)):
                with self.subTest(fixture=name, variant=variant):
                    self.assert_all_candidates_equal(baseline, mask, face)
            neighbour = {**face, "x": face["x"] - 95}
            neighbour_before = before.crop((bounds[0] - 95, bounds[1], bounds[2] - 95, bounds[3]))
            with self.subTest(fixture=name, variant="neighbour"):
                self.assert_all_candidates_equal(neighbour_before, after, neighbour)
            # A missing or broadly darkened glyph must retain exactly the
            # old scores, including densities above the admission threshold.
            for color in (0, 255):
                occluded = after.copy()
                ImageDraw.Draw(occluded).rectangle((bounds[0], bounds[1] - 80,
                                                    bounds[2], bounds[3]), fill=color)
                with self.subTest(fixture=name, variant="occluded", color=color):
                    self.assert_all_candidates_equal(baseline, occluded, face)

    def test_binary_and_nonbinary_masks_preserve_all_scores_and_ties(self):
        rng = random.Random(20261030)
        face = {"x": 3, "y": 88, "width": 17, "height": 13}
        for levels in ((0, 255), (0, 1, 17, 128, 255)):
            baseline = Image.new("L", (17, 13))
            baseline.putdata([rng.choice(levels) for _ in range(17 * 13)])
            receipt = Image.new("L", (28, 110))
            receipt.putdata([rng.choice(levels) for _ in range(28 * 110)])
            self.assert_all_candidates_equal(baseline, receipt, face)
        dense = Image.new("L", (17, 13), 255)
        ties = self.assert_all_candidates_equal(dense, Image.new("L", (28, 110), 255), face)
        self.assertEqual(max(ties), (1.0, 1.0, 80))
        self.assertIsNone(raised_glyph_overlap_confirmation(
            dense, Image.new("L", (28, 110), 255), face, {"x": 11, "y": 94}))

    def test_empty_glyph_and_out_of_frame_padding_preserve_old_behavior(self):
        empty = Image.new("L", (7, 9))
        receipt = Image.new("L", (20, 30), 255)
        face = {"x": -2, "y": 4, "width": 7, "height": 9}
        self.assertEqual(self.assert_all_candidates_equal(empty, receipt, face), [])
        self.assertIsNone(raised_glyph_overlap_confirmation(empty, receipt, face, {"x": 1, "y": 8}))
        self.assert_all_candidates_equal(Image.new("L", (7, 9), 255), receipt, face)

    def test_extreme_search_offsets_are_retained(self):
        baseline = Image.new("L", (17, 13))
        ImageDraw.Draw(baseline).rectangle((2, 4, 11, 8), fill=255)
        face = {"x": 3, "y": 88, "width": 17, "height": 13}
        for lift in (8, 80):
            receipt = Image.new("L", (28, 110))
            receipt.paste(baseline, (3, 88 - lift))
            candidates = self.assert_all_candidates_equal(baseline, receipt, face)
            self.assertEqual(max(candidates)[2], lift)


if __name__ == "__main__":
    unittest.main()
