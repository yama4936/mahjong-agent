import hashlib,subprocess,tempfile,time,unittest,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from auto_operator import PythonAutoOperator,load_json,clip_for_hand
from screen_state import load_references
from sanma_friend_discard_experiment import execute_friend_draw_candidate
ROOT=Path('/home/yama1/.codex/sanma-run-c177d5d-20261031')
REFS=Path('/home/yama1/projects/jantama-auto/artifacts/live')
@unittest.skipUnless((ROOT/'manual-42-after.png').exists() and REFS.exists(),'saved friend transition unavailable')
class C177KitaTransitionTests(unittest.TestCase):
 def test_real_hand_and_north_change_allows_unconfirmed_transition(self):
  before=ROOT/'manual-42-before.png';after=ROOT/'manual-42-after.png'
  with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent) as d:
   op=object.__new__(PythonAutoOperator);op.frames=Path(d);op.verified_friend_300_active=True;op.screen_references=load_references(REFS)
   layout=load_json(Path('config/layout-runtime.json'));op.hand_clip=clip_for_hand(layout);op.river_clip=layout['publicTileRegions']['ownDiscards']
   page=Mock();page.screenshot.return_value=after.read_bytes()
   result=op.observe_sanma_friend_transition(page,{'screenshot':str(before),'digest':hashlib.sha256(before.read_bytes()).hexdigest()},'kita')
   self.assertEqual(result['status'],'visual_change_unconfirmed');self.assertFalse(result['confirmed'])
   self.assertGreaterEqual(result['handDelta'],1.5);self.assertGreaterEqual(result['otherDelta'],1.0)
   self.assertEqual(page.screenshot.call_count,2);page.mouse.click.assert_not_called()
 def test_real_post_kita_observation_reaches_distinct_unconfirmed_discard(self):
  child=subprocess.Popen(['node','--import','tsx','src/recognition/recognitionServer.ts','config/layout-runtime.json','templates/bootstrap','examples/public-unknown.json'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8')
  try:
   self.assertTrue(json.loads(child.stdout.readline())['ready'])
   with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent) as d:
    op=object.__new__(PythonAutoOperator);op.frames=Path(d);op.recognition_request_id=0;op.recognition_server=child;op.log=Mock()
    op.args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False,experimental_sanma_friend=True,start_reviewed_friend_room='reviewed.png')
    op.verified_friend_300_active=True;op.verified_friend_300_started_at=time.monotonic();op.sanma_friend_riichi_attempted=False;op.layout=load_json(Path('config/layout-runtime.json'))
    page=Mock();page.screenshot.return_value=(ROOT/'manual-42-after.png').read_bytes();receipt=op.inspect_sanma_self_turn(page)
    self.assertEqual(receipt['candidates']['candidates'],[]);self.assertEqual(receipt['drawCandidate']['tile'],'7s')
    with patch('sanma_friend_discard_experiment.send_discard_click',return_value={}) as send:
     action=execute_friend_draw_candidate(op,page,receipt)
    self.assertEqual((action['tile'],action['clickIndex']),('7s',13));self.assertEqual(action['result'],'discard_not_verified');send.assert_called_once();page.mouse.click.assert_not_called()
  finally:
   child.kill();child.wait();child.stdin.close();child.stdout.close()
