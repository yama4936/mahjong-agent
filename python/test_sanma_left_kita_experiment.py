import tempfile
import unittest
from pathlib import Path
from PIL import Image
from sanma_left_kita_experiment import left_north_candidate

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'test/fixtures/sanma-left-kita'
TEMPLATE = FIXTURES / 'left-north-reference.png'
GLARE_TEMPLATE = FIXTURES / 'left-north-glare-reference.png'

class LeftKitaExperimentTest(unittest.TestCase):
    def probe(self, name, glare=False):
        image = Image.new('RGB', (1920, 1080))
        image.paste(Image.open(FIXTURES / (name + '.png')), (270, 680))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'frame.png'
            image.save(path)
            return left_north_candidate(path, TEMPLATE, glare_template_path=GLARE_TEMPLATE if glare else None)

    def test_separate_recorded_frames_have_candidate_not_verified_count(self):
        # Reference from 215; later, independently captured same-match images.
        for frame in ('216', '217', '219', '247'):
            with self.subTest(frame=frame):
                result = self.probe(frame)
                self.assertIsNotNone(result['candidate'])
                self.assertEqual((result['candidate']['x'], result['candidate']['y']), (305, 712))
                self.assertEqual(result['status'], 'unknown')
                self.assertFalse(result['verified'])
                self.assertFalse(result['complete'])
                self.assertNotIn('count', result)

    def test_missing_or_degraded_match_never_means_zero(self):
        # 218 visibly shows north but its correlation drops below threshold.
        for frame in ('214', '218', '254', '601'):
            with self.subTest(frame=frame):
                result = self.probe(frame)
                self.assertIsNone(result['candidate'])
                self.assertEqual(result['status'], 'unknown')
                self.assertFalse(result['verified'])

    def test_optional_glare_reference_recovers_unseen_highlight_frame(self):
        # Glare reference was taken from frame 218, not this later frame.
        self.assertIsNone(self.probe('223')['candidate'])
        result = self.probe('223', glare=True)
        self.assertEqual(result['candidate']['reference'], 'glare')
        self.assertGreaterEqual(result['candidate']['similarity'], .97)
        self.assertEqual(result['status'], 'unknown')
        self.assertFalse(result['verified'])
        self.assertFalse(result['complete'])
        # Further shimmer variants remain undetected; absence is unknown.
        for name in ('214', '227', '228', '233', '238', '244', '254', '601'):
            self.assertIsNone(self.probe(name, glare=True)['candidate'])

    def test_glare_reference_has_no_matches_on_four_player_boards(self):
        paths = list((ROOT / 'test/fixtures').glob('board-*.png')) + list((ROOT / 'test/fixtures').glob('board-*.jpg'))
        self.assertEqual(len(paths), 9)
        for path in paths:
            with self.subTest(path=path.name):
                result = left_north_candidate(path, TEMPLATE, glare_template_path=GLARE_TEMPLATE)
                self.assertIsNone(result.get('candidate'))
                self.assertEqual(result['status'], 'unknown')

    def test_invalid_glare_reference_never_silently_falls_back(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'frame.png'
            template = Path(temp) / 'blank.png'
            Image.new('L', (1920, 1080)).save(image)
            Image.new('L', (85, 48)).save(template)
            result = left_north_candidate(image, TEMPLATE, glare_template_path=template)
            self.assertEqual(result['reason'], 'uncalibrated_or_unreadable_glare_template')
            self.assertNotIn('candidate', result)

    def test_score_movement_screen_can_preserve_old_left_tile(self):
        result = self.probe('251')
        self.assertIsNotNone(result['candidate'])
        self.assertFalse(result['verified'])
        self.assertEqual(result['status'], 'unknown')

    def test_four_player_boards_do_not_match(self):
        paths = list((ROOT / 'test/fixtures').glob('board-*.png')) + list((ROOT / 'test/fixtures').glob('board-*.jpg'))
        self.assertEqual(len(paths), 9)
        for path in paths:
            with self.subTest(path=path.name):
                result = left_north_candidate(path, TEMPLATE)
                self.assertIsNone(result.get('candidate'))
                self.assertEqual(result['status'], 'unknown')

    def test_bad_image_and_template_are_unknown(self):
        result = left_north_candidate(FIXTURES / '214.png', TEMPLATE)
        self.assertEqual(result['reason'], 'uncalibrated_or_unreadable_image')
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'frame.png'
            template = Path(temp) / 'blank.png'
            Image.new('L', (1920, 1080)).save(image)
            Image.new('L', (85, 48)).save(template)
            result = left_north_candidate(image, template)
            self.assertEqual(result['reason'], 'uncalibrated_or_unreadable_template')
            self.assertEqual(result['status'], 'unknown')

if __name__ == '__main__':
    unittest.main()
