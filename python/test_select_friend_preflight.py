import unittest
from pathlib import Path
from unittest.mock import patch

from select_friend_preflight import select_preflight_candidate


class SelectFriendPreflightTest(unittest.TestCase):
    def test_selects_original_image_with_two_adjacent_peers(self):
        frames = [b'particle', b'stable1', b'stable2', b'stable3']
        def compare(a, b, *, sanma):
            return sanma and a.startswith(b'stable') and b.startswith(b'stable')
        with patch('select_friend_preflight.verified_friend_room', side_effect=compare):
            index, matches = select_preflight_candidate(frames, sanma=True)
        self.assertEqual(index, 1)
        self.assertEqual(matches, [2, 3])

    def test_nonadjacent_and_fewer_than_three_fail(self):
        frames = [b'yes', b'no', b'candidate', b'no', b'yes']
        def compare(a, b, *, sanma):
            return a in (b'yes', b'candidate') and b in (b'yes', b'candidate')
        with patch('select_friend_preflight.verified_friend_room', side_effect=compare):
            with self.assertRaises(ValueError): select_preflight_candidate(frames, sanma=True)
        with self.assertRaises(ValueError): select_preflight_candidate([b'one', b'two'], sanma=True)

    def test_real_room_burst_selects_candidate_with_consecutive_matches(self):
        directory = Path('/home/yama1/.codex/sanma-run-ba2a797-20261031/retry/frames')
        paths = sorted(directory.glob('*friend-start*'))[:8]
        if len(paths) != 8: self.skipTest('saved friend captures unavailable')
        index, matches = select_preflight_candidate([p.read_bytes() for p in paths], sanma=True)
        self.assertIn(index, [0, 2, 3, 5, 7])
        self.assertTrue(any(j + 1 in matches for j in matches))
