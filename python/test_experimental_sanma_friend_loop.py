"""Friend-only experimental loop integration, with no browser connection."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from auto_operator import PythonAutoOperator, experimental_sanma_friend_allowed, parse_args


class ExperimentalSanmaFriendLoopTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.preflight = Path(self.temp.name) / 'room.png'
        self.preflight.write_bytes(b'reviewed room')
        self.op = object.__new__(PythonAutoOperator)
        self.op.args = SimpleNamespace(rules='sanma',mode='force-auto',experimental_sanma_friend=True,
            action_deadline_ms=300000,ranked_loop=False,start_reviewed_friend_room=str(self.preflight),max_iterations=1)
        self.op.frames = Path(self.temp.name)
        self.op.screen_references = {}
        self.op.ensure_viewport = Mock()
        self.op.log = Mock()
        self.op.revoke_verified_friend_300 = Mock()
        self.page = Mock()
        self.page.screenshot.return_value = b'match screenshot'
        self.receipt = {'candidates': {'candidates': [{'action':'tsumo'}]}, 'digest':'abc', 'screenshot':'frame.png'}
        self.op.inspect_sanma_self_turn = Mock(return_value=self.receipt)
        self.op.execute_sanma_friend_tsumo_candidate = Mock(return_value={'clicked':True,'confirmation':'unknown'})
        self.op.execute_sanma_friend_kita_candidate = Mock(return_value={'clicked':True,'confirmation':'unknown'})

    def run_room(self):
        with patch('auto_operator.inspect_sanma_friend_start',return_value={'operationAuthorized':False}), \
             patch('auto_operator.classify_screen',return_value=('match',1.0)):
            self.op.run(self.page)

    def test_reviewed_room_start_routes_tsumo_and_stops(self):
        self.run_room()
        self.page.mouse.click.assert_called_once_with(1140,998)
        self.op.execute_sanma_friend_tsumo_candidate.assert_called_once_with(self.page,self.receipt)
        self.assertTrue(self.op.verified_friend_300_active)
        self.assertTrue(any(call.args[0]=='sanma_friend_stopped' for call in self.op.log.call_args_list))

    def test_unsupported_or_unknown_action_stops_without_play_click(self):
        self.receipt['candidates'] = {'candidates': [{'action':'kan'}]}
        self.run_room()
        self.page.mouse.click.assert_called_once_with(1140,998)
        self.op.execute_sanma_friend_tsumo_candidate.assert_not_called()
        self.assertTrue(any(call.kwargs.get('reason')=='unsupported_or_unknown_action' for call in self.op.log.call_args_list))

    def test_real_reviewed_room_preflight_enters_only_the_experimental_loop(self):
        fixture = Path(__file__).resolve().parents[1] / 'test/fixtures/sanma-friend-preflight.png'
        image = fixture.read_bytes()
        self.preflight.write_bytes(image)
        self.page.screenshot.side_effect = [image, image, b'match screenshot']
        self.receipt['candidates'] = {'candidates': []}
        with patch('auto_operator.classify_screen',return_value=('match',1.0)):
            self.op.run(self.page)
        self.page.mouse.click.assert_called_once_with(1140,998)
        self.op.execute_sanma_friend_tsumo_candidate.assert_not_called()
        self.assertTrue(any(call.kwargs.get('reason')=='observation_or_action_failed' for call in self.op.log.call_args_list))

    def test_kita_routes_to_friend_adapter_and_stops(self):
        self.receipt['candidates'] = {'candidates': [{'action':'kita'}]}
        self.run_room()
        self.op.execute_sanma_friend_kita_candidate.assert_called_once_with(self.page,self.receipt)
        self.op.execute_sanma_friend_tsumo_candidate.assert_not_called()
        self.assertTrue(any(call.kwargs.get('reason')=='candidate_click_outcome_requires_review' for call in self.op.log.call_args_list))

    def test_no_prompt_routes_to_draw_adapter_and_stops(self):
        self.receipt['candidates'] = {'candidates': []}
        with patch('sanma_friend_discard_experiment.execute_friend_draw_candidate',return_value={'status':'selection_confirmed','result':'discard_not_verified'}) as draw:
            self.run_room()
        draw.assert_called_once_with(self.op,self.page,self.receipt)
        self.page.mouse.click.assert_called_once_with(1140,998)
        self.op.execute_sanma_friend_tsumo_candidate.assert_not_called()
        self.assertTrue(any(call.kwargs.get('reason')=='candidate_click_outcome_requires_review' for call in self.op.log.call_args_list))

    def test_failed_room_verification_never_clicks(self):
        with patch('auto_operator.inspect_sanma_friend_start',side_effect=ValueError('room changed')):
            with self.assertRaisesRegex(ValueError,'room changed'):
                self.op.run(self.page)
        self.page.mouse.click.assert_not_called()

    def test_configuration_restricts_ranked_deadline_and_requires_review(self):
        self.assertTrue(experimental_sanma_friend_allowed(self.op.args))
        for field,value in [('ranked_loop',True),('action_deadline_ms',2600),('mode','advisor'),
                            ('start_reviewed_friend_room',None),('experimental_sanma_friend',False)]:
            old = getattr(self.op.args,field)
            setattr(self.op.args,field,value)
            self.assertFalse(experimental_sanma_friend_allowed(self.op.args))
            setattr(self.op.args,field,old)

    def test_parser_demands_explicit_300000_and_preflight(self):
        common=['auto_operator.py','--layout','x','--templates','x','--state','x','--rules','sanma',
                '--mode','force-auto','--experimental-sanma-friend','--start-reviewed-friend-room',str(self.preflight)]
        with patch('sys.argv',common+['--action-deadline-ms','300000']):
            self.assertTrue(experimental_sanma_friend_allowed(parse_args()))
        for extra in ([],['--action-deadline-ms','300000','--ranked-loop']):
            with self.subTest(extra=extra), patch('sys.argv',common+extra), self.assertRaises(SystemExit):
                parse_args()


if __name__ == '__main__': unittest.main()
