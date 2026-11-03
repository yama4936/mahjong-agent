import copy,json,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sanma_friend_blank_draw import blank_draw_candidate
from sanma_friend_discard_experiment import execute_friend_draw_candidate

F=Path('/home/yama1/server/data/dev-work/jantama/evidence163/artifacts/frames')
@unittest.skipUnless(F.exists(),'retained evidence unavailable')
class BlankDraw163(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.path=next(F.glob('*23-11-42*sanma-self-turn.png'));cls.frame=cls.path.read_bytes()
  cls.receipt=json.loads(Path(str(cls.path).replace('.png','.receipt.json')).read_text())
  cls.report=cls.receipt['sourceObservation']['report'];cls.hand=cls.report['hand']['value'];cls.geo=cls.report['handGeometry']['value'];cls.draw=cls.receipt['drawCandidate']
 def test_blank_image_is_physical_candidate_not_white_identification(self):
  self.assertTrue(blank_draw_candidate(self.frame,self.hand,self.geo,self.draw))
 def test_nonblank_and_missing_physical_evidence_rejected(self):
  for name in ('ink','count','gap','confidence','index'):
   h,g,d=copy.deepcopy(self.hand),copy.deepcopy(self.geo),copy.deepcopy(self.draw)
   if name=='ink':h['matches'][-1]['confidence']=.9
   elif name=='count':g['evidence']['detectedTiles']=13
   elif name=='gap':g['evidence']['drawGap']=g['evidence']['medianGap']
   elif name=='confidence':g['confidence']=float('nan')
   else:d['index']=12
   with self.subTest(name=name):self.assertFalse(blank_draw_candidate(self.frame,h,g,d))
 @patch('sanma_friend_discard_experiment.execute_friend_discard',return_value={'status':'selection_confirmed','result':'discard_not_verified'})
 def test_bridge_only_targets_draw_and_requires_stop(self,execute):
  op=Mock();op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
  op.verified_friend_300_active=True;op.verified_friend_300_started_at=100.;op.layout={}
  with patch('sanma_friend_discard_experiment.friend_opponent_riichi_candidates',return_value=[]):
   result=execute_friend_draw_candidate(op,Mock(),copy.deepcopy(self.receipt))
  self.assertTrue(result['blankDrawIdentityUnknown']);self.assertEqual(execute.call_args.kwargs['plan']['clickIndex'],13)
  self.assertEqual(execute.call_args.kwargs['plan']['clickPoint'],self.draw['point'])
