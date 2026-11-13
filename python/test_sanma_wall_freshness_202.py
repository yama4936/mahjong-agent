"""202 retained images; friend-only wall fallback never authorizes input."""
import copy
import io
from PIL import Image
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from auto_operator import PythonAutoOperator
from sanma_friend_self_turn_stability import self_turn_stability

ROOT=Path('/home/yama1/server/data/dev-work/jantama/evidence202')

@unittest.skipUnless((ROOT/'operator.log').exists(),'evidence202 unavailable')
class WallFreshness202Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  rows=[json.loads(s) for s in (ROOT/'operator.log').read_text().splitlines() if s.startswith('{')]
  row=next(x for x in rows if x.get('event')=='sanma_self_turn_observed' and x['timestamp'].startswith('2026-11-12T23:32:44'))
  cls.receipt=json.loads(Path(row['receiptPath']).read_text());cls.before=Path(row['screenshot']).read_bytes();cls.after=Path(row['freshness']['screenshot']).read_bytes()
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.op=object.__new__(PythonAutoOperator);self.op.frames=Path(self.temp.name);self.op.log=Mock();self.op.verified_friend_300_active=True
  self.op.args=SimpleNamespace(rules='sanma',mode='force-auto',experimental_sanma_friend=True,experimental_sanma_self_turn_wall=True,action_deadline_ms=300000,ranked_loop=False,start_reviewed_friend_room='reviewed')
  self.source=copy.deepcopy(self.receipt['sourceObservation']);self.op.observe_sanma_resident=Mock(return_value=self.source)
  self.page=Mock();self.page.screenshot.side_effect=[self.before,self.after]
 def inspect(self):return self.op.inspect_sanma_self_turn(self.page)
 def test_real_wall_pair_is_draw_only_candidate(self):
  self.assertTrue(self_turn_stability(self.before,self.after,self.source['report']))
  r=self.inspect();self.assertEqual(r['freshness']['status'],'stable_self_turn_wall_draw_candidate')
  self.assertFalse(r['freshness']['operationAuthorized'])
  self.page.mouse.click.assert_not_called()
 def test_shared_images_match_bytes_and_remain_unchanged(self):
  with Image.open(io.BytesIO(self.before)) as first, Image.open(io.BytesIO(self.after)) as second:
   first.load(); second.load()
   before_pixels, after_pixels = first.tobytes(), second.tobytes()
   expected = self_turn_stability(self.before, self.after, self.source['report'])
   self.assertTrue(expected)
   self.assertEqual(self_turn_stability(first, second, self.source['report']), expected)
   self.assertEqual(first.tobytes(), before_pixels)
   self.assertEqual(second.tobytes(), after_pixels)
   self.assertEqual(self_turn_stability(first, second, {}), False)
   self.assertEqual(first.tobytes(), before_pixels)
   self.assertEqual(second.tobytes(), after_pixels)
 def test_opt_out_or_unverified_session_does_not_use_wall_fallback(self):
  for key in ('disabled','unverified'):
   with self.subTest(key=key):
    self.setUp()
    if key=='disabled':self.op.args.experimental_sanma_self_turn_wall=False
    else:self.op.verified_friend_300_active=False
    r=self.inspect();self.assertNotEqual(r['freshness']['status'],'stable_self_turn_wall_draw_candidate');self.assertEqual(r['freshness']['status'],'changed')
    self.page.mouse.click.assert_not_called()
 def test_win_or_unknown_draw_does_not_use_wall_fallback(self):
  for key in ('ron','tsumo','no_draw'):
   with self.subTest(key=key):
    self.setUp()
    if key=='no_draw':self.source['report']['hand']['status']='unresolved'
    else:self.source['candidates']['candidates']=[{'action':key}]
    r=self.inspect();self.assertNotEqual(r['freshness']['status'],'stable_self_turn_wall_draw_candidate')
    self.page.mouse.click.assert_not_called()
 def test_draw_only_status_cannot_select_other_shape_tile(self):
  from sanma_friend_discard_experiment import execute_friend_draw_candidate
  receipt=self.inspect();geometry=self.source['report']['handGeometry']['value']
  self.op.layout={'viewport':{'width':1920,'height':1080},'handSlots':geometry['handSlots'],
                  'drawSlot':geometry['drawSlot'],'clickPoints':geometry['clickPoints']}
  self.op.force_auto_click_budget_ms=Mock(return_value=8000)
  self.op.sanma_friend_action_observed_at=time.monotonic()
  shape={'status':'candidate','tile':self.source['report']['hand']['value']['tiles'][0],
         'index':0,'point':geometry['clickPoints'][0]}
  with patch('sanma_friend_shape_candidate.friend_shape_candidate',return_value=shape), \
       patch('sanma_friend_discard_experiment.friend_visible_full_empty_row_candidate',return_value=True), \
       patch('sanma_friend_shape_candidate.friend_non_riichi_hypothesis',return_value=True), \
       patch('sanma_friend_discard_experiment.execute_friend_discard',return_value={'status':'blocked'}) as execute:
   execute_friend_draw_candidate(self.op,self.page,receipt)
  self.assertEqual(execute.call_args.kwargs['plan']['clickIndex'],13)

 def test_friend_loop_routes_wall_status_to_guarded_draw_executor(self):
  from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
  receipt=self.inspect();geometry=self.source['report']['handGeometry']['value']
  case=ExperimentalSanmaFriendLoopTest('runTest');case.setUp();self.addCleanup(case.doCleanups)
  case.op.verified_friend_300_active=True;case.op.args.experimental_sanma_self_turn_wall=True
  case.op.layout={'viewport':{'width':1920,'height':1080},'handSlots':geometry['handSlots'],
                  'drawSlot':geometry['drawSlot'],'clickPoints':geometry['clickPoints']}
  case.op.force_auto_click_budget_ms=Mock(return_value=8000)
  case.op._sanma_friend_discard_observation=(receipt,receipt['digest'],receipt['captureStartedMonotonic'])
  case.op.inspect_sanma_self_turn.return_value=receipt;case.page.screenshot.return_value=self.before
  case.op.observe_sanma_friend_transition.return_value={'status':'unresolved','reason':'transition_not_observed','confirmed':False}
  watch=Mock();watch.alive.return_value=True
  output={'status':'selection_confirmed','result':'discard_not_verified','tile':receipt['drawCandidate']['tile'],
          'clickIndex':13,'clickPoint':receipt['drawCandidate']['point'],'frameSha256':receipt['digest']}
  with patch('auto_operator.classify_screen',return_value=('match',1)), \
       patch('sanma_friend_discard_recovery.MatchContinuity',return_value=watch), \
       patch('sanma_friend_discard_experiment.execute_friend_discard',return_value=output) as executor:
   case.op.run_experimental_sanma_friend(case.page)
  executor.assert_called_once();self.assertEqual(executor.call_args.kwargs['plan']['clickIndex'],13)

 def test_wall_only_status_refuses_non_draw_defensive_plan(self):
  from sanma_friend_discard_experiment import execute_friend_draw_candidate
  receipt=self.inspect();geometry=self.source['report']['handGeometry']['value']
  self.op.layout={'viewport':{'width':1920,'height':1080},'handSlots':geometry['handSlots'],
                  'drawSlot':geometry['drawSlot'],'clickPoints':geometry['clickPoints']}
  self.op.force_auto_click_budget_ms=Mock(return_value=8000)
  defensive={'index':0,'tile':self.source['report']['hand']['value']['tiles'][0]}
  with patch('sanma_friend_discard_experiment.friend_opponent_riichi_candidates',return_value=['left']), \
       patch('sanma_friend_discard_experiment.friend_genbutsu_candidate',return_value=defensive), \
       patch('sanma_friend_shape_candidate.friend_hand_click_geometry',return_value=True), \
       patch('sanma_friend_shape_candidate.friend_clear_riichi_rail',return_value=True), \
       patch('sanma_friend_discard_experiment.execute_friend_discard') as execute:
   with self.assertRaisesRegex(ValueError,'draw-only plan'):execute_friend_draw_candidate(self.op,self.page,receipt)
  execute.assert_not_called()

 def test_missing_wall_evidence_or_disabled_option_never_calls_executor(self):
  from sanma_friend_discard_experiment import execute_friend_draw_candidate
  receipt=self.inspect()
  with patch('sanma_friend_discard_experiment.execute_friend_discard') as execute:
   for mode in ('disabled','missing_guard','rejected','authorized'):
    with self.subTest(mode=mode):
     self.op.args.experimental_sanma_self_turn_wall=True
     bad=copy.deepcopy(receipt)
     if mode=='disabled':self.op.args.experimental_sanma_self_turn_wall=False
     elif mode=='missing_guard':del bad['freshness']['guards']['wallSelfTurn']
     elif mode=='rejected':bad['freshness']['guards']['wallSelfTurn']['outcome']='rejected'
     else:bad['freshness']['operationAuthorized']=True
     with self.assertRaisesRegex(ValueError,'wall evidence unavailable'):execute_friend_draw_candidate(self.op,self.page,bad)
   execute.assert_not_called()
  self.page.mouse.click.assert_not_called()

 def test_north_overlap_never_uses_wall_freshness_fallback(self):
  import io
  from PIL import Image
  image=Image.open(io.BytesIO(self.after)).convert('RGB')
  north=Image.open(Path(__file__).parent/'fixtures/sanma-friend-two-north-slot-dd.png').convert('RGB')
  image.paste(north,(1180,785));out=io.BytesIO();image.save(out,format='PNG')
  self.page.screenshot.side_effect=[self.before,out.getvalue()]
  result=self.inspect();self.assertNotEqual(result['freshness']['status'],'stable_self_turn_wall_draw_candidate')
  self.page.mouse.click.assert_not_called()

 def test_wall_guard_error_never_uses_fallback(self):
  def failed(*args,on_wall_error=None,**kwargs):
   on_wall_error({'errorType':'OSError','operationAuthorized':False});return False
  with patch('auto_operator.experimental_kita_glyph_stability',return_value=False), \
       patch('auto_operator.experimental_draw_glyph_stability',side_effect=failed), \
       patch('sanma_friend_self_turn_stability.self_turn_stability',return_value=True) as wall:
   result=self.inspect()
  self.assertEqual(result['freshness']['status'],'unknown');wall.assert_not_called()
  self.page.mouse.click.assert_not_called()

 def test_changed_hand_and_action_overlay_are_rejected(self):
  import io
  from PIL import Image,ImageDraw
  for rect in ((223,921,315,1072),(890,785,1135,875)):
   with self.subTest(rect=rect):
    self.setUp();image=Image.open(io.BytesIO(self.after)).convert('RGB');ImageDraw.Draw(image).rectangle(rect,fill='red');out=io.BytesIO();image.save(out,format='PNG');self.page.screenshot.side_effect=[self.before,out.getvalue()]
    r=self.inspect();self.assertNotEqual(r['freshness']['status'],'stable_self_turn_wall_draw_candidate');self.page.mouse.click.assert_not_called()
