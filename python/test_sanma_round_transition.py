import unittest
from sanma_round_transition import possible_sanma_hand_transition as possible


def snapshot(round_name='east_1', seat='west', honba=0, verified=True):
    return dict(round=round_name, seat=seat, honba=honba, verified=verified)


class SanmaRoundTransitionTest(unittest.TestCase):
    def check(self, before, after, **kwargs):
        return possible(before, after, **{'same_match_verified': True,
            'exactly_one_hand_verified': True, 'match_length': 'east', **kwargs})

    def test_dealer_continuation_requires_same_seat_and_increment(self):
        before = snapshot(honba=2)
        self.assertTrue(self.check(before, snapshot(honba=3)))
        for after in (snapshot(honba=2), snapshot(honba=4), snapshot(seat='south', honba=3)):
            self.assertFalse(self.check(before, after))

    def test_rotation_matches_real_frame_seats_and_honba_cases(self):
        before = snapshot('east_1', 'west', 0)
        self.assertTrue(self.check(before, snapshot('east_2', 'south', 0)))
        self.assertTrue(self.check(before, snapshot('east_2', 'south', 1)))
        self.assertFalse(self.check(before, snapshot('east_2', 'east', 0)))
        self.assertFalse(self.check(before, snapshot('east_2', 'south', 2)))
        self.assertTrue(self.check(snapshot('east_2', 'south', 1), snapshot('east_3', 'east', 2)))
        self.assertFalse(self.check(snapshot('east_2', 'south', 0), snapshot('east_3', 'east', 2)))

    def test_cross_wind_and_terminal_conservatism(self):
        before, after = snapshot('east_3', 'east'), snapshot('south_1', 'west')
        self.assertFalse(self.check(before, after))
        self.assertTrue(self.check(before, after, match_length='south'))
        self.assertFalse(self.check(snapshot('south_3', 'east'), snapshot('west_1', 'west'), match_length='south'))
        self.assertFalse(self.check(snapshot('east_1'), snapshot('east_3', 'east')))

    def test_unknown_unverified_or_bad_inputs_rejected(self):
        before, after = snapshot(), snapshot('east_2', 'south')
        for kwargs in ({'same_match_verified': False}, {'exactly_one_hand_verified': False},
                       {'match_length': 'unknown'}, {'same_match_verified': 1}):
            self.assertFalse(self.check(before, after, **kwargs))
        for bad in (None, {}, snapshot(verified=False), snapshot(honba=True), snapshot(honba=-1),
                    snapshot('east_4'), snapshot(seat='north'), snapshot('east_01')):
            self.assertFalse(self.check(bad, after))
            self.assertFalse(self.check(before, bad))

    def test_same_values_are_only_structural_and_require_independent_verification(self):
        before, after = snapshot(), snapshot('east_2', 'south')
        self.assertFalse(self.check(before, after, exactly_one_hand_verified=False))
        self.assertFalse(self.check(before, after, same_match_verified=False))

    def test_hand_labeled_observed_transitions_are_structurally_possible(self):
        # Hand labels from saved frames only; the booleans here are explicit
        # test assumptions, not independent proof of match/hand continuity.
        observed_pairs = (
            (snapshot('east_1', 'west', 0), snapshot('east_2', 'south', 0)),
            (snapshot('east_2', 'south', 0), snapshot('east_2', 'south', 1)),
            (snapshot('east_2', 'south', 1), snapshot('east_3', 'east', 2)),
        )
        for before, after in observed_pairs:
            with self.subTest(before=before, after=after):
                self.assertTrue(self.check(before, after))
                self.assertFalse(self.check(before, after, exactly_one_hand_verified=False))
