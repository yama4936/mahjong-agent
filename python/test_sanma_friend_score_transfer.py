import io,tempfile,unittest,hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from PIL import Image,ImageDraw
from auto_operator import PythonAutoOperator,experimental_friend_score_transfer_candidate,load_json,clip_for_hand
from screen_state import classify_screen,load_references
ROOT=Path('/home/yama1/.codex/sanma-run-bf336af-20261031')
A=ROOT/'east3-end-4.png';B=ROOT/'east3-end-7.png'
REFS=Path('/home/yama1/projects/jantama-auto/artifacts/live')
@unittest.skipUnless(all(p.exists() for p in (A,B,REFS)),'saved friend transition unavailable')
class ScoreTransferTests(unittest.TestCase):
 def test_real_score_transfer_is_wait_candidate_not_result(self):
  frame=A.read_bytes();self.assertTrue(experimental_friend_score_transfer_candidate(frame))
  self.assertFalse(experimental_friend_score_transfer_candidate(B.read_bytes()))
  refs=load_references(REFS);self.assertEqual(classify_screen(frame,refs)[0],'away');self.assertEqual(classify_screen(B.read_bytes(),refs)[0],'match')
  with tempfile.TemporaryDirectory() as d:
   op=object.__new__(PythonAutoOperator);op.frames=Path(d);op.verified_friend_300_active=True;op.screen_references=refs
   layout=load_json(Path('config/layout-runtime.json'));op.hand_clip=clip_for_hand(layout);op.river_clip=layout['publicTileRegions']['ownDiscards']
   before=op.frames/'before.png';before.write_bytes(B.read_bytes());page=Mock();page.screenshot.return_value=frame
   result=op.observe_sanma_friend_transition(page,{'screenshot':str(before),'digest':hashlib.sha256(B.read_bytes()).hexdigest()},'discard')
   self.assertEqual(result['status'],'round_end_candidate');self.assertFalse(result['confirmed']);page.mouse.click.assert_not_called()
 def test_destroyed_score_panel_is_not_accepted(self):
  im=Image.open(A).convert('RGB');ImageDraw.Draw(im).rectangle((740,225,805,300),fill=(0,0,0));out=io.BytesIO();im.save(out,format='PNG')
  self.assertFalse(experimental_friend_score_transfer_candidate(out.getvalue()))
 def test_loop_logs_transfer_and_waits_for_next_deal_without_click(self):
  with tempfile.TemporaryDirectory() as d:
   op=object.__new__(PythonAutoOperator);op.frames=Path(d);op.verified_friend_300_active=True;op.screen_references=load_references(REFS)
   op.args=SimpleNamespace(rules='sanma',mode='force-auto',experimental_sanma_friend=True,action_deadline_ms=300000,
                           ranked_loop=False,start_reviewed_friend_room='reviewed.png',max_iterations=3)
   op.log=Mock();op.inspect_sanma_self_turn=Mock(return_value={'candidates':{'candidates':[]},
       'drawCandidate':{'status':'unresolved'},'digest':'fixture','screenshot':str(B)})
   page=Mock();page.screenshot.side_effect=[B.read_bytes(),A.read_bytes(),B.read_bytes()]
   op.run_experimental_sanma_friend(page)
   self.assertTrue(any(c.args[0]=='sanma_friend_score_transfer_candidate' and c.kwargs.get('confirmed') is False for c in op.log.call_args_list))
   self.assertTrue(any(c.args[0]=='sanma_friend_round_transition_reobserved' for c in op.log.call_args_list))
   page.mouse.click.assert_not_called()

DD=Path('/home/yama1/.codex/sanma-run-dd7175d-20261031')
@unittest.skipUnless((DD/'manual-42-after-3.png').exists(),'saved second round transition unavailable')
class IndependentScoreTransferTests(unittest.TestCase):
 def test_actual_score_overlay_and_nonresults(self):
  for n in (2,3):self.assertTrue(experimental_friend_score_transfer_candidate((DD/f'manual-42-after-{n}.png').read_bytes()))
  for n in (0,1,4,5):self.assertFalse(experimental_friend_score_transfer_candidate((DD/f'manual-42-after-{n}.png').read_bytes()))
  im=Image.open(DD/'manual-42-after-3.png').convert('RGB');ImageDraw.Draw(im).rectangle((1186,480,1251,555),fill='black');out=io.BytesIO();im.save(out,format='PNG')
  self.assertFalse(experimental_friend_score_transfer_candidate(out.getvalue()))
 def test_transition_detects_round_result_classified_overlay_without_click(self):
  with tempfile.TemporaryDirectory() as d:
   op=object.__new__(PythonAutoOperator);op.frames=Path(d);op.verified_friend_300_active=True;op.screen_references=load_references(REFS)
   layout=load_json(Path('config/layout-runtime.json'));op.hand_clip=clip_for_hand(layout);op.river_clip=layout['publicTileRegions']['ownDiscards']
   before=op.frames/'before.png';before.write_bytes(B.read_bytes());page=Mock();page.screenshot.return_value=(DD/'manual-42-after-3.png').read_bytes()
   result=op.observe_sanma_friend_transition(page,{'screenshot':str(before),'digest':hashlib.sha256(B.read_bytes()).hexdigest()},'discard')
   self.assertEqual(result['status'],'round_end_candidate');self.assertFalse(result['confirmed']);page.mouse.click.assert_not_called()
 def test_loop_reobserves_changing_result_as_transfer_without_click(self):
  with tempfile.TemporaryDirectory() as d:
   op=object.__new__(PythonAutoOperator);op.frames=Path(d);op.verified_friend_300_active=True;op.screen_references=load_references(REFS)
   op.args=SimpleNamespace(rules='sanma',mode='force-auto',experimental_sanma_friend=True,action_deadline_ms=300000,
                           ranked_loop=False,start_reviewed_friend_room='reviewed.png',max_iterations=4)
   op.log=Mock();op.inspect_sanma_self_turn=Mock(return_value={'candidates':{'candidates':[]},'drawCandidate':{'status':'unresolved'},'digest':'fixture','screenshot':str(B)})
   page=Mock();page.screenshot.side_effect=[B.read_bytes()]+[(DD/f'manual-42-after-{n}.png').read_bytes() for n in (1,2,3,5)]
   op.run_experimental_sanma_friend(page)
   self.assertTrue(any(c.args[0]=='sanma_friend_score_transfer_candidate' and c.kwargs.get('confirmed') is False for c in op.log.call_args_list))
   self.assertTrue(any(c.args[0]=='sanma_friend_round_transition_reobserved' for c in op.log.call_args_list))
   page.mouse.click.assert_not_called()

CONT=Path('/home/yama1/.codex/sanma-run-6c090e6-20261031/continuous')
def continuous_frame(n):
 return next(CONT.glob(f'frame-{n:06d}-*.png')).read_bytes()
@unittest.skipUnless(CONT.exists(),'saved 6c friend transition unavailable')
class ContinuousScoreTransferTests(unittest.TestCase):
 def test_real_sequence_and_destroyed_panel(self):
  refs=load_references(REFS)
  self.assertEqual(classify_screen(continuous_frame(465),refs)[0],'round_result')
  self.assertEqual(classify_screen(continuous_frame(467),refs)[0],'round_result')
  self.assertEqual(classify_screen(continuous_frame(469),refs)[0],'match')
  for n in (466,467):self.assertTrue(experimental_friend_score_transfer_candidate(continuous_frame(n)))
  for n in (465,468,469):self.assertFalse(experimental_friend_score_transfer_candidate(continuous_frame(n)))
  for n in (466,467):
   im=Image.open(io.BytesIO(continuous_frame(n))).convert('RGB');ImageDraw.Draw(im).rectangle((1186,480,1251,555),fill='black');out=io.BytesIO();im.save(out,format='PNG')
   self.assertFalse(experimental_friend_score_transfer_candidate(out.getvalue()))
 def test_other_overlay_covering_inner_panel_is_not_score_transfer(self):
  frame=continuous_frame(466)
  for box in ((940,300,1010,330),(1390,555,1460,585),(940,840,1010,870)):
   im=Image.open(io.BytesIO(frame)).convert('RGB');ImageDraw.Draw(im).rectangle(box,fill='black');out=io.BytesIO();im.save(out,format='PNG')
   with self.subTest(box=box):self.assertFalse(experimental_friend_score_transfer_candidate(out.getvalue()))

 def test_loop_reobserves_score_animation_without_click(self):
  with tempfile.TemporaryDirectory() as d:
   op=object.__new__(PythonAutoOperator);op.frames=Path(d);op.verified_friend_300_active=True;op.screen_references=load_references(REFS)
   op.args=SimpleNamespace(rules='sanma',mode='force-auto',experimental_sanma_friend=True,action_deadline_ms=300000,ranked_loop=False,start_reviewed_friend_room='reviewed.png',max_iterations=4)
   op.log=Mock();op.inspect_sanma_self_turn=Mock(return_value={'candidates':{'candidates':[]},'drawCandidate':{'status':'unresolved'},'digest':'fixture','screenshot':str(B)})
   page=Mock();page.screenshot.side_effect=[continuous_frame(n) for n in (464,465,466,467,469)]
   op.run_experimental_sanma_friend(page)
   self.assertTrue(any(c.args[0]=='sanma_friend_score_transfer_candidate' and c.kwargs.get('confirmed') is False for c in op.log.call_args_list))
   self.assertTrue(any(c.args[0]=='sanma_friend_round_transition_reobserved' for c in op.log.call_args_list))
   page.mouse.click.assert_not_called()
