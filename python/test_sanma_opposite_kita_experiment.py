import tempfile
import unittest
from pathlib import Path
from PIL import Image
from sanma_opposite_kita_experiment import opposite_north_candidate

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'test/fixtures/sanma-opposite-kita'
TEMPLATE = FIXTURES / 'north-glyph-reference.png'
SHADOW_TEMPLATE = FIXTURES / 'north-glyph-shadow-reference.png'

class OppositeKitaExperimentTest(unittest.TestCase):
    def probe(self, name, shadow=False):
        image = Image.new('RGB', (1920, 1080))
        image.paste(Image.open(FIXTURES / (name + '.png')), (500, 80))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'frame.png'
            image.save(path)
            return opposite_north_candidate(path, TEMPLATE, shadow_template_path=SHADOW_TEMPLATE if shadow else None)

    def test_independent_real_crops_match_only_as_candidates(self):
        # Reference from frame 571; these are later frames in the same game.
        for name in ('601', '602', '1501'):
            with self.subTest(name=name):
                result = self.probe(name)
                self.assertIsNotNone(result['candidate'])
                self.assertEqual((result['candidate']['x'], result['candidate']['y']), (535, 101))
                self.assertEqual(result['status'], 'unknown')
                self.assertFalse(result['verified'])
                self.assertFalse(result['complete'])
                self.assertNotIn('count', result)

    def test_no_match_or_shadow_does_not_mean_zero(self):
        # 451 visibly contains north but shade causes a score below threshold.
        for name in ('301', '451', '901', '1801'):
            with self.subTest(name=name):
                result = self.probe(name)
                self.assertIsNone(result['candidate'])
                self.assertEqual(result['status'], 'unknown')
                self.assertFalse(result['complete'])

    def test_secondary_reference_recovers_unseen_shadow_frames_as_unverified_candidates(self):
        # Reference is from 451; held-out examples 433, 497, 543 all visibly contain north.
        for name in ('433', '497', '543'):
            with self.subTest(name=name):
                self.assertIsNone(self.probe(name)['candidate'])
                result = self.probe(name, shadow=True)
                self.assertEqual(result['candidate']['reference'], 'shadow')
                self.assertGreaterEqual(result['candidate']['similarity'], .97)
                self.assertEqual(result['status'], 'unknown')
                self.assertFalse(result['verified'])
                self.assertFalse(result['complete'])
        for name in ('301', '901', '1801'):
            self.assertIsNone(self.probe(name, shadow=True)['candidate'])

    def test_shadow_template_never_makes_four_player_control_a_match(self):
        paths = list((ROOT / 'test/fixtures').glob('board-*.png')) + list((ROOT / 'test/fixtures').glob('board-*.jpg'))
        self.assertEqual(len(paths), 9)
        for path in paths:
            with self.subTest(path=path.name):
                result = opposite_north_candidate(path, TEMPLATE, shadow_template_path=SHADOW_TEMPLATE)
                self.assertIsNone(result.get('candidate'))
                self.assertEqual(result['status'], 'unknown')

    def test_invalid_shadow_reference_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'frame.png'
            template = Path(temp) / 'blank.png'
            Image.new('L', (1920, 1080)).save(image)
            Image.new('L', (40, 29)).save(template)
            result = opposite_north_candidate(image, TEMPLATE, shadow_template_path=template)
            self.assertEqual(result['reason'], 'uncalibrated_or_unreadable_shadow_template')
            self.assertNotIn('candidate', result)

    def test_final_overlay_can_match_stale_board(self):
        result = self.probe('2911')
        self.assertIsNotNone(result['candidate'])
        self.assertEqual(result['status'], 'unknown')
        self.assertFalse(result['verified'])

    def test_other_four_player_board_images_no_template_match(self):
        paths = list((ROOT / 'test/fixtures').glob('board-*.png')) + list((ROOT / 'test/fixtures').glob('board-*.jpg'))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path.name):
                result = opposite_north_candidate(path, TEMPLATE)
                self.assertIsNone(result.get('candidate'))
                self.assertFalse(result['verified'])

    def test_uncalibrated_image_and_template_remain_unknown(self):
        result = opposite_north_candidate(FIXTURES / '301.png', TEMPLATE)
        self.assertEqual(result['reason'], 'uncalibrated_or_unreadable_image')
        self.assertEqual(result['status'], 'unknown')
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'frame.png'
            template = Path(temp) / 'constant.png'
            Image.new('L', (1920, 1080)).save(image)
            Image.new('L', (40, 29)).save(template)
            result = opposite_north_candidate(image, template)
            self.assertEqual(result['reason'], 'uncalibrated_or_unreadable_template')
            self.assertEqual(result['status'], 'unknown')

if __name__ == '__main__':
    unittest.main()
