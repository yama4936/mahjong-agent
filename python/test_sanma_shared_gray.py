import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image
from sanma_board_image import observe_sanma_image
from sanma_kita_image_experiment import detect_own_north_candidates, detect_own_partial_north_candidate
from sanma_opposite_kita_experiment import opposite_north_candidate
from sanma_left_kita_experiment import left_north_candidate
from sanma_right_kita_experiment import right_north_candidate

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / 'test/fixtures'
PYREF = ROOT / 'python/fixtures'


def separate(path):
    return {
        'own': {**detect_own_north_candidates(path, REF / 'sanma-public-experiment/own-north-face.png'),
                'partialObservation': detect_own_partial_north_candidate(path, PYREF / 'sanma-own-north-partial-c177.png')},
        'opposite': opposite_north_candidate(path, REF / 'sanma-opposite-kita/north-glyph-reference.png', shadow_template_path=REF / 'sanma-opposite-kita/north-glyph-shadow-reference.png'),
        'left': left_north_candidate(path, REF / 'sanma-left-kita/left-north-reference.png', glare_template_path=REF / 'sanma-left-kita/left-north-glare-reference.png'),
        'right': right_north_candidate(path, [PYREF / f'sanma-right-north-c177-{x}.png' for x in ('top', 'bottom')]),
    }


class SharedGrayTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.paths = [Path(self.dir.name) / f'{i}.png' for i in range(2)]
        for i, path in enumerate(self.paths):
            img = np.full((1080, 1920, 3), 60 + 140*i, dtype=np.uint8)
            img[100:150, 500:610, :] = (11 + i, 100, 210)
            Image.fromarray(img).save(path)
        self.board = patch('sanma_board_image.recognize_sanma_board_candidate', return_value={'verified':False})
        self.board.start()
        self.addCleanup(self.board.stop)

    def test_separate_and_shared_readings_are_identical_and_single_decode(self):
        real = cv2.imread
        expected = separate(self.paths[0])
        count = []
        def monitor(path, flags):
            if path == str(self.paths[0]): count.append(path)
            return real(path, flags)
        with patch.object(cv2, 'imread', side_effect=monitor):
            actual = observe_sanma_image(self.paths[0])
        self.assertEqual(actual['north']['positions'], expected)
        self.assertEqual(len(count), 1)

    def test_distinct_frames_and_parallel_calls_have_no_shared_cache(self):
        expected = {p: separate(p) for p in self.paths}
        self.assertNotEqual(expected[self.paths[0]]['left']['frame_sha256'], expected[self.paths[1]]['left']['frame_sha256'])
        order = [self.paths[0], self.paths[1], self.paths[0], self.paths[1]]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(observe_sanma_image, order))
        for p, result in zip(order, results):
            self.assertEqual(result['north']['positions'], expected[p])

    def test_failed_decode_and_exception_fail_closed(self):
        with patch.object(cv2, 'imread', side_effect=RuntimeError('decode failed')):
            self.assertEqual(observe_sanma_image(self.paths[0])['north']['reason'], 'north observation failed: decode failed')
        self.paths[0].write_bytes(b'not an image')
        self.assertEqual(observe_sanma_image(self.paths[0])['north']['positions'], separate(self.paths[0]))

if __name__ == '__main__': unittest.main()
