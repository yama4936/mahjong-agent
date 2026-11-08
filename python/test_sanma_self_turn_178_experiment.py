import io,json,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from sanma_friend_self_turn_stability import self_turn_stability
BASE=Path('/home/yama1/server/data/dev-work/jantama/evidence178/artifacts2')
@unittest.skipUnless(BASE.exists(),'retained 178 evidence unavailable')
class TestSelfTurn178(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.events=[x for x in map(json.loads,(BASE/'python-operator.jsonl').read_text().splitlines()) if x['event']=='sanma_friend_discard_preclick_rejected']
  e=cls.events[0];path=Path(e['referenceScreenshot']);cls.a=path.read_bytes();cls.b=Path(e['screenshot']).read_bytes();cls.report=json.loads(path.with_suffix('.receipt.json').read_text())['sourceObservation']['report']
 def test_actual_pair_and_fail_closed(self):
  self.assertTrue(self_turn_stability(self.a,self.b,self.report))
  for box in ((904,496,1016,516),(1485,920,1578,1075),(900,785,1135,875),(905,375,1010,465),(650,300,780,380),(170,190,375,620),(250,280,310,330),(320,100,375,160)):
   with self.subTest(box=box):
    image=Image.open(io.BytesIO(self.b)).convert('RGB');ImageDraw.Draw(image).rectangle(box,fill='black');out=io.BytesIO();image.save(out,format='PNG')
    self.assertFalse(self_turn_stability(self.a,out.getvalue(),self.report))
 def test_recorded_pon_and_other_turn_are_rejected(self):
  events=[x for x in map(json.loads,(BASE/'python-operator.jsonl').read_text().splitlines()) if x.get('event')=='sanma_self_turn_observed']
  pon=next(x for x in events if '10-23-36.001478' in x.get('screenshot',''))
  self.assertFalse(self_turn_stability(self.a,Path(pon['screenshot']).read_bytes(),self.report))
  self.assertFalse(self_turn_stability(self.a,Path(pon['freshness']['screenshot']).read_bytes(),self.report))
  # Matching a later prompt to itself must not be mistaken for our turn.
  prompt=Path(pon['screenshot']).read_bytes()
  self.assertFalse(self_turn_stability(prompt,prompt,self.report))
 def test_existing_draw_path_and_opt_in_are_distinct(self):
  import inspect
  from sanma_friend_discard_experiment import execute_friend_discard
  self.assertFalse(inspect.signature(execute_friend_discard).parameters['self_turn_wall_opt_in'].default)
 def test_actual_preclick_fallback_is_opt_in_and_draw_only(self):
  import hashlib
  from unittest.mock import Mock,patch
  from sanma_friend_discard_experiment import execute_friend_discard,DiscardPreclickChanged
  tiles=self.report['hand']['value']['tiles'];points=self.report['handGeometry']['value']['clickPoints']
  slots=[{'tile':tile,**point} for tile,point in zip(tiles,points)]
  plan={'scope':'offline_untrusted_sanma_discard_plan','operationAuthorized':False,'tile':tiles[-1],'clickIndex':len(slots)-1,'clickPoint':points[-1]}
  obs={'status':'candidate','phase':'self_turn','promptStatus':'none','handStatus':'candidate','layoutStatus':'candidate','slots':slots,'frameSha256':hashlib.sha256(self.a).hexdigest(),'referenceFrame':self.a,'experimentalDrawReport':self.report}
  session={'mode':'cpu_friend','rules':'sanma','clock':'300+0','actionDeadlineMs':300000,'ranked':False,'cpuCount':2,'roomVerified':True}
  page=Mock();page.screenshot.return_value=self.b
  kwargs={'session':session,'observation':obs,'plan':plan,'layout':{'viewport':{'width':1920,'height':1080}},'log':lambda e:None,'turn_started_monotonic':100,'clock':lambda:101}
  with patch('sanma_friend_discard_experiment.send_discard_click') as send:
   with self.assertRaises(DiscardPreclickChanged):execute_friend_discard(page,**kwargs)
   send.assert_not_called()
   result=execute_friend_discard(page,**kwargs,self_turn_wall_opt_in=True)
   send.assert_called_once();self.assertEqual(result['result'],'discard_not_verified')
   send.reset_mock()
   other={**plan,'tile':tiles[0],'clickIndex':0,'clickPoint':points[0]}
   with self.assertRaises(DiscardPreclickChanged):execute_friend_discard(page,**{**kwargs,'plan':other},self_turn_wall_opt_in=True)
   send.assert_not_called()
   with self.assertRaises(ValueError):execute_friend_discard(page,**{**kwargs,'session':{**session,'ranked':True}},self_turn_wall_opt_in=True)
   send.assert_not_called()
 def test_other_round_and_real_kan_prompt(self):
  root=Path('/home/yama1/server/data/dev-work/jantama/evidence177')
  if not root.exists():self.skipTest('retained evidence177 unavailable')
  for name in ('progress1.png','progress2.png','progress3.png'):
   with self.subTest(image=name):
    frame=(root/name).read_bytes()
    self.assertFalse(self_turn_stability(frame,frame,self.report))
    self.assertFalse(self_turn_stability(self.a,frame,self.report))

class SyntheticWallSafetyTests(unittest.TestCase):
 def test_portable_lamp_and_wall_fences(self):
  from unittest.mock import patch
  image=Image.new('RGB',(1920,1080),(20,30,60));ImageDraw.Draw(image).rectangle((904,496,1015,515),fill=(250,200,50))
  output=io.BytesIO();image.save(output,format='PNG');base=output.getvalue()
  report={'handGeometry':{'value':{'drawSlot':{'x':1485,'y':921,'width':93,'height':151}}}}
  def encode(im):
   output=io.BytesIO();im.save(output,format='PNG');return output.getvalue()
  with patch('auto_operator.experimental_draw_glyph_stability',return_value=True):
   self.assertTrue(self_turn_stability(base,base,report))
   for box,color in (((904,496,1015,515),(0,0,0)),((170,190,375,620),(0,0,0)),((1495,880,1565,915),(255,255,255))):
    with self.subTest(box=box):
     changed=image.copy();ImageDraw.Draw(changed).rectangle(box,fill=color)
     self.assertFalse(self_turn_stability(base,encode(changed),report))

@unittest.skipUnless(Path('/home/yama1/server/data/dev-work/jantama/evidence177/progress3.png').exists(), 'retained raised-tile evidence unavailable')
class RaisedFriendDiscardTests(unittest.TestCase):
 def test_raised_tile_stops_all_preclick_match_paths(self):
  import hashlib
  from unittest.mock import Mock, patch
  from auto_operator import raised_closed_hand_slots
  from sanma_friend_discard_experiment import execute_friend_discard
  events=[x for x in map(json.loads,(BASE/'python-operator.jsonl').read_text().splitlines()) if x['event']=='sanma_friend_discard_preclick_rejected']
  p=Path(events[0]['referenceScreenshot']);rep=json.loads(p.with_suffix('.receipt.json').read_text())['sourceObservation']['report'];geo=rep['handGeometry']['value'];tiles=rep['hand']['value']['tiles'];points=geo['clickPoints'];layout={'viewport':{'width':1920,'height':1080},'handSlots':geo['handSlots'],'drawSlot':geo['drawSlot']}
  self.assertEqual(raised_closed_hand_slots(p.read_bytes(),layout),[])
  frame=Path('/home/yama1/server/data/dev-work/jantama/evidence177/progress3.png').read_bytes()
  self.assertIn(13,raised_closed_hand_slots(frame,layout))
  slots=[{'tile':t,**q} for t,q in zip(tiles,points)];plan={'scope':'offline_untrusted_sanma_discard_plan','operationAuthorized':False,'tile':tiles[-1],'clickIndex':13,'clickPoint':points[-1]}
  session={'mode':'cpu_friend','rules':'sanma','clock':'300+0','actionDeadlineMs':300000,'ranked':False,'cpuCount':2,'roomVerified':True}
  page=Mock();page.screenshot.return_value=frame
  for matching in ('identical','friend','fallback'):
   with self.subTest(matching=matching),patch('sanma_friend_discard_experiment.send_discard_click') as send,patch('sanma_friend_discard_experiment.friend_frame_stable',return_value=matching=='friend'),patch('sanma_friend_self_turn_stability.self_turn_stability',return_value=True):
    ref=frame if matching=='identical' else p.read_bytes()
    obs={'status':'candidate','phase':'self_turn','promptStatus':'none','handStatus':'candidate','layoutStatus':'candidate','slots':slots,'frameSha256':hashlib.sha256(ref).hexdigest(),'referenceFrame':ref,'experimentalDrawReport':rep}
    with self.assertRaisesRegex(ValueError,'selected or hovered tile'):
     execute_friend_discard(page,session=session,observation=obs,plan=plan,layout=layout,log=lambda _:None,turn_started_monotonic=100,clock=lambda:101,self_turn_wall_opt_in=True)
    send.assert_not_called()
