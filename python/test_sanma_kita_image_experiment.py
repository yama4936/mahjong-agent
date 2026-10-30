import tempfile
import unittest
from pathlib import Path
from PIL import Image

from sanma_kita_image_experiment import (detect_own_north_candidates,
                                         compare_own_north_candidate_frames)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'test/fixtures/sanma-public-experiment'


class KitaImageExperimentTest(unittest.TestCase):
    def probe(self, name):
        # Small, redacted source crops are placed at the original coordinates.
        image = Image.new('RGB', (1920, 1080))
        image.paste(Image.open(FIXTURES / (name + '.png')), (1180, 750))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'frame.png'
            image.save(path)
            return detect_own_north_candidates(path, FIXTURES / 'own-north-face.png')

    def test_positive_candidates_are_incomplete(self):
        for name, expected in [('own-one', 1), ('own-three-countdown', 2)]:
            with self.subTest(name=name):
                result = self.probe(name)
                self.assertFalse(result['verified'])
                self.assertFalse(result['complete'])
                self.assertEqual(len(result['matches']), expected)

    def test_absence_or_shadow_never_claims_zero(self):
        for name in ('own-none', 'own-one-shadow'):
            result = self.probe(name)
            self.assertEqual(result['matches'], [])
            self.assertFalse(result['complete'])
            self.assertFalse(result['verified'])

    def test_existing_four_player_board_fixtures_do_not_match(self):
        paths = list((ROOT / 'test/fixtures').glob('board-*.png')) + list((ROOT / 'test/fixtures').glob('board-*.jpg'))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path.name):
                result = detect_own_north_candidates(path, FIXTURES / 'own-north-face.png')
                self.assertFalse(result['verified'])
                self.assertEqual(result.get('matches', []), [])

    def test_real_occlusion_keeps_stable_and_previously_seen_separate(self):
        a, b = self.probe('frame-001003-north-area'), self.probe('frame-001004-north-area')
        result = compare_own_north_candidate_frames(a, b, previous_hand_id='reviewed-east2',
            current_hand_id='reviewed-east2', previous_index=1003, current_index=1004)
        self.assertEqual(result['stable_candidate_slots'], [1, 2])
        self.assertEqual(result['previous_only_candidate_slots'], [0])
        self.assertEqual(result['current_only_candidate_slots'], [])
        self.assertFalse(result['verified'])
        self.assertFalse(result['complete'])
        self.assertNotIn('count', result)

    def test_no_carry_across_hand_duplicate_or_stale_frame(self):
        a, b = self.probe('frame-001003-north-area'), self.probe('frame-001004-north-area')
        opts = dict(previous_hand_id='h1', current_hand_id='h1', previous_index=10, current_index=11)
        self.assertEqual(compare_own_north_candidate_frames(a, a, **opts)['reason'], 'duplicate_frame')
        self.assertEqual(compare_own_north_candidate_frames(a, b, **{**opts, 'current_hand_id': 'h2'})['reason'], 'hand_identity_or_frame_order_unknown')
        self.assertEqual(compare_own_north_candidate_frames(a, b, **{**opts, 'current_index': 10})['reason'], 'hand_identity_or_frame_order_unknown')
        self.assertEqual(compare_own_north_candidate_frames(a, b, **{**opts, 'previous_hand_id': None})['reason'], 'hand_identity_or_frame_order_unknown')

    def test_one_frame_false_candidate_is_not_stable(self):
        a, b = self.probe('frame-001003-north-area'), self.probe('frame-001004-north-area')
        # Emulate an isolated high-scoring false match in one otherwise valid
        # frame: temporal association retains it as uncertain, never confirmed.
        a = {**a, 'matches': a['matches'][:1]}
        b = {**b, 'matches': []}
        result = compare_own_north_candidate_frames(a, b, previous_hand_id='h', current_hand_id='h', previous_index=1, current_index=2)
        self.assertEqual(result['stable_candidate_slots'], [])
        self.assertEqual(result['previous_only_candidate_slots'], [0])
        bad = {**a, 'matches': [{**a['matches'][0], 'x': 1408}]}
        self.assertEqual(compare_own_north_candidate_frames(bad, b, previous_hand_id='h', current_hand_id='h', previous_index=1, current_index=2)['reason'], 'invalid_or_uncalibrated_candidate')

    def test_consecutive_one_and_shadow_is_ambiguous(self):
        a, b = self.probe('own-one'), self.probe('own-one-shadow')
        result = compare_own_north_candidate_frames(a, b, previous_hand_id='h', current_hand_id='h', previous_index=1, current_index=2)
        self.assertEqual(result['stable_candidate_slots'], [])
        self.assertEqual(result['previous_only_candidate_slots'], [0])
        self.assertFalse(result['verified'])

    def test_result_overlay_still_contains_north_candidates_not_live_evidence(self):
        # Real final-result screen retains the last table image underneath.
        # A glyph match alone cannot establish an active hand or current count.
        result = self.probe('frame-002911-result-north-area')
        self.assertEqual(len(result['matches']), 3)
        self.assertFalse(result['verified'])
        self.assertFalse(result['complete'])

    def test_invalid_constant_template_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            template = Path(temp) / 'template.png'
            frame = Path(temp) / 'frame.png'
            Image.new('L', (53, 54)).save(template)
            Image.new('L', (1920, 1080)).save(frame)
            result = detect_own_north_candidates(frame, template)
            self.assertEqual(result['reason'], 'uncalibrated_or_unreadable_template')
            self.assertNotIn('matches', result)

    def test_wrong_size_and_missing_image_are_unknown(self):
        for name in ('own-none.png', 'missing.png'):
            result = detect_own_north_candidates(FIXTURES / name, FIXTURES / 'own-north-face.png')
            self.assertFalse(result['verified'])
            self.assertEqual(result['reason'], 'uncalibrated_or_unreadable_image')
            self.assertNotIn('matches', result)


if __name__ == '__main__':
    unittest.main()
