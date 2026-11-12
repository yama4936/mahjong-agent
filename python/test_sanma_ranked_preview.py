import os
import unittest
from pathlib import Path
from unittest.mock import Mock
from PIL import Image, ImageDraw
from sanma_ranked_preview import inspect_bronze_sanma_east, _REGIONS
from auto_operator import PythonAutoOperator

ROOT = Path(os.environ.get('SANMA_PREFLIGHT_ROOT', '/nonexistent'))
LIVE = Path(os.environ.get('JANTAMA_LIVE_ROOT', '/nonexistent'))

class SanmaRankedPreviewTests(unittest.TestCase):
    def image(self, path):
        if not path.exists():
            self.skipTest(f'missing optional real capture: {path}')
        with Image.open(path) as img:
            return img.convert('RGB')

    def test_real_bronze_screen_and_wrong_inputs_never_authorize_click(self):
        im = self.image(ROOT / 'jantama-bronze-menu.png')
        result = inspect_bronze_sanma_east(im)
        self.assertTrue(result.candidate, result.distances)
        self.assertFalse(result.click_permitted)
        self.assertIsNone(PythonAutoOperator.ranked_loop_click_point('ranked_room', {'width': 1920, 'height': 1080}, rules='sanma'))
        # Four-player East copied over three-player East must not qualify.
        im.paste(im.crop((1270, 360, 1530, 440)), (1270, 690))
        result = inspect_bronze_sanma_east(im)
        self.assertFalse(result.candidate, result.distances)
        self.assertFalse(result.click_permitted)

    def test_ranked_menu_profile_and_entry_denied_are_not_candidate(self):
        for path in [ROOT / 'jantama-ranked-menu.png', ROOT / 'jantama-profile.png', LIVE / 'b2a16a7-copper-menu-20261015.png']:
            with self.subTest(path=path):
                result = inspect_bronze_sanma_east(self.image(path))
                self.assertFalse(result.candidate, result.distances)
                self.assertFalse(result.click_permitted)

    def test_wrong_size_fails_closed(self):
        self.assertFalse(inspect_bronze_sanma_east(Image.new('RGB', (960, 540))).candidate)

    def test_label_paste_on_black_and_target_overlay_are_rejected(self):
        source = self.image(ROOT / 'jantama-bronze-menu.png')
        fake = Image.new('RGB', source.size)
        for name in ('bronze', 'yonma_east', 'sanma_east'):
            box = _REGIONS[name][0]
            fake.paste(source.crop(box), box[:2])
        result = inspect_bronze_sanma_east(fake)
        self.assertFalse(result.candidate, result.distances)
        self.assertFalse(result.click_permitted)
        for box in [(1130, 660, 1250, 815), (1270, 690, 1530, 770)]:
            with self.subTest(box=box):
                covered = source.copy()
                ImageDraw.Draw(covered).rectangle(box, fill=(30, 30, 30))
                result = inspect_bronze_sanma_east(covered)
                self.assertFalse(result.candidate, result.distances)
                self.assertFalse(result.click_permitted)
