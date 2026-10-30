import tempfile
import unittest
from pathlib import Path
from PIL import Image
from sanma_friend_result import detect_sanma_friend_result

FIX = Path(__file__).resolve().parents[1] / 'test/fixtures/sanma-result'

class ResultDetectionTest(unittest.TestCase):
    def test_recorded_result_and_distinct_negatives(self):
        self.assertEqual(detect_sanma_friend_result(FIX / 'positive-redacted.png')['status'], 'sanma_friend_east_result_candidate')
        for name in ('yonma', 'yonma_false_positive', 'live', 'round'):
            with self.subTest(name=name):
                self.assertEqual(detect_sanma_friend_result(FIX / f'{name}-redacted.png')['status'], 'unknown')

    def test_missing_shifted_and_resized_are_unknown(self):
        self.assertEqual(detect_sanma_friend_result(FIX / 'missing.png')['status'], 'unknown')
        with tempfile.TemporaryDirectory() as tmp:
            image = Image.open(FIX / 'positive-redacted.png')
            resized = Path(tmp) / 'resized.png'; image.resize((960, 540)).save(resized)
            shifted = Path(tmp) / 'shifted.png'; shifted_image = Image.new('RGB', image.size); shifted_image.paste(image, (8, 0)); shifted_image.save(shifted)
            self.assertEqual(detect_sanma_friend_result(resized)['status'], 'unknown')
            self.assertEqual(detect_sanma_friend_result(shifted)['status'], 'unknown')

    def test_obscured_mode_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Image.open(FIX / 'positive-redacted.png'); image.paste((0, 0, 0), (52, 190, 290, 225))
            path = Path(tmp) / 'covered.png'; image.save(path)
            self.assertEqual(detect_sanma_friend_result(path)['status'], 'unknown')

if __name__ == '__main__': unittest.main()
