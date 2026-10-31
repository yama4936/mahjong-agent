import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from sanma_friend_kita_rearm import rearm_friend_kita_candidate
from sanma_friend_freshness import friend_action_target_key

REPLAY=Path('/home/yama1/projects/jantama-test-tmp/kita-observe-replay.jsonl')
@unittest.skipUnless(REPLAY.exists(), 'recorded friend replay missing')
class KitaRearmTests(unittest.TestCase):
    def setUp(self):
        data=[json.loads(line) for line in REPLAY.read_text().splitlines()]
        self.before=data[0]['r'];self.after=data[3]['r']
        self.before['screenshot']=data[0]['file'];self.after['screenshot']=data[3]['file']
        self.op=Mock();self.op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
        self.op.verified_friend_300_active=True;self.op._sanma_friend_kita_rearmed=False
        self.op._sanma_friend_attempted_targets={friend_action_target_key(Path(data[0]['file']).read_bytes(),'kita')}
    def test_real_first_north_change_rearms_once_without_claiming_confirmation(self):
        self.assertTrue(rearm_friend_kita_candidate(self.op,self.before,self.after))
        self.assertFalse(self.op.log.call_args.kwargs['confirmed'])
        self.assertFalse(rearm_friend_kita_candidate(self.op,self.before,self.after))
    def test_same_frame_stale_weak_draw_and_ranked_rejected(self):
        for case in ('same','stale','draw','ranked','north'):
            self.setUp();before=copy.deepcopy(self.before);after=copy.deepcopy(self.after)
            if case=='same':after=before
            if case=='stale':after['freshness']['status']='changed'
            if case=='draw':after['sourceObservation']['report']['hand']['value']['matches'][-1]['confidence']=.7
            if case=='ranked':self.op.args.ranked_loop=True
            if case=='north':after['sourceObservation']['report']['hand']['value']['tiles'][11]='S'
            with self.subTest(case=case):self.assertFalse(rearm_friend_kita_candidate(self.op,before,after))
