import copy
import json
import unittest
from pathlib import Path
from sanma_friend_discard_experiment import experimental_draw_only_candidate

LOG=Path('/home/yama1/projects/jantama-test-tmp/replay-manual03.log')
@unittest.skipUnless(LOG.exists(),'saved replay report unavailable')
class DrawOnlyTests(unittest.TestCase):
    def setUp(self):
        report=json.loads(next(x[2:] for x in LOG.read_text().splitlines() if x.startswith('1 ')))
        self.hand=report['hand']['value'];self.geo=report['handGeometry']['value']
        self.draw={'index':13,'tile':self.hand['tiles'][-1]}
    def test_actual_frame_strong_east_despite_weak_four_pin(self):
        self.assertFalse(self.hand['safe'])
        self.assertEqual(self.hand['tiles'][3],'4p')
        self.assertEqual(self.draw['tile'],'E')
        self.assertTrue(experimental_draw_only_candidate(self.hand,self.geo,self.draw))
    def test_weak_draw_incomplete_row_and_no_gap_rejected(self):
        for case in ('confidence','margin','length','geometry','gap','draw'):
            hand,geo,draw=copy.deepcopy(self.hand),copy.deepcopy(self.geo),dict(self.draw)
            if case=='confidence':hand['matches'][-1]['confidence']=.8
            if case=='margin':hand['matches'][-1]['runnerUpConfidence']=.98
            if case=='length':hand['matches'].pop()
            if case=='geometry':geo['evidence']['detectedTiles']=13
            if case=='gap':geo['evidence']['drawGap']=geo['evidence']['medianGap']
            if case=='draw':draw['index']=12
            with self.subTest(case=case):self.assertFalse(experimental_draw_only_candidate(hand,geo,draw))
    def test_real_report_reaches_friend_draw_bridge_without_promoting_safe(self):
        import hashlib,tempfile
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        from sanma_friend_discard_experiment import execute_friend_draw_candidate
        path=Path('/home/yama1/.codex/sanma-run-d0ff500-20261031/manual-03-before.png')
        if not path.exists():self.skipTest('frame unavailable')
        frame=path.read_bytes();digest=hashlib.sha256(frame).hexdigest()
        op=Mock();op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
        op.verified_friend_300_active=True
        point=self.geo['clickPoints'][-1]
        report={'digest':digest,'hand':{'status':'candidate','value':self.hand},
                'handGeometry':{'status':'candidate','value':self.geo},
                'buttonRow':{'status':'candidate','value':{'slots':[{'status':'empty_candidate'},{'status':'empty_candidate'},{'status':'unresolved'}]}}}
        receipt={'scope':'sanma_self_turn_observation','digest':digest,'screenshot':str(path),'freshness':{'status':'identical_pixels_candidate'},
                 'sourceObservation':{'digest':digest,'report':report},
                 'drawCandidate':{'status':'candidate','digest':digest,'index':13,'tile':'E','point':point}}
        with patch('sanma_friend_discard_experiment.execute_friend_discard') as execute:
            execute_friend_draw_candidate(op,Mock(),receipt)
            execute.assert_called_once()
            self.assertEqual(execute.call_args.kwargs['plan']['clickPoint'],point)
        self.assertFalse(self.hand['safe'])
        self.assertTrue(any('other hand labels' in c.kwargs.get('risk','') for c in op.log.call_args_list))
