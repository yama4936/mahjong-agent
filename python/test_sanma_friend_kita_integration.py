"""Replay real friend frames through two unverified north actions."""
import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch, call
from auto_operator import PythonAutoOperator,clip_for_hand,load_json

REPLAY=Path('/home/yama1/projects/jantama-test-tmp/kita-observe-replay.jsonl')
@unittest.skipUnless(REPLAY.exists(),'saved friend observations unavailable')
class FriendKitaIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        data=[json.loads(line) for line in REPLAY.read_text().splitlines()]
        self.first=data[0]['r'];self.second=data[3]['r']
        self.first['screenshot']=data[0]['file'];self.second['screenshot']=data[3]['file']
        # Restore offline replay images by digest; this is not a live observation.
        for r in (self.first, self.second):
            frame=Path(r['screenshot'])
            if hashlib.sha256(frame.read_bytes()).hexdigest() != r['freshness']['digest']:
                self.skipTest('recorded replay freshness content unavailable')
            r['freshness']['screenshot']=str(frame)
        self.a=Path(data[0]['file']).read_bytes();self.b=Path(data[3]['file']).read_bytes()
        self.op=object.__new__(PythonAutoOperator)
        self.op.args=SimpleNamespace(rules='sanma',mode='force-auto',experimental_sanma_friend=True,
            action_deadline_ms=300000,ranked_loop=False,start_reviewed_friend_room='reviewed.png',max_iterations=2)
        self.op.verified_friend_300_active=True;self.op.frames=Path(self.tmp.name);self.op.screen_references={}
        self.op.log=Mock();self.op.layout=load_json(Path('config/layout-runtime.json'))
        self.op.hand_clip=clip_for_hand(self.op.layout);self.op.river_clip=self.op.layout['publicTileRegions']['ownDiscards']
        self.op.inspect_sanma_self_turn=Mock(side_effect=[self.first,self.second])
        self.page=Mock();self.page.screenshot.side_effect=[self.a,self.a,self.b,self.b,self.b,self.b,self.b,self.b]+[self.b]*30
    def test_offline_replay_two_north_inputs_remain_unconfirmed(self):
        with patch('auto_operator.classify_screen',return_value=('match',1.0)):
            self.op.run_experimental_sanma_friend(self.page)
        self.assertEqual(self.page.mouse.click.call_args_list,[call(1012.5,830.0),call(1012.5,830.0)])
        self.assertEqual(sum(c.args[0]=='sanma_friend_action_unconfirmed' for c in self.op.log.call_args_list),2)
        self.assertTrue(any(c.args[0]=='sanma_friend_kita_rearm_candidate' and c.kwargs['confirmed'] is False for c in self.op.log.call_args_list))
        self.assertTrue(any(c.kwargs.get('reason')=='transition_requires_review' for c in self.op.log.call_args_list))
