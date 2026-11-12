import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from sanma_friend_discard_experiment import (DiscardPreclickBudgetExpired,
    friend_discard_reserve_guard, execute_friend_discard)
from test_sanma_friend_discard_experiment import FriendDiscardExperimentTests

class Reserve199Tests(FriendDiscardExperimentTests):
    def test_199_logged_attempt_age_exceeds_new_reserve(self):
        log=Path('/home/yama1/server/data/dev-work/jantama/evidence199/operator.log')
        if not log.exists():self.skipTest('evidence199 unavailable')
        rows=[json.loads(s) for s in log.read_text().splitlines() if s.startswith('{')]
        expired=next(x for x in rows if x.get('event')=='sanma_friend_click_budget_expired')
        attempts=[x for x in rows if x.get('event')=='sanma_friend_discard_experiment' and x.get('status')=='attempted']
        attempted=attempts[-1]
        elapsed=(datetime.fromisoformat(expired['timestamp'])-datetime.fromisoformat(attempted['timestamp'])).total_seconds()*1000
        # Attempted event is just before first mouse input. Wall-time
        # reconstruction does not establish the earlier reserve-check age.
        at_attempt=expired['captureAgeMs']-elapsed
        self.assertGreater(at_attempt,6000)
        self.assertLess(at_attempt,8000)
        logger=Mock()
        with self.assertRaises(DiscardPreclickBudgetExpired):
            execute_friend_discard(self.page,**{**self.kwargs,
                'preclick_budget_reserve_guard':lambda:friend_discard_reserve_guard(0,8000,logger,clock=lambda:at_attempt/1000)})
        self.page.mouse.click.assert_not_called()
        self.assertEqual(logger.call_args.args[0],'sanma_friend_click_budget_reserve_insufficient')

    @patch('sanma_friend_discard_experiment.send_discard_click')
    def test_sufficient_reserve_allows_unchanged_path(self, send):
        send.return_value={}
        latch=Mock()
        result=execute_friend_discard(self.page,**{**self.kwargs,'before_click':latch,
            'preclick_budget_reserve_guard':lambda:friend_discard_reserve_guard(0,8000,Mock(),clock=lambda:5.5)})
        self.assertEqual(result['status'],'selection_confirmed')
        latch.assert_called_once();send.assert_called_once()

    @patch('sanma_friend_discard_experiment.send_discard_click')
    def test_insufficient_reserve_never_latches_or_clicks(self, send):
        latch=Mock()
        with self.assertRaises(DiscardPreclickBudgetExpired):
            execute_friend_discard(self.page,**{**self.kwargs,'before_click':latch,
                'preclick_budget_reserve_guard':lambda:friend_discard_reserve_guard(0,8000,Mock(),clock=lambda:6.001)})
        latch.assert_not_called();send.assert_not_called()

    @patch('sanma_friend_discard_experiment.send_discard_click')
    def test_revoked_session_still_blocks_before_reserve_or_input(self,send):
        reserve=Mock()
        with self.assertRaisesRegex(RuntimeError,'friend session revoked'):
            execute_friend_discard(self.page,**{**self.kwargs,'session_check':lambda:False,'preclick_budget_reserve_guard':reserve})
        reserve.assert_not_called();send.assert_not_called()

    @patch('sanma_friend_discard_experiment.send_discard_click')
    def test_reserve_log_failure_is_terminal_without_input(self,send):
        logger=Mock(side_effect=OSError('disk full'));latch=Mock()
        with self.assertRaisesRegex(OSError,'disk full'):
            execute_friend_discard(self.page,**{**self.kwargs,'before_click':latch,
                'preclick_budget_reserve_guard':lambda:friend_discard_reserve_guard(0,8000,logger,clock=lambda:6.5)})
        latch.assert_not_called();send.assert_not_called()

    def test_reserve_clock_crosses_boundary_and_backwards_clock_is_rejected(self):
        clock=Mock(side_effect=[5.999,6.001])
        with self.assertRaisesRegex(RuntimeError,'insufficient time'):
            friend_discard_reserve_guard(0,8000,Mock(),clock=clock)
        clock=Mock(side_effect=[1,-1])
        with self.assertRaisesRegex(RuntimeError,'timestamp invalid'):
            friend_discard_reserve_guard(0,8000,Mock(),clock=clock)

    @patch('sanma_friend_discard_experiment.send_discard_click')
    def test_ranked_session_blocked_before_reserve(self,send):
        reserve=Mock()
        with self.assertRaisesRegex(ValueError,'reviewed CPU friend'):
            execute_friend_discard(self.page,**{**self.kwargs,'session':{**self.session,'ranked':True},
                                               'preclick_budget_reserve_guard':reserve})
        reserve.assert_not_called();send.assert_not_called()

    def test_future_or_invalid_clock_never_qualifies(self):
        for start,budget,now in [(10,8000,9),(0,0,1),(0,True,1)]:
            with self.subTest(start=start,budget=budget,now=now),self.assertRaises((RuntimeError,ValueError)):
                friend_discard_reserve_guard(start,budget,Mock(),clock=lambda:now)
