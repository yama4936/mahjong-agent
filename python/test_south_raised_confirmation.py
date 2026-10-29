"""Native South lift regression: timer occlusion plus mixed PNG/JPEG edges."""
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw, ImageStat

from auto_operator import glyph_overlap_candidates, load_json, raised_glyph_overlap_confirmation
from auto_operator import raised_tile_confirmation_point


class SouthRaisedConfirmationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        fixtures = cls.root / "test/fixtures"
        cls.meta = load_json(fixtures / "south-riichi-raised-20261030.json")
        cls.layout = load_json(cls.root / "config/layout-runtime.json")
        cls.point = cls.meta["clickPoint"]
        cls.before = cls.reconstruct(fixtures / cls.meta["before"])
        cls.receipt = cls.reconstruct(fixtures / cls.meta["receipt"])

    @staticmethod
    def png(image):
        encoded = io.BytesIO()
        image.save(encoded, format="PNG")
        return encoded.getvalue()

    @classmethod
    def reconstruct(cls, path):
        viewport, crop = cls.meta["viewport"], cls.meta["nativeCrop"]
        canvas = Image.new("RGB", (viewport["width"], viewport["height"]), (25, 55, 85))
        with Image.open(path) as image:
            if image.size != (crop["width"], crop["height"]):
                raise AssertionError("native fixture dimensions changed")
            canvas.paste(image.convert("RGB"), (crop["x"], crop["y"]))
        return cls.png(canvas)

    def confirm(self, receipt=None, before=None, index=12):
        point = self.point if index == 12 else self.layout["clickPoints"][index]
        return raised_tile_confirmation_point(before or self.before, receipt or self.receipt,
                                              self.layout, index, point, 1.5)

    def altered(self, rectangle, color):
        image = Image.open(io.BytesIO(self.receipt)).convert("RGB")
        ImageDraw.Draw(image).rectangle(rectangle, fill=color)
        return self.png(image)

    def test_native_south_lift_adds_independent_rim_and_neighbour_proof(self):
        with patch("auto_operator.raised_rim_cluster_glyph_confirmation", return_value=None):
            self.assertIsNone(self.confirm())
        result = self.confirm()
        self.assertEqual((result["x"], result["y"], result["lift"]), (1407, 948.5, 48))
        self.assertEqual(result["verification"], "translated_rim_unique_glyph_cluster_and_stable_neighbour")
        self.assertEqual(result["rimLift"], 47)
        self.assertAlmostEqual(result["glyphOverlap"], .9897091722595078)
        self.assertAlmostEqual(result["rawFaceStructureDelta"], 2.0403146509341203)
        self.assertEqual(result["faceStructureDelta"], 2.04)
        self.assertLess(result["adjacentGlyphMargin"], .07)
        self.assertGreater(result["distantGlyphMargin"], .19)
        self.assertLess(result["neighbourFaceStructureDelta"], 1.5)

    def test_adjacent_pixel_peaks_are_one_position_but_distant_peaks_remain_separate(self):
        lookup = [255 if value < 120 else 0 for value in range(256)]
        before = Image.open(io.BytesIO(self.before)).convert("L").point(lookup)
        after = Image.open(io.BytesIO(self.receipt)).convert("L").point(lookup)
        face = {"x": 1371, "y": 931, "width": 72, "height": 113}
        baseline = before.crop((1371, 931, 1443, 1044))
        candidates = sorted(glyph_overlap_candidates(baseline, after, face), reverse=True)
        self.assertEqual((candidates[0][2], candidates[1][2]), (48, 47))
        self.assertLess(candidates[0][0] - candidates[1][0], .07)
        self.assertGreater(candidates[0][0] - max(score for score, _, lift in candidates
                                                if abs(lift - 48) > 2), .19)
        # The existing overlap-only acceptance rule remains unchanged.
        self.assertIsNone(raised_glyph_overlap_confirmation(baseline, after, face, self.point))

    def test_codec_control_explains_old_threshold_failure_without_lowering_it(self):
        before = Image.open(io.BytesIO(self.before)).convert("RGB")
        jpeg = io.BytesIO()
        before.save(jpeg, format="JPEG", quality=55)
        for label, frame in (("native PNG", self.before), ("same content JPEG55", jpeg.getvalue())):
            with self.subTest(label=label):
                result = self.confirm(before=frame)
                self.assertEqual((result["y"], result["lift"]), (948.5, 48))
        lookup = [255 if value < 120 else 0 for value in range(256)]
        native = before.convert("L").point(lookup).crop((1371, 931, 1443, 1044))
        shifted = Image.open(io.BytesIO(self.receipt)).convert("L").point(lookup).crop((1371, 883, 1443, 996))
        difference = ImageChops.difference(native, shifted)
        self.assertEqual(ImageStat.Stat(difference).sum[0] / 255, 166)
        self.assertEqual(ImageStat.Stat(difference.crop((0, 0, 72, 12))).sum[0] / 255, 122)

    def test_unchanged_tiles_and_other_slots_are_rejected(self):
        self.assertIsNone(self.confirm(receipt=self.before))
        self.assertIsNone(self.confirm(before=self.receipt))
        for index in (11, 13):
            with self.subTest(index=index):
                self.assertIsNone(self.confirm(index=index))

    def test_a_different_raised_glyph_cannot_substitute_for_south(self):
        image = Image.open(io.BytesIO(self.receipt)).convert("RGB")
        source = Image.open(io.BytesIO(self.before)).convert("RGB")
        # The neighbouring East is a real glyph with similar dark strokes,
        # moved into exactly South's raised face, with its rim left intact.
        image.paste(source.crop((1276, 931, 1348, 1044)), (1371, 883))
        self.assertIsNone(self.confirm(receipt=self.png(image)))

    def test_disappearance_or_broad_face_occlusion_is_rejected(self):
        for color in ((25, 55, 85), "black", "white", (180, 180, 180)):
            with self.subTest(color=color):
                self.assertIsNone(self.confirm(receipt=self.altered((1371, 883, 1442, 995), color)))

    def test_unproved_rim_or_changed_neighbour_cannot_use_cluster_fallback(self):
        for rectangle in ((1366, 873, 1450, 882), (1276, 931, 1347, 1043)):
            with self.subTest(rectangle=rectangle):
                self.assertIsNone(self.confirm(receipt=self.altered(rectangle, (100, 100, 100))))

    def test_countdown_without_a_target_lift_is_not_selection_evidence(self):
        image = Image.open(io.BytesIO(self.before)).convert("RGB")
        receipt = Image.open(io.BytesIO(self.receipt)).convert("RGB")
        # Transfer the actual changed countdown, leaving South in its original
        # row. Timer-only movement must never produce a confirmation click.
        image.paste(receipt.crop((1370, 820, 1550, 905)), (1370, 820))
        self.assertIsNone(self.confirm(receipt=self.png(image)))

    def test_other_recorded_tile_lifts_keep_their_observed_positions(self):
        fixtures = self.root / "test/fixtures"
        standard = load_json(self.root / "config/layout-300-regression.json")
        cases = [("7p", "before", "receipt", "20261029.png", 8, standard),
                 ("green", "before", "lift", "20261028.jpg", 13, standard),
                 ("8s-sparkle", "before", "lift", "20261028.png", 13, standard),
                 ("9m-inset", "before", "lift", "20261030.png", 13, self.layout)]
        for tile, first, second, suffix, index, layout in cases:
            with self.subTest(tile=tile):
                before = (fixtures / f"selection-{tile}-{first}-{suffix}").read_bytes()
                after = (fixtures / f"selection-{tile}-{second}-{suffix}").read_bytes()
                point = layout["clickPoints"][index]
                result = raised_tile_confirmation_point(before, after, layout, index, point, 1.5)
                self.assertIsNotNone(result)
                self.assertEqual(result["lift"], 48)
                self.assertIsNone(raised_tile_confirmation_point(before, before, layout, index, point, 1.5))


if __name__ == "__main__":
    unittest.main()
