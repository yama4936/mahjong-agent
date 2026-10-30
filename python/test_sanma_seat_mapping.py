import unittest
from board_metadata import remap_seats, sanma_seats_by_screen_position


class SanmaSeatMappingTests(unittest.TestCase):
    def test_all_observed_own_winds(self):
        expected = {
            'east': {'own': 'east', 'left': 'west', 'opposite': 'south'},
            'south': {'own': 'south', 'left': 'east', 'opposite': 'west'},
            'west': {'own': 'west', 'left': 'south', 'opposite': 'east'},
        }
        for seat, positions in expected.items():
            with self.subTest(seat=seat):
                result = sanma_seats_by_screen_position(seat)
                self.assertEqual(result, positions)
                self.assertEqual(set(result.values()), {'east', 'south', 'west'})
                self.assertNotIn('right', result)

    def test_invalid_own_seat_is_rejected(self):
        for seat in ('north', '', 'E', 'East', None, [], 0):
            with self.subTest(seat=seat), self.assertRaises(ValueError):
                sanma_seats_by_screen_position(seat)

    def test_yonma_remapping_remains_four_seat(self):
        self.assertEqual(remap_seats([{'seat': 'east'}, {'seat': 'south'}], 'west', 'south'),
                         [{'seat': 'north'}, {'seat': 'east'}])
        self.assertEqual(sanma_seats_by_screen_position('south')['opposite'], 'west')
