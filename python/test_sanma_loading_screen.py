import io
import os
import unittest
from pathlib import Path
from PIL import Image, ImageDraw
from screen_state import classify_screen

ROOT = Path(__file__).resolve().parents[1]

class SanmaLoadingTests(unittest.TestCase):
    def test_known_loading_caption_and_progress_bar_only(self):
        caption = Image.open(ROOT / "templates/screens/sanma-friend-loading-caption.png").convert("RGB")
        image = Image.new("RGB", (1920, 1080), (35, 52, 78))
        image.paste(caption, (840, 910))
        ImageDraw.Draw(image).rectangle((0, 998, 1100, 1009), fill="white")
        def classify(im):
            output = io.BytesIO(); im.save(output, format="PNG")
            return classify_screen(output.getvalue(), {})[0]
        self.assertEqual(classify(image), "loading")
        without_bar = image.copy(); ImageDraw.Draw(without_bar).rectangle((0, 998, 1919, 1009), fill="black")
        self.assertNotEqual(classify(without_bar), "loading")
        without_caption = image.copy(); ImageDraw.Draw(without_caption).rectangle((840, 910, 1079, 984), fill="black")
        self.assertNotEqual(classify(without_caption), "loading")
        self.assertNotEqual(classify(image.resize((1280, 720))), "loading")

    def test_archived_transition_frames(self):
        archive = os.environ.get("SANMA_ARCHIVE_ROOT")
        if not archive: self.skipTest("archive not configured")
        directory = Path(archive) / "continuous"
        for index in (5, 6, 7):
            frame = next(directory.glob(f"frame-{index:06d}-*"))
            with self.subTest(index=index): self.assertEqual(classify_screen(frame, {}), ("loading", 1.0))
        match = next(directory.glob("frame-000012-*"))
        self.assertEqual(classify_screen(match, {}), ("match", 1.0))

    def test_existing_static_screen_fixtures_are_not_reclassified_loading(self):
        for name in ("black-client-20261021.png", "ranked-reservation-20261020.png",
                     "black-recovered-lobby-20261021.png", "board-cache-opponent-turn-20261020.jpg",
                     "riichi-stick-red-occluded-20261021.jpg"):
            with self.subTest(name=name):
                self.assertNotEqual(classify_screen(ROOT / "test/fixtures" / name, {})[0], "loading")
