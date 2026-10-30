import unittest
from board_metadata import validate_sanma_board_consistency


class SanmaBoardConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.board = {'seat': 'east', 'round': 'east_3', 'scores': {
            'east': 35000, 'south': 35000, 'west': 35000},
            'riichiSticks': 0, 'honba': 0}

    def check(self, board=None, total=105000, phase='settled'):
        return validate_sanma_board_consistency(self.board if board is None else board,
                                               expected_total_points=total, payment_phase=phase)

    def test_explicit_total_and_conserved_stick_payment(self):
        self.assertTrue(self.check()['consistent'])
        after = {**self.board, 'scores': {'east': 34000, 'south': 35000, 'west': 35000}, 'riichiSticks': 1}
        self.assertTrue(self.check(after)['consistent'])
        self.assertFalse(self.check({**after, 'riichiSticks': 0})['consistent'])
        self.assertFalse(self.check(after, total=100000)['consistent'])
        self.assertFalse(self.check(after, total=None)['consistent'])
        self.assertFalse(self.check(after, phase=None)['consistent'])
        self.assertFalse(self.check(after, phase='in_flight')['consistent'])

    def test_explicit_room_total_and_negative_score(self):
        board = {**self.board, 'scores': {'east': -1000, 'south': 50000, 'west': 56000}}
        self.assertTrue(self.check(board)['consistent'])
        self.assertTrue(self.check(self.board, total=105000)['consistent'])
        self.assertFalse(self.check(self.board, total=100000)['consistent'])

    def test_reject_missing_or_ambiguous_state(self):
        for invalid in ({'seat': 'north'}, {'round': 'east_4'}, {'round': 'unknown'},
                        {'scores': {'east': 35000, 'south': 35000}},
                        {'scores': {'east': 35000, 'south': 35000, 'west': 35000, 'north': 0}},
                        {'riichiSticks': None}, {'honba': True}):
            with self.subTest(invalid=invalid):
                self.assertFalse(self.check({**self.board, **invalid})['consistent'])
