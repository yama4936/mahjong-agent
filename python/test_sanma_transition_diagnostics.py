import unittest
from unittest.mock import Mock
from sanma_transition_diagnostics import capture_unresolved_discard

class TransitionDiagnosticTest(unittest.TestCase):
    def setUp(self):
        self.op=Mock(); self.op.verified_friend_300_active=True
        self.op.args.action_deadline_ms=300000
        self.op.inspect_sanma_self_turn.side_effect=[
            {'screenshot':'/x/first.png','digest':'first'},
            {'screenshot':'/x/second.png','digest':'second'}]
        self.watch=Mock(); self.watch.alive.return_value=True
        self.recovery={'watch':self.watch,'started':100.0}
        self.page=Mock()
    def run_capture(self,now=lambda:101):
        return capture_unresolved_discard(self.op,self.page,self.recovery,now=now)
    def test_two_observations_no_action(self):
        self.assertIsNone(self.run_capture())
        self.assertEqual(self.op.inspect_sanma_self_turn.call_count,2)
        self.page.assert_not_called()
        self.op.execute_sanma_friend_tsumo_candidate.assert_not_called()
        self.op.execute_sanma_friend_discard_candidate.assert_not_called()
        self.assertEqual([c.args[0] for c in self.op.log.call_args_list],['sanma_friend_transition_diagnostic_observed']*2)
        self.assertTrue(all(c.kwargs['operationAuthorized'] is False for c in self.op.log.call_args_list))
    def test_revoked_expired_invalid_deadline_or_monitor(self):
        for which in ('revoked','expired','deadline','monitor'):
            self.setUp()
            if which=='revoked': self.op.verified_friend_300_active=False
            if which=='deadline': self.op.args.action_deadline_ms=8000
            if which=='monitor': self.watch.alive.return_value=False
            self.run_capture(now=(lambda:401 if which=='expired' else 101))
            self.op.inspect_sanma_self_turn.assert_not_called()
            self.assertEqual(self.op.log.call_args.args[0],'sanma_friend_transition_diagnostic_stopped')
    def test_revoked_during_first_observation(self):
        self.watch.alive.side_effect=[True,False]
        self.run_capture()
        self.assertEqual(self.op.inspect_sanma_self_turn.call_count,1)
        self.assertFalse(self.op.log.call_args_list[0].kwargs['sessionValid'])
    def test_failure_stops_without_propagating(self):
        self.op.inspect_sanma_self_turn.side_effect=ValueError('broken')
        self.assertIsNone(self.run_capture())
        self.assertEqual(self.op.log.call_args.kwargs['reason'],'observation_failed')

if __name__=='__main__': unittest.main()
