"""Offline recovery-loop bounds; no browser or live match is used."""
import unittest
from unittest.mock import Mock, patch

import test_experimental_sanma_friend_loop as fixtures


class RecoveryDeadline187Test(unittest.TestCase):
    def run_recovery(self, freshness, elapsed=300.0, invalid=False, revoked=False):
        case = fixtures.ExperimentalSanmaFriendLoopTest('runTest')
        case.setUp()
        self.addCleanup(case.doCleanups)
        op, page = case.op, case.page
        op.args.max_iterations = 4
        op.verified_friend_300_active = True
        now = [100.0]
        watch = Mock()
        watch.alive.return_value = True
        watch.diagnostic.return_value = {'reason': 'Network.webSocketClosed' if invalid else None}

        def capture(**kwargs):
            now[0] += 1
            return b'match screenshot'

        def inspect(*args, **kwargs):
            index = op.inspect_sanma_self_turn.call_count
            if index == 4:
                now[0] = op._sanma_friend_resume_guard[1] + elapsed
                watch.alive.return_value = not invalid
                op.verified_friend_300_active = not revoked
            return {'digest': str(index), 'screenshot': f'{index}.png',
                    'drawCandidate': {'status': 'candidate'},
                    'candidates': {'candidates': [{'action': 'kita'}] if index >= 3 else []},
                    'freshness': {'status': freshness if index == 4 else 'changed' if index == 3
                                  else 'identical_pixels_candidate'}}

        def transition(*args, **kwargs):
            now[0] += 1
            return {'status': 'visual_change_unconfirmed', 'confirmed': False}

        page.screenshot.side_effect = capture
        op.inspect_sanma_self_turn.side_effect = inspect
        op.observe_sanma_friend_transition.side_effect = transition
        result = {'status': 'selection_confirmed', 'result': 'discard_not_verified',
                  'tile': 'S', 'clickIndex': 13, 'clickPoint': {'x': 1532, 'y': 996.5},
                  'frameSha256': '1'}
        with patch('auto_operator.time.monotonic', side_effect=lambda: now[0]), \
             patch('auto_operator.classify_screen', return_value=('match', 1.0)), \
             patch('sanma_friend_discard_recovery.MatchContinuity', return_value=watch), \
             patch('sanma_friend_discard_recovery.candidate', return_value=True), \
             patch('sanma_friend_discard_experiment.execute_friend_draw_candidate', return_value=result) as discard:
            op.run_experimental_sanma_friend(page)
        self.assertEqual(discard.call_count, 1)
        self.assertEqual(op.inspect_sanma_self_turn.call_count, 4)
        op.execute_sanma_friend_kita_candidate.assert_not_called()
        page.mouse.click.assert_not_called()
        self.assertTrue(any(c.args[0] == 'sanma_friend_discard_recovery_candidate' for c in op.log.call_args_list))
        self.assertIsNone(op._sanma_friend_resume_guard)
        watch.close.assert_called()
        return op.log.call_args_list

    def test_original_deadline_blocks_changed_and_stable_kita(self):
        for freshness in ('changed', 'stable_kita_glyph_candidate'):
            for elapsed in (300.0, 315.0):
                with self.subTest(freshness=freshness, elapsed=elapsed):
                    events = self.run_recovery(freshness, elapsed)
                    stopped = next(c.kwargs for c in events if c.kwargs.get('reason') == 'discard_recovery_session_or_deadline')
                    self.assertEqual(stopped['deadlineElapsedMs'], round(elapsed * 1000))
                    self.assertEqual(stopped['actionDeadlineMs'], 300000)
                    self.assertEqual(stopped['screenshot'], '4.png')
                    self.assertEqual(stopped['stage'], 'before_freshness_reobserve')
                    self.assertFalse(stopped['operationAuthorized'])
                    self.assertFalse(any(c.kwargs.get('reason') == 'observation_changed_reobserve'
                                         and c.kwargs.get('screenshot') == '4.png' for c in events))

    def test_continuity_loss_blocks_changed_reobservation(self):
        events = self.run_recovery('changed', 299.999, invalid=True)
        stopped = next(c.kwargs for c in events if c.kwargs.get('reason') == 'discard_recovery_session_changed')
        self.assertEqual(stopped['continuity']['reason'], 'Network.webSocketClosed')
        self.assertEqual(stopped['screenshot'], '4.png')

    def test_revoked_friend_session_blocks_changed_reobservation(self):
        events = self.run_recovery('changed', 299.999, revoked=True)
        stopped = next(c.kwargs for c in events if c.kwargs.get('reason') == 'discard_recovery_session_or_deadline')
        self.assertFalse(stopped['friendSessionActive'])

    def test_unexpired_kita_still_requires_review(self):
        events = self.run_recovery('stable_kita_glyph_candidate', 299.999)
        self.assertTrue(any(c.kwargs.get('reason') == 'discard_recovery_action_requires_review' for c in events))
        self.assertFalse(any(c.kwargs.get('reason') == 'discard_recovery_session_or_deadline' for c in events))

    def test_unexpired_changed_receipt_can_reobserve(self):
        events = self.run_recovery('changed', 299.999)
        self.assertTrue(any(c.kwargs.get('reason') == 'observation_changed_reobserve'
                            and c.kwargs.get('screenshot') == '4.png' for c in events))
