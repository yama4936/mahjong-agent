"""Saved friend evidence and simulated inputs; no live match is claimed."""
import copy, glob, io, json, time, unittest, tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw
from sanma_friend_pon_stability import pon_pass_stability, _pon_pass_stability_impl
from sanma_friend_pass_experiment import execute_friend_pon_pass, PassPreclickChanged

ROOT=Path('/home/yama1/server/data/dev-work/jantama/evidence192/attempt/artifacts/frames')
PATHS=list(ROOT.glob('*11-35-38*.sanma-self-turn.receipt.json')) if ROOT.exists() else []
@unittest.skipUnless(PATHS,'locally saved 192 observation unavailable')
class LeftPonTrial(unittest.TestCase):
 def setUp(self):
  self.r=json.loads(PATHS[0].read_text());self.before=Path(self.r['screenshot']).read_bytes();self.after=Path(self.r['freshness']['screenshot']).read_bytes();self.report=self.r['sourceObservation']['report']
 def mutate(self,kind):
  im=Image.open(io.BytesIO(self.after)).convert('RGB');d=ImageDraw.Draw(im)
  if kind.startswith('red_at_'):
   x,y=map(int,kind[7:].split('_'));d.rectangle((x,y,x+3,y+3),fill=(255,0,0))
  if kind=='indicator': d.rectangle((832,380,856,466),fill=(0,0,0))
  if kind=='arrow': d.rectangle((710,250,760,285),fill=(0,0,0))
  if kind=='real_other_tile': im.paste(im.crop((1153,487,1224,544)),(700,290))
  if kind=='tile': im.paste(im.crop((1280,938,1346,997)),(705,290))
  if kind=='small_red':d.rectangle((733,306,736,309),fill=(255,0,0))
  if kind=='hand': im.paste(im.crop((315,938,375,995)),(225,938))
  if kind=='skip':d.rectangle((1200,800,1395,855),fill=(0,0,0))
  if kind=='board':d.rectangle((930,470,990,490),fill=(0,0,0))
  if kind=='ron':
   other=Image.open('/home/yama1/.codex/sanma-run-1740066-20261031/manual-20-before.png').convert('RGB');im.paste(other.crop((600,785,1424,875)),(600,785))
  out=io.BytesIO();im.save(out,format='PNG');return out.getvalue()
 def test_saved_pair_and_negatives(self):
  self.assertTrue(pon_pass_stability(self.before,self.after,self.report))
  for kind in ('indicator','arrow','real_other_tile','tile','small_red','hand','skip','board','ron','red_at_700_300','red_at_773_300','red_at_699_341','red_at_773_345','red_at_695_270','red_at_836_405'):
   with self.subTest(kind=kind):self.assertFalse(pon_pass_stability(self.before,self.mutate(kind),self.report))
 def test_trial_reports_the_threshold_actually_used(self):
  im=Image.open(io.BytesIO(self.after)).convert('RGB')
  ImageDraw.Draw(im).rectangle((1112,801,1119,802),fill=(255,0,0))
  out=io.BytesIO();im.save(out,format='PNG');detail={}
  self.assertFalse(_pon_pass_stability_impl(self.before,out.getvalue(),self.report,diagnostic=detail,left_candidate=True))
  self.assertEqual((detail.get('reason'),detail.get('threshold')),('row_block',30))
 def test_actual_friend_pass_bridge_uses_current_frame_guard(self):
  r=copy.deepcopy(self.r);r['freshness']['status']='stable_pon_pass_candidate';page=Mock();page.screenshot.return_value=self.after
  op=Mock();op.args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False,experimental_sanma_friend=True,experimental_sanma_pon_monitor=False);op.verified_friend_300_active=True;op.frames=ROOT;op.screen_references={}
  r['captureStartedMonotonic']=time.monotonic();op.force_auto_click_budget_ms.return_value=8000
  op._sanma_friend_discard_observation=(r,r['digest'],r['captureStartedMonotonic'])
  with patch('sanma_friend_pass_experiment.friend_action_started_at',return_value=time.monotonic()),patch('sanma_friend_pass_experiment.classify_screen',return_value=('match',1.0)),patch('sanma_friend_pass_experiment.latch_friend_action_target'),patch('sanma_friend_freshness.check_friend_recovery_guard'):
   result=execute_friend_pon_pass(op,page,r)
  page.mouse.click.assert_called_once_with(1300,830);self.assertEqual(result['confirmation'],'unknown')
  with tempfile.TemporaryDirectory() as tmp:
   op.frames=Path(tmp)
   for kind in ('ron','tile','small_red','indicator','arrow'):
    with self.subTest(kind=kind):
     page=Mock();page.screenshot.return_value=self.mutate(kind)
     with patch('sanma_friend_pass_experiment.friend_action_started_at',return_value=time.monotonic()),patch('sanma_friend_pass_experiment.classify_screen',return_value=('match',1.0)),patch('sanma_friend_pass_experiment.latch_friend_action_target'),patch('sanma_friend_freshness.check_friend_recovery_guard'):
      with self.assertRaises(PassPreclickChanged):execute_friend_pon_pass(op,page,r)
     page.mouse.click.assert_not_called()
