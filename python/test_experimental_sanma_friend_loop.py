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
        self.op.observe_sanma_friend_transition = Mock(return_value={'status':'unresolved','confirmed':False})

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

    def test_ron_takes_priority_over_other_candidates(self):
        self.op.execute_sanma_friend_ron_candidate = Mock(return_value={'confirmation':'unknown'})
        self.receipt['candidates'] = {'candidates':[{'action':'pon'}, {'action':'ron'}]}
        self.run_room()
        self.op.execute_sanma_friend_ron_candidate.assert_called_once_with(self.page,self.receipt)
        self.op.execute_sanma_friend_tsumo_candidate.assert_not_called()
        self.assertTrue(any(call.kwargs.get('reason') == 'transition_requires_review' for call in self.op.log.call_args_list))

    def test_unsupported_or_unknown_action_stops_without_play_click(self):
        self.receipt['candidates'] = {'candidates': [{'action':'abort'}]}
        self.run_room()
        self.page.mouse.click.assert_called_once_with(1140,998)
        self.op.execute_sanma_friend_tsumo_candidate.assert_not_called()
        self.assertTrue(any(call.kwargs.get('reason')=='unsupported_or_unknown_action' for call in self.op.log.call_args_list))

    def test_real_start_animation_waits_then_observes_match(self):
        fixture = Path('/home/yama1/.codex/sanma-run-1740066-20261031/frames/2026-10-30T23-37-24.592906+00-00.805131614d0e42f4aafdf2c7a89c592c.sanma-friend-stop.png')
        if not fixture.exists():
            self.skipTest('captured friend start animation is not available')
        self.op.args.max_iterations = 2
        self.page.screenshot.side_effect = [fixture.read_bytes(), b'match']
        self.op.verified_friend_300_active = True
        with patch('auto_operator.classify_screen', side_effect=[('unknown', 0.0), ('match', 1.0)]):
            self.op.run_experimental_sanma_friend(self.page)
        self.op.execute_sanma_friend_tsumo_candidate.assert_called_once()
        self.assertTrue(any(c.kwargs.get('reason') == 'startup_screen_unknown' for c in self.op.log.call_args_list))

    def test_unknown_start_is_bounded_and_login_is_not_ignored(self):
        self.op.args.max_iterations = 0
        self.op.verified_friend_300_active = True
        with patch('auto_operator.classify_screen', return_value=('unknown', 0.0)):
            self.op.run_experimental_sanma_friend(self.page)
        self.assertEqual(self.page.wait_for_timeout.call_count, 20)
        self.assertTrue(any(c.kwargs.get('reason') == 'unexpected_screen' for c in self.op.log.call_args_list))
        self.op.log.reset_mock()
        self.page.wait_for_timeout.reset_mock()
        with patch('auto_operator.classify_screen', return_value=('login', 1.0)):
            self.op.run_experimental_sanma_friend(self.page)
        self.page.wait_for_timeout.assert_not_called()
        self.assertTrue(any(c.kwargs.get('screenState') == 'login' for c in self.op.log.call_args_list))

    def test_real_reviewed_room_preflight_enters_only_the_experimental_loop(self):
        fixture = Path(__file__).resolve().parents[1] / 'test/fixtures/sanma-friend-preflight.png'
        image = fixture.read_bytes()
        self.preflight.write_bytes(image)
        self.page.screenshot.side_effect = [image, image, image, image, b'match screenshot']
        self.receipt['candidates'] = {'candidates': []}
        with patch('auto_operator.classify_screen',return_value=('match',1.0)):
            self.op.run(self.page)
        self.page.mouse.click.assert_called_once_with(1140,998)
        self.op.execute_sanma_friend_tsumo_candidate.assert_not_called()
        self.assertTrue(any(call.kwargs.get('reason')=='friend_monitor_limit' for call in self.op.log.call_args_list))

    def test_kita_routes_to_friend_adapter_and_stops(self):
        self.receipt['candidates'] = {'candidates': [{'action':'kita'}]}
        self.run_room()
        self.op.execute_sanma_friend_kita_candidate.assert_called_once_with(self.page,self.receipt)
        self.op.execute_sanma_friend_tsumo_candidate.assert_not_called()
        self.assertTrue(any(call.kwargs.get('reason')=='transition_requires_review' for call in self.op.log.call_args_list))

    def test_pon_routes_to_pass_and_stops_unconfirmed(self):
        self.receipt['candidates'] = {'candidates': [{'action':'pon'}]}
        with patch('sanma_friend_pass_experiment.execute_friend_pon_pass', return_value={'confirmation':'unknown'}) as skip:
            self.run_room()
        skip.assert_called_once_with(self.op, self.page, self.receipt)
        self.assertTrue(any(call.kwargs.get('reason') == 'pass_transition_requires_review' for call in self.op.log.call_args_list))

    def test_optional_riichi_and_kan_route_to_pass(self):
        for actions in ([{'action':'riichi'}], [{'action':'pon'},{'action':'kan'}]):
            self.receipt['candidates'] = {'candidates': actions}
            with self.subTest(actions=actions), patch('sanma_friend_pass_experiment.execute_friend_pon_pass', return_value={'confirmation':'unknown'}) as skip:
                self.run_room()
                skip.assert_called_once_with(self.op,self.page,self.receipt)

    def test_result_is_recorded_then_round_advanced_and_match_stopped(self):
        self.op.args.max_iterations = 3
        self.op.verified_friend_300_active = True
        self.op.advance_result_screen_once = Mock(return_value=True)
        with patch('auto_operator.classify_screen', side_effect=[('round_result',1.0),('round_result',1.0),('match_result',1.0)]), \
             patch('auto_operator.friend_frame_stable', return_value=True):
            self.op.run_experimental_sanma_friend(self.page)
        self.op.advance_result_screen_once.assert_called_once_with(self.page,'round_result',1.0)
        self.assertTrue(any(c.kwargs.get('reason')=='match_result_observed' for c in self.op.log.call_args_list))
        self.assertEqual(sum(c.args[0]=='sanma_friend_result_observed' for c in self.op.log.call_args_list),2)

    def test_result_changed_before_advance_stops_without_click(self):
        self.op.args.max_iterations = 3
        self.op.verified_friend_300_active = True
        self.op.advance_result_screen_once = Mock()
        with patch('auto_operator.classify_screen', side_effect=[('round_result',1.0),('match',1.0)]):
            self.op.run_experimental_sanma_friend(self.page)
        self.op.advance_result_screen_once.assert_not_called()
        self.assertTrue(any(c.kwargs.get('reason')=='result_changed_before_advance' for c in self.op.log.call_args_list))

    def test_pass_visible_change_reobserves_next_frame(self):
        self.op.args.max_iterations = 2
        self.receipt['candidates'] = {'candidates': [{'action':'pon'}]}
        self.op.observe_sanma_friend_transition.return_value = {'status':'visual_change_unconfirmed','confirmed':False}
        self.op.inspect_sanma_self_turn.side_effect = [self.receipt, {'candidates':{'candidates':[{'action':'kan'}]},'digest':'next'}]
        with patch('sanma_friend_pass_experiment.execute_friend_pon_pass', return_value={'confirmation':'unknown'}):
            self.run_room()
        self.assertEqual(self.op.inspect_sanma_self_turn.call_count, 2)

    def test_waiting_for_turn_preserves_first_observation_clock(self):
        self.op.args.max_iterations = 2
        self.op.verified_friend_300_active = True
        self.receipt['candidates'] = {'candidates': []}
        observed = []
        def inspect(_page):
            observed.append(self.op.sanma_friend_action_observed_at)
            return self.receipt
        self.op.inspect_sanma_self_turn.side_effect = inspect
        clock = iter([100.0, 101.0, 102.0, 103.0, 104.0, 110.0, 111.0, 112.0, 113.0])
        with patch('auto_operator.time.monotonic', side_effect=lambda: next(clock, 114.0)), \
             patch('auto_operator.classify_screen', return_value=('match', 1.0)):
            self.op.run_experimental_sanma_friend(self.page)
        self.assertEqual(observed, [102.0, 102.0])
        self.assertEqual(sum(c.args[0]=='sanma_friend_action_clock_started' for c in self.op.log.call_args_list),1)

    def test_waits_through_four_unknown_observations_then_handles_ron(self):
        self.op.args.max_iterations = 5
        self.op.verified_friend_300_active = True
        self.op.execute_sanma_friend_ron_candidate = Mock(return_value={'confirmation':'unknown'})
        unknown = {'candidates':{'candidates':[]}, 'digest':'unknown','screenshot':'unknown.png'}
        ron = {'candidates':{'candidates':[{'action':'ron'}]}, 'digest':'ron','screenshot':'ron.png'}
        self.op.inspect_sanma_self_turn.side_effect = [unknown]*4 + [ron]
        with patch('auto_operator.classify_screen', return_value=('match',1.0)):
            self.op.run_experimental_sanma_friend(self.page)
        self.assertEqual(self.page.wait_for_timeout.call_count,4)
        self.op.execute_sanma_friend_ron_candidate.assert_called_once()
        self.assertTrue(any(c.kwargs.get('opponentTurnConfirmed') is False for c in self.op.log.call_args_list))

    def test_unknown_turn_has_bounded_wait(self):
        self.op.args.max_iterations = 0
        self.op.verified_friend_300_active = True
        self.receipt['candidates'] = {'candidates':[]}
        with patch('auto_operator.classify_screen', return_value=('match',1.0)):
            self.op.run_experimental_sanma_friend(self.page)
        self.assertEqual(self.page.wait_for_timeout.call_count,119)
        self.assertTrue(any(c.kwargs.get('reason')=='draw_or_turn_unknown' for c in self.op.log.call_args_list))

    def test_captured_opponent_turn_frame_remains_observation_only(self):
        frame = Path('/home/yama1/.codex/sanma-run-1740066-20261031/manual-17-after.png')
        references = Path('/home/yama1/projects/jantama-auto/artifacts/live')
        if not frame.exists() or not references.exists():
            self.skipTest('recorded opponent frame or references unavailable')
        from screen_state import load_references
        self.op.screen_references = load_references(references)
        self.op.args.max_iterations = 4
        self.op.verified_friend_300_active = True
        self.page.screenshot.return_value = frame.read_bytes()
        self.op.inspect_sanma_self_turn.return_value = {
            'candidates':{'candidates':[]}, 'drawCandidate':{'status':'unresolved'},
            'digest':'real-opponent-observation','screenshot':str(frame)}
        self.op.run_experimental_sanma_friend(self.page)
        self.assertEqual(self.page.wait_for_timeout.call_count,4)
        self.page.mouse.click.assert_not_called()

    def test_no_prompt_routes_to_draw_adapter_and_stops(self):
        self.receipt['candidates'] = {'candidates': []}
        self.receipt['drawCandidate'] = {'status':'candidate'}
        with patch('sanma_friend_discard_experiment.execute_friend_draw_candidate',return_value={'status':'selection_confirmed','result':'discard_not_verified'}) as draw:
            self.run_room()
        draw.assert_called_once_with(self.op,self.page,self.receipt)
        self.page.mouse.click.assert_called_once_with(1140,998)
        self.op.execute_sanma_friend_tsumo_candidate.assert_not_called()
        self.assertTrue(any(call.kwargs.get('reason')=='transition_requires_review' for call in self.op.log.call_args_list))

    def test_changed_unconfirmed_transition_reobserves_before_next_action(self):
        self.op.args.max_iterations = 2
        self.op.observe_sanma_friend_transition.return_value = {'status':'visual_change_unconfirmed','confirmed':False}
        next_receipt = {'candidates': {'candidates':[{'action':'abort'}]}, 'digest':'next', 'screenshot':'next.png'}
        self.op.inspect_sanma_self_turn.side_effect = [self.receipt,next_receipt]
        self.run_room()
        self.assertEqual(self.op.inspect_sanma_self_turn.call_count,2)
        self.op.execute_sanma_friend_tsumo_candidate.assert_called_once()
        self.assertTrue(any(call.kwargs.get('reason')=='unsupported_or_unknown_action' for call in self.op.log.call_args_list))
        self.assertTrue(any(call.args[0]=='sanma_friend_action_unconfirmed' and call.kwargs.get('confirmed') is False
                            for call in self.op.log.call_args_list))

    def test_new_digest_cannot_repeat_an_unconfirmed_kita(self):
        self.op.args.max_iterations = 2
        self.op.observe_sanma_friend_transition.return_value = {'status':'visual_change_unconfirmed','confirmed':False}
        self.receipt['candidates'] = {'candidates':[{'action':'kita'}]}
        next_receipt = {'candidates':{'candidates':[{'action':'kita'}]},'digest':'changed-clock','screenshot':'next.png'}
        self.op.inspect_sanma_self_turn.side_effect = [self.receipt,next_receipt]
        self.run_room()
        self.op.execute_sanma_friend_kita_candidate.assert_called_once()
        self.assertTrue(any(call.kwargs.get('reason')=='previous_kita_unconfirmed' for call in self.op.log.call_args_list))

    def test_second_kita_requires_explicit_rearm_candidate(self):
        self.op.args.max_iterations = 2
        self.op.observe_sanma_friend_transition.return_value = {'status':'visual_change_unconfirmed','confirmed':False}
        self.receipt['candidates'] = {'candidates':[{'action':'kita'}]}
        next_receipt = {'candidates':{'candidates':[{'action':'kita'}]},'digest':'next','screenshot':'next.png'}
        self.op.inspect_sanma_self_turn.side_effect = [self.receipt,next_receipt]
        with patch('sanma_friend_kita_rearm.rearm_friend_kita_candidate',return_value=True) as rearm:
            self.run_room()
        rearm.assert_called_once_with(self.op,self.receipt,next_receipt)
        self.assertEqual(self.op.execute_sanma_friend_kita_candidate.call_count,2)

    def test_real_changed_kita_observation_is_reobserved_before_input(self):
        directory=Path('/home/yama1/.codex/sanma-run-d0ff500-20261031/frames')
        original=next(directory.glob('*dcb907c754fe49edb5e5d8a4e2f4ab45.sanma-self-turn.png'),None)
        changed=next(directory.glob('*91ba8301a2464ec1b3ee6db282cbe1d3.sanma-freshness.png'),None)
        if original is None or changed is None:
            self.skipTest('saved stale kita images unavailable')
        from sanma_friend_freshness import friend_frame_changes
        self.assertTrue(friend_frame_changes(original.read_bytes(),changed.read_bytes())['fullFrame'])
        self.op.args.max_iterations = 2
        first={'candidates':{'candidates':[{'action':'kita'}]},'digest':'first','screenshot':str(original),
               'freshness':{'status':'changed','screenshot':str(changed),'digest':'changed','regionsChanged':{'hand':True}}}
        second={'candidates':{'candidates':[{'action':'kita'}]},'digest':'new','screenshot':str(changed),
                'freshness':{'status':'identical_pixels_candidate'}}
        self.op.inspect_sanma_self_turn.side_effect = [first,second]
        self.run_room()
        self.op.execute_sanma_friend_kita_candidate.assert_called_once_with(self.page,second)
        self.assertTrue(any(c.kwargs.get('reason')=='observation_changed_reobserve' for c in self.op.log.call_args_list))

    def test_repeated_changed_observation_times_out_without_input(self):
        self.op.args.max_iterations = 0
        self.op.verified_friend_300_active = True
        self.receipt['freshness'] = {'status':'changed'}
        with patch('auto_operator.classify_screen', return_value=('match',1.0)):
            self.op.run_experimental_sanma_friend(self.page)
        self.op.execute_sanma_friend_tsumo_candidate.assert_not_called()
        self.assertTrue(any(c.kwargs.get('reason')=='observation_changed_timeout' for c in self.op.log.call_args_list))

    def test_same_frame_after_unconfirmed_transition_never_repeats_click(self):
        self.op.args.max_iterations = 2
        self.op.observe_sanma_friend_transition.return_value = {'status':'visual_change_unconfirmed','confirmed':False}
        self.run_room()
        self.op.execute_sanma_friend_tsumo_candidate.assert_called_once()
        self.assertTrue(any(call.kwargs.get('reason')=='frame_already_attempted_or_unknown' for call in self.op.log.call_args_list))

    def test_failed_room_verification_never_clicks(self):
        with patch('auto_operator.inspect_sanma_friend_start',side_effect=ValueError('room changed')):
            with self.assertRaisesRegex(ValueError,'room changed'):
                self.op.run(self.page)
        self.page.mouse.click.assert_not_called()

    def test_changed_room_at_final_check_never_starts(self):
        with patch('auto_operator.inspect_sanma_friend_start', side_effect=[
                {'operationAuthorized': False}, RuntimeError('room changed')]):
            with self.assertRaisesRegex(RuntimeError, 'room changed'):
                self.op.run(self.page)
        self.page.mouse.click.assert_not_called()
        self.assertFalse(self.op.verified_friend_300_active)
        self.assertTrue(any(call.kwargs.get('reason') == 'final_friend_room_check_failed'
                            for call in self.op.log.call_args_list))

    def test_revoked_session_at_final_check_never_starts(self):
        calls = 0
        def inspect(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.op.verified_friend_300_active = False
            return {'operationAuthorized': False}
        with patch('auto_operator.inspect_sanma_friend_start', side_effect=inspect):
            with self.assertRaisesRegex(RuntimeError, 'session revoked'):
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
