import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from auto_operator import PythonAutoOperator

class TransitionGapTest(unittest.TestCase):
    def test_unrecognized_screen_breaks_stability_for_discard_and_pass(self):
        for action, gap in ((action, gap) for action in ('discard', 'pass_pon') for gap in (('unknown', .2), ('match', .94))):
            with self.subTest(action=action, gap=gap), tempfile.TemporaryDirectory(dir='/home/yama1/.codex') as folder:
                op = object.__new__(PythonAutoOperator)
                op.frames = Path(folder)
                op.verified_friend_300_active = True
                op.screen_references = {}
                op.hand_clip = {'x': 1, 'y': 1, 'width': 1, 'height': 1}
                op.river_clip = {'x': 2, 'y': 2, 'width': 1, 'height': 1}
                before = b'before'; after = b'after'; unknown = b'unknown'
                path = op.frames / 'before.png'; path.write_bytes(before)
                page = Mock()
                page.screenshot.side_effect = [after, unknown] * 10
                receipt = {'screenshot': str(path), 'digest': hashlib.sha256(before).hexdigest()}
                states = [('match', 1.0), gap] * 10
                with patch('auto_operator.classify_screen', side_effect=states), \
                     patch('auto_operator.experimental_friend_score_transfer_candidate', return_value=False), \
                     patch('auto_operator.crop_screenshot', side_effect=lambda data, _: data), \
                     patch('auto_operator.mean_pixel_delta', side_effect=lambda x,y: 0 if x == y else 2), \
                     patch('auto_operator.friend_frame_stable', return_value=True):
                    result = op.observe_sanma_friend_transition(page, receipt, action)
                self.assertEqual(result['status'], 'unresolved')
                self.assertEqual(page.screenshot.call_count, 20)
                page.mouse.click.assert_not_called()

if __name__ == '__main__': unittest.main()
