"""Replay real sanma selection captures through the production click routine."""
import unittest
from pathlib import Path
from unittest.mock import Mock, call

from auto_operator import SelectionStateUncertainAbort, load_json, send_discard_click


ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / 'artifacts/sanma-manual-e48c562-20261031/actions'
BEFORE = IMAGES / '2026-10-30T16-07-32-642Z-before.png'
SELECTED = IMAGES / '2026-10-30T16-07-32-642Z-after.png'


@unittest.skipUnless(BEFORE.exists() and SELECTED.exists(), 'saved sanma selection captures unavailable')
class SanmaDiscardExecutionEvidence(unittest.TestCase):
    def setUp(self):
        self.before = BEFORE.read_bytes()
        self.selected = SELECTED.read_bytes()
        self.layout = load_json(ROOT / 'config/layout-runtime.json')
        self.mouse = Mock()
        self.wait = Mock()
        self.guard = Mock()
        self.point = {'x': 1215, 'y': 1000}

    def execute(self, index, receipt):
        return send_discard_click(self.mouse, self.point, self.layout['viewport'], self.wait,
                                  self.before, lambda first_click_at: receipt,
                                  self.layout, index, 5, self.guard)

    def test_real_selection_is_confirmed_at_the_observed_lifted_tile(self):
        result = self.execute(10, self.selected)
        self.assertEqual(result['lift'], 48.0)
        self.assertEqual(self.mouse.click.call_args_list, [call(1215, 1000), call(1215.0, 952.0, delay=80)])
        self.guard.assert_called_once_with()

    def test_unchanged_frame_or_wrong_slot_never_gets_confirmation_click(self):
        for index, receipt in ((10, self.before), (9, self.selected)):
            with self.subTest(index=index):
                self.mouse.reset_mock()
                self.guard.reset_mock()
                with self.assertRaises(SelectionStateUncertainAbort):
                    self.execute(index, receipt)
                self.assertEqual(self.mouse.click.call_args_list, [call(1215, 1000)])
                self.guard.assert_not_called()

    def test_failed_deadline_guard_withholds_second_click(self):
        self.guard.side_effect = RuntimeError('deadline exceeded')
        with self.assertRaises(SelectionStateUncertainAbort):
            self.execute(10, self.selected)
        self.assertEqual(self.mouse.click.call_args_list, [call(1215, 1000)])


if __name__ == '__main__':
    unittest.main()
