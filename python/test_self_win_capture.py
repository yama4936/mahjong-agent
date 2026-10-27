"""Regression coverage for yaku animation evidence, without live gameplay."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from auto_operator import PythonAutoOperator


class SelfWinCaptureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.operator = PythonAutoOperator.__new__(PythonAutoOperator)
        self.operator.frames = Path(self.directory.name)
        self.operator.log = Mock()
        self.operator.layout = {}
        self.page = Mock()

    def test_own_ron_preserves_later_yaku_frames_without_clicking(self):
        with patch('auto_operator.time.monotonic', return_value=10):
            self.operator.start_self_win_capture('ron')
        self.page.screenshot.side_effect = [b'animation-without-yaku', b'visible-yaku-and-points']
        with patch('auto_operator.classify_screen', return_value=('round_result', 1)), \
                patch('auto_operator.time.monotonic', side_effect=[11, 16, 26]):
            self.assertTrue(self.operator.capture_self_win_result(self.page))
            self.assertTrue(self.operator.capture_self_win_result(self.page))
            self.assertFalse(self.operator.capture_self_win_result(self.page))
        events = [c.kwargs for c in self.operator.log.call_args_list if c.args[0] == 'self_win_frame']
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]['winId'], events[1]['winId'])
        self.assertEqual(Path(events[1]['evidence']['screenshot']).read_bytes(), b'visible-yaku-and-points')
        self.page.mouse.click.assert_not_called()
        self.assertIsNone(self.operator.self_win_capture)

    def test_opponent_win_does_not_create_self_win_record(self):
        self.assertFalse(self.operator.capture_self_win_result(self.page))
        self.page.screenshot.assert_not_called()
        self.operator.log.assert_not_called()

    def test_new_live_hand_releases_capture_without_saving_wrong_hand(self):
        with patch('auto_operator.time.monotonic', return_value=10):
            self.operator.start_self_win_capture('tsumo')
        self.operator.self_win_capture['sawOverlay'] = True
        with patch('auto_operator.time.monotonic', return_value=12), \
                patch('auto_operator.classify_screen', return_value=('match', 1)), \
                patch('auto_operator.closed_concealed_row_visible', return_value=True), \
                patch('auto_operator.round_result_conflicts_with_live_table', return_value={'live': True}):
            self.assertFalse(self.operator.capture_self_win_result(self.page))
        self.assertEqual(list(self.operator.frames.iterdir()), [])
        self.page.wait_for_timeout.assert_not_called()

    def test_capture_failure_does_not_repeat_win(self):
        self.operator.start_self_win_capture('ron')
        self.page.screenshot.side_effect = RuntimeError('capture failed')
        self.assertFalse(self.operator.capture_self_win_result(self.page))
        self.assertIsNone(self.operator.self_win_capture)
        self.page.mouse.click.assert_not_called()

    def test_final_result_is_saved_and_releases_capture(self):
        self.operator.start_self_win_capture('tsumo')
        self.page.screenshot.return_value = b'final'
        with patch('auto_operator.classify_screen', return_value=('match_result', 1)):
            self.assertFalse(self.operator.capture_self_win_result(self.page))
        self.assertEqual(len(list(self.operator.frames.iterdir())), 1)
        self.assertFalse(self.operator.capture_self_win_result(self.page))


if __name__ == '__main__':
    unittest.main()
