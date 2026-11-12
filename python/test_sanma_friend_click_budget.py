import hashlib
import unittest
from unittest.mock import Mock, patch

from auto_operator import SelectionStateUncertainAbort
from sanma_friend_discard_experiment import (execute_friend_discard, friend_discard_budget_guard,
                                              require_friend_discard_timing_binding, DiscardPreclickBudgetExpired,
                                              FriendDiscardBudgetExpired)


class FriendDiscardBudgetTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.frame = b'original-frame'
        self.page = Mock()
        self.page.screenshot.return_value = self.frame
        self.events = []
        self.target = []
        self.session = dict(mode='cpu_friend', rules='sanma', clock='300+0', actionDeadlineMs=300000,
                            ranked=False, cpuCount=2, roomVerified=True)
        self.point = dict(x=300, y=1000)
        self.observation = dict(status='candidate', phase='self_turn', promptStatus='none', handStatus='candidate',
                                layoutStatus='candidate', slots=[dict(tile='1m', **self.point)],
                                frameSha256=hashlib.sha256(self.frame).hexdigest(), referenceFrame=self.frame)
        self.plan = dict(scope='offline_untrusted_sanma_discard_plan', operationAuthorized=False,
                         tile='1m', clickIndex=0, clickPoint=self.point)
        self.layout = dict(viewport=dict(width=1920, height=1080))

    def clock(self): return self.now
    def guard(self):
        friend_discard_budget_guard(100, 8000, lambda name, **kw: self.events.append((name, kw)), self.clock)
    def run_discard(self):
        with patch('sanma_friend_discard_experiment.require_sanma_observable_frame'), \
             patch('auto_operator.raised_closed_hand_slots', return_value=[]), \
             patch('auto_operator.raised_tile_confirmation_point', return_value={'x':300, 'y':950}):
            return execute_friend_discard(self.page, session=self.session, observation=self.observation,
                     plan=self.plan, layout=self.layout, log=self.events.append, turn_started_monotonic=100,
                     clock=self.clock, click_budget_guard=self.guard,
                     before_click=lambda: self.target.append('latched'))

    def test_valid_observation_to_both_clicks(self):
        self.now = 101
        self.assertEqual(self.run_discard()['status'], 'selection_confirmed')
        self.assertEqual(self.page.mouse.click.call_count, 2)
        self.assertEqual(self.target, ['latched'])

    def test_original_observation_expired_never_latches_or_clicks(self):
        self.now = 108
        with self.assertRaisesRegex(DiscardPreclickBudgetExpired, 'budget expired'): self.run_discard()
        self.page.mouse.click.assert_not_called()
        self.assertEqual(self.target, [])

    def test_slow_first_capture_never_clicks(self):
        self.now = 101
        def slow(**kw): self.now = 108; return self.frame
        self.page.screenshot.side_effect = slow
        with self.assertRaisesRegex(DiscardPreclickBudgetExpired, 'budget expired'): self.run_discard()
        self.page.mouse.click.assert_not_called()
        self.assertEqual(self.target, [])

    def test_slow_confirmation_keeps_first_click_unresolved(self):
        self.now = 101
        def capture(**kw):
            if self.page.screenshot.call_count == 2: self.now = 108
            return self.frame
        self.page.screenshot.side_effect = capture
        with self.assertRaises(SelectionStateUncertainAbort): self.run_discard()
        self.assertEqual(self.page.mouse.click.call_count, 1)
        self.assertEqual(self.target, ['latched'])

    def test_error_from_sender_is_never_retried_even_if_budget_typed(self):
        self.now = 101
        with patch('sanma_friend_discard_experiment.send_discard_click', side_effect=FriendDiscardBudgetExpired('unknown input')):
            with self.assertRaises(FriendDiscardBudgetExpired) as error:
                self.run_discard()
        self.assertNotIsInstance(error.exception, DiscardPreclickBudgetExpired)

    def test_missing_or_future_timestamp_rejected(self):
        for stamp in (None, float('nan'), True):
            with self.assertRaises(ValueError): friend_discard_budget_guard(stamp, 8000, Mock(), self.clock)
        with self.assertRaises(RuntimeError): friend_discard_budget_guard(101, 8000, Mock(), self.clock)

    def test_timing_cannot_be_refreshed_by_mutating_or_copying_receipt(self):
        receipt = {'digest':'original', 'captureStartedMonotonic':100}
        op = Mock()
        op._sanma_friend_discard_observation = (receipt, 'original', 100)
        require_friend_discard_timing_binding(op, receipt, 100)
        with self.assertRaises(ValueError): require_friend_discard_timing_binding(op, dict(receipt), 100)
        receipt['captureStartedMonotonic'] = 101
        with self.assertRaises(ValueError): require_friend_discard_timing_binding(op, receipt, 101)
        receipt['captureStartedMonotonic'] = 100
        receipt['digest'] = 'other'
        with self.assertRaises(ValueError): require_friend_discard_timing_binding(op, receipt, 100)
