import json
import unittest
from pathlib import Path

from board_metadata import parse_sanma_board_tokens
from sanma_board_image import recognize_sanma_board_candidate


class OppositeRightDiagnostics(unittest.TestCase):
    def test_two_saved_game_images(self):
        root = Path('/home/yama1/.codex/sanma-58a817a-20261102')
        cases = [('manual-001.png', 35000, 35000, 35000, 'east', 'south'),
                 ('manual-063.png', 76600, 18100, 10300, 'west', 'east')]
        if not all((root / case[0]).exists() for case in cases):
            self.skipTest('local saved images unavailable')
        try:
            import rapidocr  # noqa: F401
        except ImportError:
            self.skipTest('optional OCR dependencies unavailable')
        for name, own, opposite, right, own_wind, right_wind in cases:
            with self.subTest(name=name):
                result = recognize_sanma_board_candidate(root / name, expected_total_points=105000,
                                                           payment_phase='settled')
                self.assertFalse(result['verified'])
                self.assertNotIn('candidate', result)
                self.assertEqual(result['reason'], 'unsupported_opposite_right_layout')
                self.assertEqual(result['positionObservation']['positions'], {
                    'own': {'score': own, 'wind': own_wind},
                    'opposite': {'score': opposite}, 'right': {'score': right, 'wind': right_wind}})

    def test_synthetic_positions_never_promote_to_score_mapping(self):
        def token(text, x, y):
            return {'text': text, 'confidence': 0.999, 'x': x, 'y': y}
        tokens = [token('76600', 960, 482), token('18100', 958, 364),
                  token('10300', 1047, 419), token('西', 824, 514), token('東', 1093, 514)]
        result = parse_sanma_board_tokens(tokens, expected_total_points=105000, payment_phase='settled')
        self.assertEqual(result['reason'], 'unsupported_opposite_right_layout')
        self.assertFalse(result['positionObservation']['complete'])
        self.assertNotIn('candidate', result)
        self.assertEqual(result['positionObservation']['positions']['opposite'], {'score': 18100})

    def test_real_recorded_tokens_remain_position_only(self):
        receipt = Path('/home/yama1/.codex/sanma-58a817a-20261102/run/frames/2026-11-02T12-37-14.544239+00-00.e83ed191c19a4c58b7a38d56cd4b6dea.sanma-self-turn.receipt.json')
        if not receipt.exists():
            self.skipTest('local recorded frame unavailable')
        data = json.loads(receipt.read_text())
        tokens = data['sourceObservation']['board']['tokens']
        result = parse_sanma_board_tokens(tokens, expected_total_points=105000, payment_phase='settled')
        self.assertEqual(result['reason'], 'unsupported_opposite_right_layout')
        self.assertFalse(result['verified'])
        self.assertNotIn('candidate', result)
        self.assertEqual(result['positionObservation']['positions'], {
            'own': {'score': 35000, 'wind': 'east'},
            'opposite': {'score': 35000}, 'right': {'score': 35000, 'wind': 'south'}})

    def test_simultaneous_fourth_score_is_not_classified_as_three_positions(self):
        def token(text, x, y):
            return {'text': text, 'confidence': 0.999, 'x': x, 'y': y}
        tokens = [token('35000', 960, 482), token('35000', 876, 423),
                  token('35000', 958, 364), token('35000', 1047, 419)]
        result = parse_sanma_board_tokens(tokens, expected_total_points=105000, payment_phase='settled')
        self.assertFalse(result['verified'])
        self.assertNotIn('positionObservation', result)

    def test_left_score_duplicates_and_low_confidence_never_imply_empty_seat(self):
        def token(text, x, y, confidence=0.999):
            return {'text': text, 'confidence': confidence, 'x': x, 'y': y}
        common = [token('35000', 960, 482), token('35000', 958, 364),
                  token('35000', 1047, 419)]
        for left in ([token('35000', 876, 423), token('35000', 876, 423)],
                     [token('35000', 876, 423), token('32000', 876, 423)],
                     [token('35000', 876, 423, 0.4)], [token('0', 876, 423, 0.4)]):
            with self.subTest(left=left):
                result = parse_sanma_board_tokens(common + left, expected_total_points=105000,
                                                   payment_phase='settled')
                self.assertFalse(result['verified'])
                self.assertNotIn('positionObservation', result)

    def test_mixed_zero_and_duplicate_scores_are_never_accepted_per_position(self):
        def token(text, x, y):
            return {'text': text, 'confidence': 0.999, 'x': x, 'y': y}
        positions = {'own': (960, 482), 'left': (876, 423),
                     'opposite': (958, 364), 'right': (1047, 419)}
        for layout in (('own', 'left', 'opposite'), ('own', 'opposite', 'right'),
                       ('own', 'left', 'right')):
            for position in layout:
                for conflicting in ('0', '35000', '32000'):
                    tokens = [token('35000', *positions[p]) for p in layout]
                    tokens.append(token(conflicting, *positions[position]))
                    with self.subTest(layout=layout, position=position, conflicting=conflicting):
                        result = parse_sanma_board_tokens(tokens, expected_total_points=105000,
                                                           payment_phase='settled')
                        self.assertNotIn('candidate', result)
                        for key in ('positionObservation', 'rightLayoutObservation'):
                            observation = result.get(key, {})
                            self.assertNotIn('score', observation.get('positions', {}).get(position, {}))

