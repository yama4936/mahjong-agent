import copy
import hashlib
import tempfile
import io
import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw
from sanma_friend_abort_prompt import execute, prompt_matches, recognizable

ROOT=Path('/home/yama1/server/data/dev-work/jantama/evidence198')

@unittest.skipUnless((ROOT/'operator.log').exists(), 'evidence198 unavailable')
class NineTerminalsPromptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows=[json.loads(s) for s in (ROOT/'operator.log').read_text().splitlines() if s.startswith('{')]
        row=next(x for x in rows if x.get('event')=='sanma_self_turn_observed'
                 and x['timestamp'].startswith('2026-11-12T16:20:28'))
        cls.original=json.loads(Path(row['receiptPath']).read_text())
        cls.baseline=Path(row['screenshot']).read_bytes()
        cls.fresh=Path(row['freshness']['screenshot']).read_bytes()

    def setUp(self):
        self.receipt=copy.deepcopy(self.original)
        self.watch=Mock();self.watch.alive.return_value=True
        self.op=SimpleNamespace(args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,
            ranked_loop=False,experimental_sanma_friend=True),verified_friend_300_active=True,
            sanma_friend_action_observed_at=time.monotonic(),screen_references={},log=Mock())
        self.page=Mock();self.page.screenshot.return_value=self.fresh
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        image=Image.open(io.BytesIO(self.fresh)).convert('RGB')
        ImageDraw.Draw(image).rectangle((890,785,1425,875),fill=(32,45,70))
        buffer=io.BytesIO();image.save(buffer,format='PNG');self.after=buffer.getvalue()
        path=Path(temp.name)/'synthetic-post.png';path.write_bytes(self.after)
        self.post=copy.deepcopy(self.original)
        digest=hashlib.sha256(self.after).hexdigest()
        self.post.update(screenshot=str(path),digest=digest)
        self.post['sourceObservation']['digest']=digest
        self.post['sourceObservation']['report']['digest']=digest
        row=self.post['sourceObservation']['report']['buttonRow']['value']
        row['slots']=[{'slot':i,'status':'empty_candidate'} for i in range(3)]
        self.post['freshness'].update(screenshot=str(path),digest=digest)
        self.post['drawCandidate']['digest']=digest
        def inspect(page, *, classified_frame, classified_started):
            return dict(self.post,captureStartedMonotonic=classified_started)
        self.inspect=inspect
        self.op.inspect_sanma_self_turn=Mock(side_effect=inspect)

    def call(self):
        with patch('sanma_friend_abort_prompt.MatchContinuity',return_value=self.watch), \
             patch('sanma_friend_abort_prompt.classify_screen',return_value=('match',1)), \
             patch('sanma_friend_abort_prompt.require_friend_observation_budget'):
            return execute(self.op,self.page,self.receipt)

    def test_real_prompt_and_stable_reobservation_then_skip_once(self):
        self.assertTrue(prompt_matches(self.baseline));self.assertTrue(prompt_matches(self.fresh))
        self.page.screenshot.side_effect=[self.fresh,self.after,self.after]
        self.assertTrue(recognizable(self.receipt));self.assertIs(self.call(),self.watch)
        self.assertEqual(self.op.inspect_sanma_self_turn.call_count,2)
        self.page.mouse.click.assert_called_once_with(1300,830)
        self.page.screenshot.side_effect=None;self.page.screenshot.return_value=self.fresh
        with self.assertRaisesRegex(RuntimeError,'already attempted'): self.call()
        self.page.mouse.click.assert_called_once()

    def test_unrecognized_buttons_or_changed_hand_never_click(self):
        for box in ((930,790,1100,865),(1210,800,1380,860),(223,921,315,1072)):
            with self.subTest(box=box):
                image=Image.open(io.BytesIO(self.fresh)).convert('RGB');ImageDraw.Draw(image).rectangle(box,fill='black')
                buf=io.BytesIO();image.save(buf,format='PNG');self.page.screenshot.return_value=buf.getvalue()
                self.assertFalse(self.call());self.page.mouse.click.assert_not_called()

    def test_ron_or_unknown_row_or_inconsistent_hand_never_click(self):
        for mutate in ('ron','unknown_skip','insufficient_orphans','bad_digest'):
            with self.subTest(mutate=mutate):
                self.receipt=copy.deepcopy(self.original)
                if mutate=='ron': self.receipt['candidates']['candidates']=[{'action':'ron'}]
                elif mutate=='unknown_skip': self.receipt['sourceObservation']['report']['buttonRow']['value']['slots'][2]['status']='unresolved'
                elif mutate=='insufficient_orphans': self.receipt['sourceObservation']['report']['hand']['value']['tiles']=['1m']*14
                else:self.receipt['sourceObservation']['report']['digest']='0'*64
                self.assertFalse(self.call());self.page.mouse.click.assert_not_called()

    def test_disconnect_and_expired_deadline_never_click(self):
        self.watch.alive.return_value=False;self.assertFalse(self.call());self.page.mouse.click.assert_not_called()
        self.watch.alive.return_value=True;self.op.sanma_friend_action_observed_at=time.monotonic()-301
        self.assertFalse(self.call());self.page.mouse.click.assert_not_called()

    def test_connection_loss_after_latch_blocks_click_and_retries(self):
        self.watch.alive.side_effect=[True,True,False]
        with self.assertRaisesRegex(RuntimeError,'continuity'):self.call()
        self.page.mouse.click.assert_not_called()
        self.watch.alive.side_effect=None;self.watch.alive.return_value=True
        with self.assertRaisesRegex(RuntimeError,'already attempted'):self.call()
        self.page.mouse.click.assert_not_called()

    def test_unconfirmed_pass_or_changed_round_never_retried(self):
        for mode in ('prompt_still_visible','changed_round'):
            with self.subTest(mode=mode):
                self.setUp()
                self.page.screenshot.side_effect=[self.fresh]+[self.after]*8
                if mode=='prompt_still_visible':
                    self.post['sourceObservation']['report']['buttonRow']['value']['slots'][1]['status']='unresolved'
                else:
                    self.post['sourceObservation']['board']['candidate']['round']='east_2'
                with self.assertRaisesRegex(RuntimeError,'pass outcome not independently observed'):
                    self.call()
                self.page.mouse.click.assert_called_once_with(1300,830)
                self.watch.close.assert_called_once()

    def test_changed_board_pixels_between_independent_post_frames_never_resumes(self):
        image=Image.open(io.BytesIO(self.after)).convert('RGB')
        ImageDraw.Draw(image).rectangle((760,550,775,565),fill=(255,255,255))
        buffer=io.BytesIO();image.save(buffer,format='PNG');alternate=buffer.getvalue()
        path=Path(self.post['screenshot']).with_name('synthetic-other.png');path.write_bytes(alternate)
        other=copy.deepcopy(self.post);digest=hashlib.sha256(alternate).hexdigest()
        other.update(screenshot=str(path),digest=digest)
        other['sourceObservation']['digest']=digest;other['sourceObservation']['report']['digest']=digest
        other['freshness'].update(screenshot=str(path),digest=digest);other['drawCandidate']['digest']=digest
        def inspect(page, *, classified_frame, classified_started):
            current=self.post if classified_frame==self.after else other
            return dict(current,captureStartedMonotonic=classified_started)
        self.op.inspect_sanma_self_turn.side_effect=inspect
        self.page.screenshot.side_effect=[self.fresh]+[x for _ in range(4) for x in (self.after,alternate)]
        with self.assertRaisesRegex(RuntimeError,'pass outcome not independently observed'):self.call()
        self.page.mouse.click.assert_called_once_with(1300,830)
        self.watch.close.assert_called_once()

    def test_disconnect_after_sent_never_retries(self):
        self.page.screenshot.return_value=self.fresh
        self.watch.alive.side_effect=[True,True,True,False]
        with self.assertRaisesRegex(RuntimeError,'after pass'):self.call()
        self.page.mouse.click.assert_called_once_with(1300,830)
        self.watch.close.assert_called_once()

    def test_real_prompt_through_friend_loop(self):
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        case=ExperimentalSanmaFriendLoopTest('runTest'); case.setUp(); self.addCleanup(case.doCleanups)
        case.op.verified_friend_300_active=True
        case.op.inspect_sanma_self_turn.return_value=self.receipt
        case.page.screenshot.side_effect=[self.baseline,self.fresh,self.after,self.after]
        def inspect(page, *, classified_frame, classified_started):
            if classified_frame==self.baseline: return self.receipt
            return self.inspect(page,classified_frame=classified_frame,classified_started=classified_started)
        case.op.inspect_sanma_self_turn.side_effect=inspect
        with patch('auto_operator.classify_screen',return_value=('match',1)), \
             patch('sanma_friend_abort_prompt.classify_screen',return_value=('match',1)), \
             patch('sanma_friend_abort_prompt.MatchContinuity',return_value=self.watch), \
             patch('sanma_friend_abort_prompt.require_friend_observation_budget'):
            case.op.run_experimental_sanma_friend(case.page)
        case.page.mouse.click.assert_called_once_with(1300,830)
        self.assertTrue(any(c.args[0]=='sanma_friend_nine_terminals_pass_recovery' for c in case.op.log.call_args_list))
        self.assertIsNone(case.op._sanma_friend_resume_guard)
        self.watch.close.assert_called_once()

    def test_real_prompt_recovers_to_next_discard_under_same_watch(self):
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        case=ExperimentalSanmaFriendLoopTest('runTest'); case.setUp(); self.addCleanup(case.doCleanups)
        case.op.verified_friend_300_active=True;case.op.args.max_iterations=2
        self.post['freshness']['status']='identical_pixels_candidate'
        case.page.screenshot.side_effect=[self.baseline,self.fresh,self.after,self.after,self.after]
        def inspect(page, *, classified_frame, classified_started):
            if classified_frame==self.baseline:return self.receipt
            return self.inspect(page,classified_frame=classified_frame,classified_started=classified_started)
        case.op.inspect_sanma_self_turn.side_effect=inspect
        case.op.observe_sanma_friend_transition.return_value={'status':'unresolved','reason':'transition_not_observed','confirmed':False}
        def discard(op,page,receipt):
            watch,started,deadline=op._sanma_friend_resume_guard
            self.assertIs(watch,self.watch);self.assertEqual(deadline,300000)
            self.assertEqual(started,op.sanma_friend_action_observed_at)
            return {'status':'selection_confirmed','result':'discard_not_verified','tile':'8p','clickIndex':13,
                    'clickPoint':{'x':1532,'y':996.5},'frameSha256':receipt['digest']}
        with patch('auto_operator.classify_screen',return_value=('match',1)), \
             patch('sanma_friend_abort_prompt.classify_screen',return_value=('match',1)), \
             patch('sanma_friend_abort_prompt.MatchContinuity',return_value=self.watch), \
             patch('sanma_friend_abort_prompt.require_friend_observation_budget'), \
             patch('sanma_friend_discard_recovery.MatchContinuity',return_value=Mock()), \
             patch('sanma_friend_discard_experiment.execute_friend_draw_candidate',side_effect=discard) as action:
            case.op.run_experimental_sanma_friend(case.page)
        self.assertEqual(action.call_count,1)
        case.page.mouse.click.assert_called_once_with(1300,830)

    def test_ranked_or_wrong_session_never_click(self):
        self.op.args.ranked_loop=True;self.assertFalse(self.call());self.page.mouse.click.assert_not_called()
        self.op.args.ranked_loop=False;self.op.verified_friend_300_active=False
        self.assertFalse(self.call());self.page.mouse.click.assert_not_called()
