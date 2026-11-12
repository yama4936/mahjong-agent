import copy
import json
import unittest
from pathlib import Path

from sanma_friend_shape_candidate import friend_shape_candidate


class RedTieBreakTests(unittest.TestCase):
    def setUp(self):
        # Start from the saved observation's complete receipt geometry. The
        # two five labels and candidate scores below are synthetic: these
        # tests do not claim that this exact hand occurred in that match.
        self.receipt = json.loads((Path(__file__).parent / 'fixtures/sanma-dd-shape-receipt.json').read_text())
        hand = self.receipt['sourceObservation']['report']['hand']['value']['tiles']
        hand[10] = '0s'
        rows = self.receipt['structuralPositions']['candidates']
        five = next(row for row in rows if row['tile'] == '5s')
        red = copy.deepcopy(five)
        red['tile'] = '0s'
        red['positions'] = [p for p in five['positions'] if p['index'] == 10]
        five['positions'] = [p for p in five['positions'] if p['index'] == 11]
        rows.append(red)
        for row in rows:
            row['shanten'] = 0 if row['tile'] in ('0s', '5s') else 2

    def test_same_shape_preserves_red(self):
        self.assertEqual(friend_shape_candidate(self.receipt)['tile'], '5s')

    def test_better_shape_still_wins_over_red_tiebreak(self):
        rows = self.receipt['structuralPositions']['candidates']
        next(row for row in rows if row['tile'] == '5s')['shanten'] = 1
        self.assertEqual(friend_shape_candidate(self.receipt)['tile'], '0s')

    def test_better_acceptance_still_wins_over_red_tiebreak(self):
        rows = self.receipt['structuralPositions']['candidates']
        plain = next(row for row in rows if row['tile'] == '5s')
        plain['improvingDraws'][0]['maximumUnseen'] -= 1
        plain['maximumUnseenTotal'] -= 1
        self.assertEqual(friend_shape_candidate(self.receipt)['tile'], '0s')

    def test_red_pinzu_is_also_preserved(self):
        hand = self.receipt['sourceObservation']['report']['hand']['value']['tiles']
        hand[10:12] = ['0p', '5p']
        for row in self.receipt['structuralPositions']['candidates']:
            if row['tile'] in ('0s', '5s'):
                row['tile'] = row['tile'][0] + 'p'
        self.assertEqual(friend_shape_candidate(self.receipt)['tile'], '5p')

    def test_real_observation_red_tie_when_available(self):
        path = Path('/home/yama1/server/data/dev-work/jantama/evidence181/retry-artifacts/frames/2026-11-08T12-04-03.646509+00-00.3b855717d217494fb85b4c7ad0959e76.sanma-self-turn.receipt.json')
        if not path.is_file():
            self.skipTest('locally retained observation unavailable')
        receipt = json.loads(path.read_text())
        rows = receipt['structuralPositions']['candidates']
        old = min(rows, key=lambda row: (row['shanten'], -row['maximumUnseenTotal'], row['tile']))
        self.assertEqual((old['tile'], old['shanten'], old['maximumUnseenTotal']), ('0p', 3, 16))
        selected = friend_shape_candidate(receipt)
        self.assertEqual((selected['tile'], selected['shanten'], selected['improvingDrawUpperBound']), ('3p', 3, 16))


if __name__ == '__main__':
    unittest.main()
