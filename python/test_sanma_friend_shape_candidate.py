import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sanma_friend_shape_candidate import friend_shape_candidate
from sanma_friend_discard_experiment import execute_friend_draw_candidate

ROOT=Path('/home/yama1/.codex/sanma-run-dd7175d-20261031')
@unittest.skipUnless((ROOT/'manual-12-before.png').exists(),'friend frame unavailable')
class ShapeCandidateTests(unittest.TestCase):
 def setUp(self):
  self.receipt=json.loads((Path(__file__).parent/'fixtures/sanma-dd-shape-receipt.json').read_text())
 def test_real_shape_and_live_counts_not_claimed(self):
  result=friend_shape_candidate(self.receipt)
  self.assertEqual((result['tile'],result['shanten'],result['improvingDrawUpperBound']),('9s',2,51))
  self.assertEqual(result['riichiStatus'],'unknown');self.assertFalse(result['operationAuthorized'])
 def test_missing_and_conflicting_evidence_unresolved(self):
  for variant in ('digest','points','total','missing'):
   with self.subTest(variant=variant):
    r=copy.deepcopy(self.receipt)
    if variant=='digest':r['structuralPositions']['digest']='0'*64
    elif variant=='points':r['structuralPositions']['candidates'][0]['positions'][0]['point']['x']=-1
    elif variant=='total':r['structuralPositions']['candidates'][0]['maximumUnseenTotal']+=1
    else:r['structuralPositions']['candidates']=[]
    self.assertEqual(friend_shape_candidate(r)['status'],'unresolved')
 def test_shape_hypothesis_logged_but_unknown_riichi_draw_only(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'before.png';p.write_bytes((ROOT/'manual-12-before.png').read_bytes());self.receipt['screenshot']=str(p)
   op=Mock();op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
   op.verified_friend_300_active=True;op.verified_friend_300_started_at=time.monotonic();op.layout={}
   with patch('sanma_friend_discard_experiment.execute_friend_discard') as execute:
    execute_friend_draw_candidate(op,Mock(),self.receipt)
    self.assertEqual(execute.call_args.kwargs['plan']['tile'],'7p')
    event=next(c for c in op.log.call_args_list if c.args[0]=='sanma_friend_shape_candidate')
    self.assertEqual(event.kwargs['candidate']['tile'],'9s');self.assertEqual(event.kwargs['selectedAction'],'draw_only')
