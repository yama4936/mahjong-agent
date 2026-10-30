import json
import unittest
from pathlib import Path
from unittest.mock import patch

from sanma_board_image import recognize_sanma_board_candidate
from board_metadata import recognize_board

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = ROOT / 'artifacts/sanma-manual-e48c562-20261031/actions'
CASES = [
    ('2026-10-30T16-05-55-331Z-before.png', 'west', 'east_1',
     {'west': 35000, 'south': 35000, 'east': 35000}, 0, 52),
    ('2026-10-30T16-30-00-848Z-before.png', 'south', 'east_2',
     {'south': 42000, 'east': 32000, 'west': 31000}, 0, 40),
    ('2026-10-30T17-20-14-718Z-after.png', 'east', 'east_3',
     {'east': 41500, 'west': 33000, 'south': 30500}, 2, 51),
]


class SanmaBoardImageTests(unittest.TestCase):
    @unittest.skipUnless(Path('/home/yama1/sanma-independent-20261031/20-turn.png').exists(), 'independent frame unavailable')
    def test_new_right_layout_is_not_mapped_as_the_old_opposite_layout(self):
        frame = Path('/home/yama1/sanma-independent-20261031/20-turn.png')
        result = recognize_sanma_board_candidate(frame, expected_total_points=None, payment_phase=None)
        self.assertFalse(result['verified'])
        self.assertEqual(result['reason'], 'unsupported_right_opponent_layout')
        self.assertEqual(result['layoutCandidate'], {'opponents':['left','right'], 'verified':False})
        self.assertNotIn('candidate', result)
        observation = result['rightLayoutObservation']
        self.assertEqual(observation['positions'], {'own': {'wind': 'south', 'score': 35000},
            'left': {'wind': 'east', 'score': 35000}, 'right': {'wind': 'west', 'score': 35000}})
        self.assertEqual(observation['scoresByObservedWind'], {'south': 35000, 'east': 35000, 'west': 35000})
        self.assertFalse(observation['verified'])
        self.assertFalse(observation['complete'])

    @unittest.skipUnless((ACTIONS / '2026-10-30T17-30-50-782Z-before.png').exists(), 'local score frame unavailable')
    def test_sanma_left_score_retry_recovers_unverified_candidate(self):
        frame = ACTIONS / '2026-10-30T17-30-50-782Z-before.png'
        default = recognize_board(frame)
        self.assertFalse(any(t['text'] == '33000' and t['confidence'] >= .98 for t in default['tokens']))
        result = recognize_sanma_board_candidate(frame, expected_total_points=None, payment_phase=None)
        self.assertFalse(result['verified'])
        self.assertFalse(result.get('consistent', False))
        self.assertEqual(result['candidate']['remainingTiles'], 43)
        self.assertEqual(result['candidate']['scores'], {'east': 41500, 'west': 33000, 'south': 30500})
        self.assertTrue(any(t['text'] == '33000' and t['confidence'] >= .98 and
                            t.get('source') == 'upright_left_score_crop' and t.get('cropWidth') == 328
                            for t in result['tokens']))

    @unittest.skipUnless((ACTIONS / '2026-10-30T16-40-57-727Z-before.png').exists(), 'local compact hand frame unavailable')
    def test_compact_sanma_hand_can_yield_only_unverified_board_candidate(self):
        frame = ACTIONS / '2026-10-30T16-40-57-727Z-before.png'
        # Default four-player/operator path and shared screen state stay unchanged.
        self.assertEqual(recognize_board(frame)['reason'], 'not_gameplay_screen')
        result = recognize_sanma_board_candidate(frame, expected_total_points=None, payment_phase=None)
        self.assertFalse(result['verified'])
        self.assertFalse(result.get('consistent', False))
        self.assertEqual(result['screenEvidence'], 'sanma_compact_candidate')
        self.assertEqual(result['candidate']['remainingTiles'], 27)
        self.assertEqual(result['candidate']['seat'], 'south')
        self.assertEqual(result['candidate']['scores'], {'south': 42000, 'east': 32000, 'west': 31000})

    def test_screen_rejection_is_not_promoted(self):
        with patch('sanma_board_image.recognize_board', return_value={
                'verified': False, 'reason': 'not_gameplay_screen'}):
            result = recognize_sanma_board_candidate(Path('unused'), expected_total_points=105000,
                                                      payment_phase='settled')
        self.assertFalse(result['verified'])
        self.assertEqual(result['reason'], 'not_gameplay_screen')

    def test_unobserved_settings_and_missing_score_stay_unverified(self):
        tokens = json.loads((ROOT / 'test/fixtures/sanma-board-tokens/west.json').read_text())
        with patch('sanma_board_image.recognize_board', return_value={'tokens': tokens}):
            unknown = recognize_sanma_board_candidate(Path('unused'), expected_total_points=None,
                                                        payment_phase=None)
        self.assertFalse(unknown['verified'])
        self.assertNotEqual(unknown.get('consistent'), True)
        self.assertEqual(unknown['reason'], 'expected_total_points_unknown')
        tokens = [token for token in tokens if abs(token['x'] - 958) > 24 or abs(token['y'] - 364) > 20]
        with patch('sanma_board_image.recognize_board', return_value={'tokens': tokens}):
            missing = recognize_sanma_board_candidate(Path('unused'), expected_total_points=105000,
                                                        payment_phase='settled')
        self.assertFalse(missing['verified'])
        self.assertNotIn('candidate', missing)
        self.assertEqual(missing['reason'], 'incomplete_or_ambiguous_tokens')

    @unittest.skipUnless(all((ACTIONS / case[0]).exists() for case in CASES),
                         'local screenshots from the manually assisted match unavailable')
    def test_three_real_saved_images_end_to_end(self):
        try:
            import rapidocr  # noqa: F401
        except ImportError:
            self.skipTest('optional OCR dependencies unavailable')
        for name, seat, round_name, scores, honba, remaining in CASES:
            with self.subTest(seat=seat):
                result = recognize_sanma_board_candidate(ACTIONS / name, expected_total_points=105000,
                                                          payment_phase='settled')
                self.assertFalse(result['verified'])
                self.assertTrue(result.get('consistent'), result)
                self.assertEqual(result['candidate'], {'seat': seat, 'round': round_name,
                                 'scores': scores, 'riichiSticks': 0, 'honba': honba,
                                 'remainingTiles': remaining})


if __name__ == '__main__':
    unittest.main()
