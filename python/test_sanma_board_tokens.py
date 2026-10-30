import copy
import json
import unittest
from pathlib import Path
from board_metadata import parse_sanma_board_tokens


class SanmaBoardTokensTest(unittest.TestCase):
    def tokens(self, seat):
        return json.loads((Path(__file__).resolve().parents[1] / 'test/fixtures/sanma-board-tokens' / f'{seat}.json').read_text())

    def parse(self, tokens, total=105000, phase='settled'):
        return parse_sanma_board_tokens(tokens, expected_total_points=total, payment_phase=phase)

    def test_three_native_frames_candidate_values(self):
        cases = {
            'west': ('east_1', {'west': 35000, 'south': 35000, 'east': 35000}, 0),
            'south': ('east_2', {'south': 42000, 'east': 32000, 'west': 31000}, 0),
            'east': ('east_3', {'east': 41500, 'west': 33000, 'south': 30500}, 2),
        }
        for seat, (round_name, scores, honba) in cases.items():
            with self.subTest(seat=seat):
                result = self.parse(self.tokens(seat))
                self.assertFalse(result['verified'])
                self.assertTrue(result['consistent'])
                self.assertEqual(result['candidate'], {'seat': seat, 'round': round_name,
                                 'scores': scores, 'riichiSticks': 0, 'honba': honba})

    def test_missing_conflicting_and_unsettled_fail_closed(self):
        tokens = self.tokens('south')
        self.assertFalse(self.parse(tokens, total=None).get('consistent', False))
        self.assertFalse(self.parse(tokens, phase=None).get('consistent', False))
        self.assertFalse(self.parse(tokens, total=100000).get('consistent', False))
        self.assertFalse(self.parse([t for t in tokens if t['x'] != 958]).get('consistent', False))
        changed = copy.deepcopy(tokens)
        changed.append({'text': '12345', 'confidence': 1.0, 'x': 1047, 'y': 419})
        self.assertEqual(self.parse(changed)['reason'], 'unexpected_right_score')
        changed = copy.deepcopy(tokens)
        changed.append({'text': '99999', 'confidence': 1.0, 'x': 960, 'y': 482})
        self.assertFalse(self.parse(changed).get('consistent', False))
