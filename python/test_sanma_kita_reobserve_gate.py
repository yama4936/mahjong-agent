"""An unsent pre-click rejection may only be revisited within its original clock."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path
import tempfile
from auto_operator import may_reobserve_unsent_kita, PythonAutoOperator, SanmaKitaPreclickChanged


class KitaReobserveGateTest(unittest.TestCase):
    def setUp(self):
        self.op = SimpleNamespace(verified_friend_300_active=True,
                                  args=SimpleNamespace(action_deadline_ms=300000))

    def allowed(self, *, digest='frame', unconfirmed=False, start=100.0, now=101.0):
        return may_reobserve_unsent_kita(self.op, digest, unconfirmed, start, now)

    def test_repeat_is_allowed_before_original_deadline(self):
        for _ in range(10):
            self.assertTrue(self.allowed(now=399.999))
        self.assertFalse(self.allowed(now=400.0))

    def test_unknown_or_invalid_clock_and_revoked_session_stop(self):
        for start, now in [(None, 101), (100, 99), (100, float('nan')), (True, 101)]:
            self.assertFalse(self.allowed(start=start, now=now))
        self.op.verified_friend_300_active = False
        self.assertFalse(self.allowed())

    def test_unconfirmed_input_and_both_latches_stop(self):
        self.assertFalse(self.allowed(unconfirmed=True))
        self.op._sanma_friend_attempted_frames = {'frame'}
        self.assertFalse(self.allowed())
        self.op._sanma_friend_attempted_frames = set()
        self.op._sanma_friend_attempted_targets = {'latched'}
        self.assertFalse(self.allowed())
        self.assertFalse(self.allowed(digest=None))


class KitaReobserveLoopTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        room = Path(self.temp.name) / 'room.png'
        room.write_bytes(b'room')
        self.op = object.__new__(PythonAutoOperator)
        self.op.args = SimpleNamespace(rules='sanma', mode='force-auto', experimental_sanma_friend=True,
            action_deadline_ms=300000, ranked_loop=False, start_reviewed_friend_room=str(room), max_iterations=8)
        self.op.verified_friend_300_active = True
        self.op.frames = Path(self.temp.name)
        self.op.screen_references = {}
        self.op.log = Mock()
        self.page = Mock()
        self.page.screenshot.return_value = b'frame'
        self.receipt = {'candidates': {'candidates': [{'action': 'kita'}]}, 'digest': 'frame', 'screenshot': 'frame'}
        self.op.inspect_sanma_self_turn = Mock(return_value=self.receipt)
        self.op.execute_sanma_friend_kita_candidate = Mock(side_effect=SanmaKitaPreclickChanged('before click'))

    def run_loop(self, states=None):
        with patch('auto_operator.classify_screen', side_effect=states or [('match', 1.0)] * 20), \
             patch('auto_operator.is_blank_white_client_frame', return_value=False):
            self.op.run_experimental_sanma_friend(self.page)

    def test_more_than_three_rejections_keep_original_clock(self):
        self.run_loop()
        self.assertEqual(self.op.execute_sanma_friend_kita_candidate.call_count, 8)
        self.assertEqual(sum(c.args[0] == 'sanma_friend_action_clock_started' for c in self.op.log.call_args_list), 1)
        self.page.mouse.click.assert_not_called()

    def test_result_screen_stops_without_reset_or_advancement(self):
        self.run_loop([('match', 1.0), ('round_result', 1.0)])
        self.assertEqual(self.op.execute_sanma_friend_kita_candidate.call_count, 1)
        self.assertTrue(any(c.kwargs.get('reason') == 'kita_reobserve_screen_changed' for c in self.op.log.call_args_list))
        self.page.mouse.click.assert_not_called()

    def test_original_deadline_expires_during_retry(self):
        clock = [100.0]
        def rejection(*args):
            if self.op.execute_sanma_friend_kita_candidate.call_count == 4:
                clock[0] = 400.0
            raise SanmaKitaPreclickChanged('before click')
        self.op.execute_sanma_friend_kita_candidate.side_effect = rejection
        with patch('auto_operator.time.monotonic', side_effect=lambda: clock[0]):
            self.run_loop()
        self.assertEqual(self.op.execute_sanma_friend_kita_candidate.call_count, 4)
        self.assertTrue(any(c.kwargs.get('reason') == 'kita_preclick_reobserve_limit' for c in self.op.log.call_args_list))
        self.page.mouse.click.assert_not_called()

    def test_candidate_change_stops_without_input(self):
        for choices in ([{'action': 'tsumo'}], [{'action': 'kita'}, {'action': 'tsumo'}],
                        [{'action': 'kita'}, {'action': 'ron'}]):
            with self.subTest(choices=choices):
                changed = {'candidates': {'candidates': choices}, 'digest': 'frame2', 'screenshot': 'frame'}
                self.op.log.reset_mock()
                self.op.inspect_sanma_self_turn.side_effect = [self.receipt, changed]
                self.op.execute_sanma_friend_tsumo_candidate = Mock()
                self.op.execute_sanma_friend_ron_candidate = Mock()
                self.run_loop()
                self.assertTrue(any(c.kwargs.get('reason') == 'kita_reobserve_candidate_changed' for c in self.op.log.call_args_list))
                self.op.execute_sanma_friend_tsumo_candidate.assert_not_called()
                self.op.execute_sanma_friend_ron_candidate.assert_not_called()

    def test_uncertain_input_exception_never_retries(self):
        self.op.execute_sanma_friend_kita_candidate.side_effect = RuntimeError('click attempted; outcome unknown')
        self.run_loop()
        self.assertEqual(self.op.execute_sanma_friend_kita_candidate.call_count, 1)
        self.assertTrue(any(c.kwargs.get('reason') == 'observation_or_action_failed' for c in self.op.log.call_args_list))

    def test_rearmed_kita_retries_only_known_unsent_input(self):
        for cause in ('success', 'deadline', 'revoked', 'target', 'frame', 'non_kita'):
            with self.subTest(cause=cause):
                self.op.args.max_iterations = 4
                self.op.verified_friend_300_active = True
                self.op.log.reset_mock()
                self.op._sanma_friend_attempted_targets = set()
                self.op._sanma_friend_attempted_frames = set()
                self.op._sanma_friend_kita_rearmed = False
                self.op.observe_sanma_friend_transition = Mock(return_value={'status': 'visual_change_unconfirmed'})
                def receipt(digest, actions):
                    return {'candidates': {'candidates': actions}, 'digest': digest,
                            'screenshot': digest, 'drawCandidate': {'status': 'candidate'}}
                first = [] if cause == 'non_kita' else [{'action': 'kita'}]
                self.op.inspect_sanma_self_turn.side_effect = [receipt('first', first),
                    receipt('north1', [{'action':'kita'}]), receipt('north2', [{'action':'kita'}]),
                    receipt('north3', [{'action':'kita'}]), receipt('north4', [{'action':'kita'}])]
                clock = [100.0]
                calls = [0]
                def execute(page, receipt):
                    calls[0] += 1
                    if calls[0] == 1:
                        self.op._sanma_friend_attempted_targets.add('old')
                        self.op._sanma_friend_attempted_frames.add(receipt['digest'])
                        return {}
                    if calls[0] <= 3:
                        if cause == 'deadline': clock[0] = 400.0
                        if cause == 'revoked': self.op.verified_friend_300_active = False
                        if cause == 'target': self.op._sanma_friend_attempted_targets.add('unexpected')
                        if cause == 'frame': self.op._sanma_friend_attempted_frames.add('unexpected')
                        raise SanmaKitaPreclickChanged('before click')
                    return {}
                self.op.execute_sanma_friend_kita_candidate.side_effect = execute
                def rearm(op, before, after):
                    self.assertIn('old', op._sanma_friend_attempted_targets)
                    self.assertFalse(op._sanma_friend_kita_rearmed)
                    op._sanma_friend_attempted_targets.remove('old')
                    op._sanma_friend_kita_rearmed = True
                    return True
                with patch('auto_operator.time.monotonic', side_effect=lambda: clock[0]), \
                     patch('sanma_friend_kita_rearm.rearm_friend_kita_candidate', side_effect=rearm) as rearm_mock, \
                     patch('sanma_friend_discard_experiment.execute_friend_draw_candidate', return_value={}):
                    self.run_loop()
                if cause == 'success':
                    self.assertEqual(calls[0], 4)
                    self.assertEqual(rearm_mock.call_count, 3)
                    self.assertEqual(sum(c.args[0] == 'sanma_friend_action_clock_started' for c in self.op.log.call_args_list), 1)
                else:
                    self.assertEqual(calls[0], 2)
                    self.assertTrue(any(c.kwargs.get('reason') == 'kita_preclick_reobserve_limit' for c in self.op.log.call_args_list))
                    if cause in ('target', 'frame'):
                        self.assertNotIn('old', self.op._sanma_friend_attempted_targets)
                        self.assertTrue(self.op._sanma_friend_kita_rearmed)

    def test_live_receipts_revalidate_after_rearm_preclick_failure(self):
        import copy
        import json
        from sanma_friend_freshness import friend_action_target_key
        from sanma_friend_kita_rearm import rearm_friend_kita_candidate
        data = Path('/home/yama1/server/data/dev-work/jantama/data88-run3/frames')
        paths = sorted(data.glob('*.sanma-self-turn.receipt.json'))
        if len(paths) < 2:
            self.skipTest('independent live capture unavailable')
        before, after = (json.loads(p.read_text()) for p in paths[-2:])
        for cause in ('success', 'candidate', 'screen'):
            with self.subTest(cause=cause):
                self.op.args.max_iterations = 3
                self.op.verified_friend_300_active = True
                self.op._sanma_friend_attempted_targets = set()
                self.op._sanma_friend_attempted_frames = set()
                self.op._sanma_friend_kita_rearmed = False
                self.op.log.reset_mock()
                self.op.observe_sanma_friend_transition = Mock(return_value={'status': 'visual_change_unconfirmed'})
                changed = copy.deepcopy(after)
                if cause == 'candidate': changed['candidates']['candidates'] = [{'action': 'tsumo'}]
                self.op.inspect_sanma_self_turn.side_effect = [before, after, changed]
                self.op.execute_sanma_friend_tsumo_candidate = Mock()
                calls = [0]
                def execute(page, receipt):
                    calls[0] += 1
                    if calls[0] == 1:
                        self.op._sanma_friend_attempted_targets.add(friend_action_target_key(Path(before['screenshot']).read_bytes(), 'kita'))
                        self.op._sanma_friend_attempted_frames.add(before['digest'])
                        return {}
                    if calls[0] == 2: raise SanmaKitaPreclickChanged('before click')
                    return {}
                self.op.execute_sanma_friend_kita_candidate.side_effect = execute
                states = [('match', 1.0), ('match', 1.0),
                          ('round_result' if cause == 'screen' else 'match', 1.0)]
                with patch('sanma_friend_kita_rearm.rearm_friend_kita_candidate', wraps=rearm_friend_kita_candidate) as guard:
                    self.run_loop(states)
                self.assertEqual(calls[0], 3 if cause == 'success' else 2)
                self.assertEqual(guard.call_count, 2 if cause == 'success' else 1)
                self.op.execute_sanma_friend_tsumo_candidate.assert_not_called()
                if cause != 'success':
                    reason = 'kita_reobserve_candidate_changed' if cause == 'candidate' else 'kita_reobserve_screen_changed'
                    self.assertTrue(any(c.kwargs.get('reason') == reason for c in self.op.log.call_args_list))

    def test_two_unconfirmed_kita_keep_clock_for_unsent_discard_retry(self):
        from sanma_friend_discard_experiment import DiscardPreclickChanged
        self.op.args.max_iterations = 4
        def receipt(digest, choices, draw=None):
            return {'candidates': {'candidates': choices}, 'digest': digest,
                    'screenshot': digest, 'drawCandidate': draw}
        self.op.inspect_sanma_self_turn.side_effect = [
            receipt('north1', [{'action': 'kita'}]),
            receipt('north2', [{'action': 'kita'}]),
            receipt('draw1', [], {'status': 'candidate'}),
            receipt('draw2', [], {'status': 'candidate'}),
        ]
        self.op.execute_sanma_friend_kita_candidate.side_effect = None
        self.op.execute_sanma_friend_kita_candidate.return_value = {}
        self.op.observe_sanma_friend_transition = Mock(return_value={'status': 'visual_change_unconfirmed'})
        with patch('sanma_friend_kita_rearm.rearm_friend_kita_candidate', return_value=True), \
             patch('sanma_friend_discard_experiment.execute_friend_draw_candidate',
                   side_effect=DiscardPreclickChanged('before click')) as discard:
            self.run_loop()
        self.assertEqual(discard.call_count, 2)
        self.assertEqual(sum(c.args[0] == 'sanma_friend_action_clock_started' for c in self.op.log.call_args_list), 1)
        self.assertFalse(any(c.kwargs.get('reason') == 'discard_preclick_reobserve_limit' for c in self.op.log.call_args_list))

    def test_prior_non_kita_input_prevents_discard_retry_after_kita(self):
        from sanma_friend_discard_experiment import DiscardPreclickChanged
        for first_action in ('discard', 'pass'):
            with self.subTest(first_action=first_action):
                self.op.args.max_iterations = 4
                self.op.log.reset_mock()
                self.op.execute_sanma_friend_kita_candidate.reset_mock()
                self.op.execute_sanma_friend_kita_candidate.side_effect = None
                self.op.execute_sanma_friend_kita_candidate.return_value = {}
                self.op.observe_sanma_friend_transition = Mock(return_value={'status': 'visual_change_unconfirmed'})
                def receipt(digest, choices):
                    return {'candidates': {'candidates': choices}, 'digest': digest,
                            'screenshot': digest, 'drawCandidate': {'status': 'candidate'}}
                first = [] if first_action == 'discard' else [{'action': 'pon'}]
                self.op.inspect_sanma_self_turn.side_effect = [receipt('first', first),
                    receipt('north', [{'action': 'kita'}]), receipt('draw', [])]
                discards = ([{}, DiscardPreclickChanged('before click')]
                            if first_action == 'discard' else [DiscardPreclickChanged('before click')])
                with patch('sanma_friend_discard_experiment.execute_friend_draw_candidate', side_effect=discards) as discard, \
                     patch('sanma_friend_pass_experiment.execute_friend_pon_pass', return_value={}):
                    self.run_loop()
                self.assertEqual(discard.call_count, 2 if first_action == 'discard' else 1)
                self.assertTrue(any(c.kwargs.get('reason') == 'discard_preclick_reobserve_limit' for c in self.op.log.call_args_list))

    def test_two_kita_then_unsent_discard_stops_on_expiry_or_revocation(self):
        from sanma_friend_discard_experiment import DiscardPreclickChanged
        for cause in ('deadline', 'revoked'):
            with self.subTest(cause=cause):
                self.op.args.max_iterations = 4
                self.op.verified_friend_300_active = True
                self.op.log.reset_mock()
                self.op.execute_sanma_friend_kita_candidate.side_effect = None
                self.op.execute_sanma_friend_kita_candidate.return_value = {}
                self.op.observe_sanma_friend_transition = Mock(return_value={'status': 'visual_change_unconfirmed'})
                def receipt(digest, choices):
                    return {'candidates': {'candidates': choices}, 'digest': digest,
                            'screenshot': digest, 'drawCandidate': {'status': 'candidate'}}
                self.op.inspect_sanma_self_turn.side_effect = [receipt('north1', [{'action':'kita'}]),
                    receipt('north2', [{'action':'kita'}]), receipt('draw', [])]
                clock = [100.0]
                def reject(*args):
                    if cause == 'deadline': clock[0] = 400.0
                    else: self.op.verified_friend_300_active = False
                    raise DiscardPreclickChanged('before click')
                with patch('auto_operator.time.monotonic', side_effect=lambda: clock[0]), \
                     patch('sanma_friend_kita_rearm.rearm_friend_kita_candidate', return_value=True), \
                     patch('sanma_friend_discard_experiment.execute_friend_draw_candidate', side_effect=reject) as discard:
                    self.run_loop()
                self.assertEqual(discard.call_count, 1)
                self.assertTrue(any(c.kwargs.get('reason') == 'discard_preclick_reobserve_limit' for c in self.op.log.call_args_list))


if __name__ == '__main__':
    unittest.main()
