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


if __name__ == '__main__':
    unittest.main()
