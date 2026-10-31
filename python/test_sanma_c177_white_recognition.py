import json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from auto_operator import PythonAutoOperator
from sanma_friend_discard_experiment import experimental_draw_only_candidate,experimental_white_hand_candidate
ROOT=Path('/home/yama1/.codex/sanma-run-c177d5d-20261031')
@unittest.skipUnless((ROOT/'manual-43-before.png').exists() and Path('templates/bootstrap/1m__hf_base.png').exists(),'saved frame or model unavailable')
class RealWhiteCandidates(unittest.TestCase):
 def test_two_neutral_faces_remain_unverified_through_resident_server(self):
  child=subprocess.Popen(['node','--import','tsx','src/recognition/recognitionServer.ts','config/layout-runtime.json','templates/bootstrap','examples/public-unknown.json'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8')
  try:
   self.assertTrue(json.loads(child.stdout.readline())['ready'])
   with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent) as d:
    op=object.__new__(PythonAutoOperator);op.frames=Path(d);op.recognition_request_id=0;op.recognition_server=child;op.log=Mock();page=Mock()
    for n in (42,43):
     page.screenshot.return_value=(ROOT/f'manual-{n:02}-before.png').read_bytes()
     receipt=op.inspect_sanma_self_turn(page);report=receipt['sourceObservation']['report'];hand=report['hand']['value'];geo=report['handGeometry']['value']
     self.assertEqual(hand['tiles'][9:11],['P','P']);self.assertFalse(hand['safe'])
     self.assertEqual([(v['confidence'],v['runnerUpConfidence']) for v in hand['matches'][9:11]],[(0,0),(0,0)])
     self.assertIsNone(experimental_white_hand_candidate(page.screenshot.return_value,hand,geo))
     self.assertFalse(receipt['operationAuthorized'])
     if n==42:self.assertTrue(any(v['action']=='kita' for v in receipt['candidates']['candidates']))
     else:
      self.assertEqual(receipt['drawCandidate']['tile'],'7s')
      self.assertTrue(experimental_draw_only_candidate(hand,geo,receipt['drawCandidate']))
     page.mouse.click.assert_not_called()
  finally:
   child.kill();child.wait();child.stdin.close();child.stdout.close()
