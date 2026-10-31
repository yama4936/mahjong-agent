import hashlib
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw
import io
from sanma_friend_discard_experiment import friend_opponent_riichi_candidates, execute_friend_draw_candidate, friend_genbutsu_candidate

ROOT=Path('/home/yama1/.codex/sanma-run-41b9fb3-20261031')
@unittest.skipUnless((ROOT/'manual-21-before.png').exists(),'friend-match captures unavailable')
class SanmaFriendRiichiThreat(unittest.TestCase):
 def test_actual_multiple_frames_sticks_and_absence(self):
  for n in (1,10,14):self.assertEqual(friend_opponent_riichi_candidates((ROOT/f'manual-{n:02}-before.png').read_bytes()),[])
  for n in (15,16):self.assertEqual(friend_opponent_riichi_candidates((ROOT/f'manual-{n:02}-before.png').read_bytes()),['left'])
  for n in (17,18,19,20,21):self.assertEqual(friend_opponent_riichi_candidates((ROOT/f'manual-{n:02}-before.png').read_bytes()),['right','left'])
  opposite=Path('/home/yama1/.codex/sanma-run-dd7175d-20261031/manual-12-before.png')
  if opposite.exists():self.assertIn('opposite',friend_opponent_riichi_candidates(opposite.read_bytes()))
 def test_opposite_stick_is_not_dropped(self):
  frame=(ROOT/'manual-01-before.png').read_bytes()
  with patch('board_metadata.recognize_riichi_sticks',return_value=['west']):
   threats=friend_opponent_riichi_candidates(frame)
  self.assertEqual(threats,['opposite'])
  self.assertIsNone(friend_genbutsu_candidate({},'digest',threats,['1m'],[{'tile':'1m','confidence':1}]))

 def test_opposite_stick_seen_in_independent_real_frame(self):
  path=Path('/home/yama1/.codex/sanma-run-d0ff500-20261031/manual-14-before.png')
  if not path.exists():self.skipTest('independent friend image unavailable')
  self.assertIn('opposite',friend_opponent_riichi_candidates(path.read_bytes()))

 def test_red_dot_without_stick_is_not_positive(self):
  image=Image.open(ROOT/'manual-14-before.png').convert('RGB')
  ImageDraw.Draw(image).ellipse((1095,416,1105,426),fill=(220,0,0));out=io.BytesIO();image.save(out,format='PNG')
  self.assertNotIn('right',friend_opponent_riichi_candidates(out.getvalue()))
 def test_observed_sticks_stop_bridge_before_input(self):
  baseline=ROOT/'manual-21-before.png';digest=hashlib.sha256(baseline.read_bytes()).hexdigest()
  points=[{'x':100+i*10,'y':1000} for i in range(14)]
  report={'digest':digest,'hand':{'status':'candidate','value':{'safe':True,'turnReady':True,'tiles':['1m']*14}},
   'handGeometry':{'status':'candidate','value':{'clickPoints':points}},
   'buttonRow':{'status':'candidate','value':{'slots':[{'status':'empty_candidate'}]*3}}}
  receipt={'scope':'sanma_self_turn_observation','digest':digest,'screenshot':str(baseline),
      'sourceObservation':{'digest':digest,'report':report},'drawCandidate':{'status':'candidate','digest':digest,'index':13,'tile':'1m','point':points[-1]},
      'freshness':{'status':'identical_pixels_candidate'}}
  op=Mock();op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
  op.verified_friend_300_active=True;page=Mock()
  with patch('sanma_friend_discard_experiment.send_discard_click') as send:
   with self.assertRaisesRegex(ValueError,'opponent riichi candidate; safe discard unverified'):execute_friend_draw_candidate(op,page,receipt)
   send.assert_not_called();page.mouse.click.assert_not_called()
  event=next(c for c in op.log.call_args_list if c.args[0]=='sanma_friend_opponent_riichi_candidate')
  self.assertEqual(event.kwargs['opponents'],['right','left']);self.assertFalse(event.kwargs['confirmed'])
 def test_candidates_must_belong_to_every_threat_and_same_frame(self):
  digest=hashlib.sha256((ROOT/'manual-21-before.png').read_bytes()).hexdigest()
  def river(side,tile,confidence=1):
   return {'scope':f'offline_untrusted_sanma_{side}_river','frameSha256':digest,'verified':False,'operationAuthorized':False,
           'candidates':[{'tile':tile,'confidence':confidence,'verified':False,'x':690 if side=='left' else 1150,'y':405}]}
  source={'leftRiver':river('left','9m'),'rightRiver':river('right','9m')}
  matches=[{'tile':'9m','confidence':.999}]
  self.assertEqual(friend_genbutsu_candidate(source,digest,['left','right'],['9m'],matches)['tile'],'9m')
  source['rightRiver']=river('right','1m')
  self.assertIsNone(friend_genbutsu_candidate(source,digest,['left','right'],['9m'],matches))
  source['rightRiver']=river('right','9m',.5)
  self.assertIsNone(friend_genbutsu_candidate(source,digest,['left','right'],['9m'],matches))
  source['rightRiver']=river('right','9m');source['leftRiver']['frameSha256']='stale'
  self.assertIsNone(friend_genbutsu_candidate(source,digest,['left','right'],['9m'],matches))
  source['leftRiver']=river('left','9m');source['leftRiver']['candidates'][0]['x']=1150
  self.assertIsNone(friend_genbutsu_candidate(source,digest,['left','right'],['9m'],matches))
  source['leftRiver']=river('left','0p');source['rightRiver']=river('right','5p')
  self.assertIsNone(friend_genbutsu_candidate(source,digest,['left','right'],['0p'],[{'tile':'0p','confidence':.999}]))
  source['leftRiver']=river('left','9m',2);source['rightRiver']=river('right','9m')
  self.assertIsNone(friend_genbutsu_candidate(source,digest,['left','right'],['9m'],matches))
 def test_matching_candidates_reach_only_the_experimental_click_bridge(self):
  baseline=ROOT/'manual-21-before.png';digest=hashlib.sha256(baseline.read_bytes()).hexdigest()
  layout=json.loads(Path('config/layout-runtime.json').read_text());points=layout['clickPoints'];tiles=['1m']*14
  hand={'safe':True,'turnReady':True,'tiles':tiles,'matches':[{'tile':'1m','confidence':.999} for _ in tiles]}
  report={'digest':digest,'hand':{'status':'candidate','value':hand},'handGeometry':{'status':'candidate','value':{'clickPoints':points,'handSlots':layout['handSlots'],'drawSlot':layout['drawSlot']}},
          'buttonRow':{'status':'candidate','value':{'slots':[{'status':'empty_candidate'}]*3}}}
  source={'digest':digest,'report':report}
  for side,x in (('left',690),('right',1150)):
   source[side+'River']={'scope':f'offline_untrusted_sanma_{side}_river','frameSha256':digest,'verified':False,'operationAuthorized':False,
                         'candidates':[{'tile':'1m','confidence':.999,'verified':False,'x':x,'y':405}]}
  receipt={'scope':'sanma_self_turn_observation','digest':digest,'screenshot':str(baseline),'sourceObservation':source,
           'drawCandidate':{'status':'candidate','digest':digest,'index':13,'tile':'1m','point':points[-1]},'freshness':{'status':'identical_pixels_candidate'}}
  op=Mock();op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
  op.verified_friend_300_active=True;op.verified_friend_300_started_at=time.monotonic();op.sanma_friend_riichi_attempted=False;op.layout=layout
  page=Mock();page.screenshot.return_value=baseline.read_bytes()
  with patch('sanma_friend_discard_experiment.send_discard_click',return_value={}) as send:
   result=execute_friend_draw_candidate(op,page,receipt)
  self.assertEqual(result['tile'],'1m');self.assertEqual(result['clickIndex'],0)
  self.assertEqual(result['result'],'discard_not_verified');send.assert_called_once()
  page.mouse.click.assert_not_called()
  # Agreement between recognition and configuration is insufficient when
  # both point to a different physical tile.
  bad=copy.deepcopy(receipt);bad_layout=copy.deepcopy(layout)
  bad_layout['clickPoints'][0]=dict(bad_layout['clickPoints'][1])
  bad['sourceObservation']['report']['handGeometry']['value']['clickPoints']=bad_layout['clickPoints']
  op.layout=bad_layout;op._sanma_friend_attempted_targets=set()
  with patch('sanma_friend_discard_experiment.send_discard_click') as send:
   with self.assertRaisesRegex(ValueError,'safe discard unverified'):execute_friend_draw_candidate(op,page,bad)
   send.assert_not_called()
 def test_no_detection_is_not_legal_or_safe_confirmation(self):
  # Positive-only result deliberately does not classify the opponents as safe.
  self.assertEqual(friend_opponent_riichi_candidates((ROOT/'manual-01-before.png').read_bytes()),[])

@unittest.skipUnless((ROOT/'manual-21-before.png').exists() and Path('templates/bootstrap/1m__hf_base.png').exists(),'saved frame or local model unavailable')
class ResidentRiverCandidateTests(unittest.TestCase):
 def test_real_two_frames_bind_rivers_and_hand_to_same_image(self):
  import json,subprocess
  from auto_operator import PythonAutoOperator
  child=subprocess.Popen(['node','--import','tsx','src/recognition/recognitionServer.ts','config/layout-runtime.json','templates/bootstrap','examples/public-unknown.json'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8')
  try:
   self.assertTrue(json.loads(child.stdout.readline())['ready'])
   with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent) as d:
    op=object.__new__(PythonAutoOperator);op.recognition_request_id=0;op.recognition_server=child;op.frames=Path(d);op.log=Mock();page=Mock()
    for number in (15,21):
     page.screenshot.return_value=(ROOT/f'manual-{number:02}-before.png').read_bytes()
     receipt=op.inspect_sanma_self_turn(page);source=receipt['sourceObservation'];hand=source['report']['hand']['value']
     threats=friend_opponent_riichi_candidates(page.screenshot.return_value)
     result=friend_genbutsu_candidate(source,receipt['digest'],threats,hand['tiles'],hand['matches'])
     if number==15:
      self.assertEqual(result['tile'],'2p');self.assertFalse(hand['turnReady'])
     else:self.assertIsNone(result)
     self.assertEqual(source['leftRiver']['frameSha256'],receipt['digest'])
     self.assertEqual(source['rightRiver']['frameSha256'],receipt['digest'])
     self.assertFalse(source['leftRiver']['verified']);page.mouse.click.assert_not_called()
  finally:
   child.kill();child.wait();child.stdin.close();child.stdout.close()
