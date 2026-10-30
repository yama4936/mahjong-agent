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
                expected = {'seat': seat, 'round': round_name,
                            'scores': scores, 'riichiSticks': 0, 'honba': honba}
                observed = [t['text'] for t in self.tokens(seat) if t['text'].startswith('余')]
                if len(observed) == 1:
                    expected['remainingTiles'] = int(observed[0][1:])
                self.assertEqual(result['candidate'], expected)

    def test_wall_count_is_candidate_only_and_missing_is_not_zero(self):
        tokens = self.tokens('south')
        result = self.parse(tokens, total=None, phase=None)
        self.assertEqual(result['candidate']['remainingTiles'], 40)
        self.assertFalse(result['verified'])
        self.assertFalse(result.get('consistent', False))
        absent = [t for t in tokens if not t['text'].startswith('余')]
        self.assertNotIn('remainingTiles', self.parse(absent)['candidate'])
        for bad in [
            {'text': '余40', 'confidence': 0.9, 'x': 959, 'y': 443},
            {'text': '余71', 'confidence': 1.0, 'x': 959, 'y': 443},
            {'text': '余40', 'confidence': 1.0, 'x': 1100, 'y': 443},
        ]:
            self.assertNotIn('remainingTiles', self.parse(absent + [bad])['candidate'])
        conflicting = tokens + [{'text': '余41', 'confidence': 1.0, 'x': 959, 'y': 443}]
        self.assertNotIn('remainingTiles', self.parse(conflicting)['candidate'])

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
        changed = copy.deepcopy(tokens)
        changed.append({'text': '31000', 'confidence': 1.0, 'x': 876, 'y': 423,
                        'source': 'upright_left_score_crop', 'cropWidth': 328})
        self.assertEqual(self.parse(changed)['reason'], 'incomplete_or_ambiguous_tokens')

    def test_right_layout_reads_winds_and_scores_without_inference(self):
        def token(text, x, y, confidence=0.999):
            return {'text': text, 'x': x, 'y': y, 'confidence': confidence}
        tokens = [token('南',824,514), token('東',835,335), token('西',1093,514),
                  token('35000',960,482), token('32000',876,423), token('38000',1047,419)]
        result = self.parse(tokens)
        observed = result['rightLayoutObservation']
        self.assertFalse(observed['verified'])
        self.assertFalse(observed['complete'])
        self.assertEqual(observed['positions'], {'own': {'wind':'south','score':35000},
            'left': {'wind':'east','score':32000}, 'right': {'wind':'west','score':38000}})
        self.assertEqual(observed['scoresByObservedWind'], {'south':35000,'east':32000,'west':38000})
        self.assertNotIn('candidate', result)
        for bad in (tokens[:2] + tokens[3:], tokens + [token('東',1093,514)],
                    [*tokens[:2], token('南',1093,514), *tokens[3:]],
                    tokens[:4] + tokens[5:]):
            with self.subTest(bad=bad):
                incomplete = self.parse(bad)['rightLayoutObservation']
                self.assertNotIn('scoresByObservedWind', incomplete)
                self.assertFalse(incomplete['complete'])
        zero = self.parse(tokens[:-1] + [token('0',1047,419)])['rightLayoutObservation']
        self.assertEqual(zero['positions']['right']['score'], 0)

    def test_alternate_right_score_layout_is_only_an_unverified_hypothesis(self):
        tokens = self.tokens('south')
        no_opposite = [t for t in tokens if not (abs(t['x'] - 958) <= 24 and abs(t['y'] - 364) <= 20)]
        right = {'text':'35000', 'confidence':.999, 'x':1047, 'y':419}
        result = self.parse(no_opposite + [right])
        self.assertFalse(result['verified'])
        self.assertEqual(result['reason'], 'unsupported_right_opponent_layout')
        self.assertEqual(result['layoutCandidate'], {'opponents':['left','right'], 'verified':False})
        self.assertNotIn('candidate', result)
        self.assertNotIn('layoutCandidate', self.parse(no_opposite + [{**right,'confidence':.9}]))
        self.assertNotIn('layoutCandidate', self.parse(no_opposite))
