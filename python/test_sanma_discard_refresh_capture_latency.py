"""Offline refresh timing regressions through the real select/confirm sender."""
import unittest
from unittest.mock import call, patch

import test_sanma_friend_discard_experiment as fixtures
from sanma_friend_discard_experiment import execute_friend_discard


class RefreshCaptureLatencyTests(unittest.TestCase):
    setUp = fixtures.FriendDiscardBaselineRefreshTests.setUp

    def execute_with_capture_delays(self, delays):
        now = [101.0]
        capture_starts = []
        frames = iter((self.candidate, self.confirmation, self.confirmation))
        delays = iter(delays)

        def capture(**kwargs):
            capture_starts.append(now[0])
            frame = next(frames)
            now[0] += next(delays)
            return frame

        def glyph(before, after, report, diagnostic=None, **kwargs):
            return fixtures.FriendDiscardBaselineRefreshTests._fail_at_binary_frame(diagnostic)

        self.page.screenshot.side_effect = capture
        self.capture_starts = capture_starts
        # These synthetic images exercise real refresh guards/evidence and the
        # sender. Only tile recognition is supplied; no browser is contacted.
        with patch('sanma_friend_self_turn_stability.self_turn_stability', return_value=False), \
                patch('auto_operator.raised_closed_hand_slots', return_value=[]), \
                patch('auto_operator.closed_hand_face_mismatches', return_value=[]), \
                patch('auto_operator.experimental_draw_glyph_stability', side_effect=glyph), \
                patch('auto_operator.raised_tile_confirmation_point', return_value={'x': 200, 'y': 950}):
            return execute_friend_discard(self.page, **{**self.kwargs, 'clock': lambda: now[0]})

    def test_each_preinput_capture_transport_stall_blocks_all_clicks(self):
        for delays in ((99, 0, 0), (0, 99, 0)):
            with self.subTest(delays=delays):
                self.page.reset_mock()
                with self.assertRaisesRegex(RuntimeError, 'freshness expired'):
                    self.execute_with_capture_delays(delays)
                self.page.mouse.click.assert_not_called()

    def test_refresh_capture_does_not_renew_original_candidate_age(self):
        with self.assertRaisesRegex(RuntimeError, 'freshness expired'):
            self.execute_with_capture_delays((3, 3, 0))
        self.page.mouse.click.assert_not_called()

    def test_selection_capture_does_not_renew_refresh_chain_age(self):
        with self.assertRaisesRegex(RuntimeError, 'freshness expired'):
            self.execute_with_capture_delays((2, 2, 2))
        self.assertEqual(self.page.mouse.click.call_args_list, [call(200, 1000)])

    def test_backward_refresh_capture_clock_blocks_all_clicks(self):
        with self.assertRaisesRegex(RuntimeError, 'freshness expired'):
            self.execute_with_capture_delays((3, -1, 0))
        self.page.mouse.click.assert_not_called()

    def test_fresh_refresh_chain_reaches_both_mouse_clicks_and_records_starts(self):
        result = self.execute_with_capture_delays((1, 1, 1))
        self.assertEqual(result['status'], 'selection_confirmed')
        self.assertEqual(self.page.mouse.click.call_args_list,
                         [call(200, 1000), call(200, 950, delay=80)])
        refreshed = next(event for event in self.logs
                         if event['kind'] == 'sanma_discard_baseline_refreshed')
        self.assertEqual(self.capture_starts, [101, 102, 103])
        self.assertEqual(refreshed['baselineCaptureStartedAtMonotonic'], 101)
        self.assertEqual(refreshed['confirmationCaptureStartedAtMonotonic'], 102)
        self.assertEqual(refreshed['baselineCapturedAtMonotonic'], 102)
        self.assertEqual(refreshed['confirmationCapturedAtMonotonic'], 103)
        self.assertEqual(refreshed['evidence']['candidate']['capturedAtMonotonic'], 102)
        self.assertEqual(refreshed['evidence']['confirmation']['capturedAtMonotonic'], 103)


if __name__ == '__main__':
    unittest.main()
