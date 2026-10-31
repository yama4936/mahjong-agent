import copy
import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from sanma_friend_pass_experiment import execute_friend_pon_pass

IMAGE=Path('/home/yama1/sanma-independent-20261031/27-turn.png')

@unittest.skipUnless(IMAGE.exists(),'saved pon prompt unavailable')
class FriendPassTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.frame=IMAGE.read_bytes(); path=Path(self.temp.name)/'prompt.png';path.write_bytes(self.frame)
        digest=hashlib.sha256(self.frame).hexdigest()
        slots=[{'slot':0,'status':'empty_candidate','confidence':1},
               {'slot':1,'status':'candidate','action':'pon','confidence':.999923},
               {'slot':2,'status':'candidate','action':'skip','confidence':.999971}]
        self.receipt={'scope':'sanma_self_turn_observation','status':'blocked','operationAuthorized':False,
          'digest':digest,'screenshot':str(path),'candidates':{'candidates':[{'action':'pon'}]},'freshness':{'status':'identical_pixels_candidate','operationAuthorized':False,'elapsedMs':1000},
          'sourceObservation':{'digest':digest,'operationAuthorized':False,'report':{'digest':digest,
          'buttonRow':{'status':'candidate','value':{'slots':slots}}}}}
        self.op=Mock();self.op.args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,
          ranked_loop=False,experimental_sanma_friend=True);self.op.verified_friend_300_active=True
        self.op.verified_friend_300_started_at=time.monotonic();self.op._sanma_friend_attempted_targets=set()
        self.page=Mock();self.page.screenshot.return_value=self.frame
        self.classifier=patch('sanma_friend_pass_experiment.classify_screen',return_value=('match',1.0));self.classifier.start();self.addCleanup(self.classifier.stop)
    def test_real_prompt_clicks_once_and_duplicate_is_blocked(self):
        result=execute_friend_pon_pass(self.op,self.page,self.receipt)
        self.assertEqual(result['confirmation'],'unknown');self.page.mouse.click.assert_called_once_with(1300,830)
        with self.assertRaisesRegex(RuntimeError,'already attempted'):execute_friend_pon_pass(self.op,self.page,self.receipt)
        self.page.mouse.click.assert_called_once()
    def test_ron_unknown_changed_and_ranked_block(self):
        for case in ('ron','unknown','changed','ranked','stale'):
            self.setUp(); slots=self.receipt['sourceObservation']['report']['buttonRow']['value']['slots']
            if case=='ron': slots[0].update(status='candidate',action='ron',confidence=1)
            if case=='unknown': slots[1]['status']='unknown'
            if case=='changed': self.page.screenshot.return_value=b'changed'
            if case=='ranked': self.op.args.ranked_loop=True
            if case=='stale': self.receipt['freshness']['elapsedMs']=20001
            with self.subTest(case=case),self.assertRaises((ValueError,RuntimeError,OSError)):
                execute_friend_pon_pass(self.op,self.page,self.receipt)
            self.page.mouse.click.assert_not_called()

    def test_observed_action_clock_survives_old_session_and_expires(self):
        self.op.verified_friend_300_started_at = 100.0
        self.op.sanma_friend_action_observed_at = 450.0
        with patch('sanma_friend_pass_experiment.time.monotonic', return_value=500.0):
            result = execute_friend_pon_pass(self.op, self.page, self.receipt)
        self.assertFalse(result['confirmation'] == 'confirmed')
        self.setUp()
        self.op.verified_friend_300_started_at = 100.0
        self.op.sanma_friend_action_observed_at = 450.0
        with patch('sanma_friend_pass_experiment.time.monotonic', return_value=750.0):
            with self.assertRaisesRegex(RuntimeError, 'expired'):
                execute_friend_pon_pass(self.op, self.page, self.receipt)
        self.page.mouse.click.assert_not_called()

    def test_real_riichi_and_pon_kan_candidate_prompts(self):
        cases = [
            (Path('/home/yama1/.codex/sanma-run-1740066-20261031/manual-18-before.png'),
             [('empty_candidate',None,1.0),('candidate','riichi',1.0),('candidate','skip',.999971)], ['riichi']),
            (Path('/home/yama1/projects/jantama-auto/artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-16-46-070Z-before.png'),
             [('candidate','pon',.98616),('candidate','kan',1.0),('candidate','skip',.999988)], ['pon','kan'])]
        for image, observed, options in cases:
            if not image.exists():
                self.skipTest('saved action prompt unavailable')
            self.setUp()
            frame = image.read_bytes()
            path = Path(self.temp.name)/'real.png'; path.write_bytes(frame)
            digest = hashlib.sha256(frame).hexdigest()
            self.page.screenshot.return_value = frame
            self.receipt['screenshot'] = str(path)
            self.receipt['digest'] = digest
            self.receipt['sourceObservation']['digest'] = digest
            self.receipt['sourceObservation']['report']['digest'] = digest
            self.receipt['candidates'] = {'candidates':[{'action':action} for action in options]}
            self.receipt['sourceObservation']['report']['buttonRow']['value']['slots'] = [
                {'slot':i,'status':status,'action':action,'confidence':confidence}
                for i,(status,action,confidence) in enumerate(observed)]
            result = execute_friend_pon_pass(self.op,self.page,self.receipt)
            self.assertEqual(result['confirmation'],'unknown')
            self.page.mouse.click.assert_called_once_with(1300,830)
