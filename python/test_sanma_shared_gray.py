import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from hashlib import sha256
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


class SharedRgbPartialTest(unittest.TestCase):
    def test_shared_rgb_matches_redecode_for_modes_and_concurrent_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for mode in ('RGB', 'RGBA', 'L', 'P', 'I;16'):
                p = root / (mode.replace(';', '_') + '.png')
                Image.new(mode, (1920, 1080)).save(p)
                paths.append(p)
            small = root / 'small.png'
            Image.new('RGB', (20, 20)).save(small)
            paths.append(small)
            template = PYREF / 'sanma-own-north-partial-c177.png'
            def compare(path):
                expected = detect_own_partial_north_candidate(path, template)
                with Image.open(path) as img:
                    rgb = img.convert('RGB')
                return detect_own_partial_north_candidate(path, template, image_rgb=rgb, expected_sha256=sha256(path.read_bytes()).hexdigest()) == expected
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                self.assertTrue(all(pool.map(compare, paths * 2)))

    def test_missing_reference_and_source_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            p = root / 'frame.png'
            Image.new('RGB', (1920, 1080)).save(p)
            with Image.open(p) as img:
                rgb = img.convert('RGB')
            absent = root / 'missing.png'
            expected = detect_own_partial_north_candidate(p, absent)
            self.assertEqual(detect_own_partial_north_candidate(p, absent, image_rgb=rgb, expected_sha256=sha256(p.read_bytes()).hexdigest()), expected)
            digest = sha256(p.read_bytes()).hexdigest()
            p.unlink()
            self.assertEqual(detect_own_partial_north_candidate(p, PYREF / 'sanma-own-north-partial-c177.png', image_rgb=rgb, expected_sha256=digest),
                             detect_own_partial_north_candidate(p, PYREF / 'sanma-own-north-partial-c177.png'))

    def test_replaced_frame_is_rejected_without_fabricated_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'frame.png'
            Image.new('RGB', (1920, 1080), 'white').save(path)
            with Image.open(path) as source:
                rgb = source.convert('RGB')
            digest = sha256(path.read_bytes()).hexdigest()
            Image.new('RGB', (1920, 1080), 'black').save(path)
            result = detect_own_partial_north_candidate(path, PYREF / 'sanma-own-north-partial-c177.png',
                                                        image_rgb=rgb, expected_sha256=digest)
            self.assertEqual(result['reason'], 'shared_frame_digest_mismatch')
            self.assertNotIn('candidate', result)
            self.assertNotIn('frame_sha256', result)
            self.assertFalse(result['verified'])

    def test_board_snapshot_mismatch_rejects_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'frame.png'
            Image.new('RGB', (1920, 1080), 'white').save(path)
            def board(path, **kwargs):
                with Image.open(path) as source:
                    kwargs['_rgb_sink'].append((source.convert('RGB'), sha256(path.read_bytes()).hexdigest()))
                return {'verified': False}
            with patch('sanma_board_image.recognize_sanma_board_candidate', side_effect=board):
                with self.assertRaisesRegex(ValueError, 'board frame digest mismatch'):
                    observe_sanma_image(path, expected_sha256='0' * 64)

    def test_observation_wires_board_rgb_to_partial_recognizer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'frame.png'
            Image.new('RGB', (1920, 1080), 'white').save(path)
            def board(path, **kwargs):
                with Image.open(path) as source:
                    kwargs['_rgb_sink'].append((source.convert('RGB'), sha256(path.read_bytes()).hexdigest()))
                return {'verified': False}
            with patch('sanma_board_image.recognize_sanma_board_candidate', side_effect=board), \
                 patch('sanma_kita_image_experiment.detect_own_partial_north_candidate', wraps=detect_own_partial_north_candidate) as partial:
                result = observe_sanma_image(path)
            self.assertIsNotNone(partial.call_args.kwargs['image_rgb'])
            self.assertEqual(result['north']['positions'], separate(path))

if __name__ == '__main__': unittest.main()
