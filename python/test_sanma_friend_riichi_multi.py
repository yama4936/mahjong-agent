import copy
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from PIL import Image,ImageEnhance,ImageDraw
from auto_operator import load_json
from sanma_friend_riichi_experiment import riichi_bright_slots,choose_riichi_selection,execute_friend_riichi
ROOT=Path('/home/yama1/.codex/sanma-run-dd7175d-20261031')
@unittest.skipUnless((ROOT/'manual-12-before.png').exists(),'friend frame unavailable')
class MultiRiichiTests(unittest.TestCase):
 def setUp(self):
  self.layout=load_json(Path('config/layout-runtime.json'));self.before=(ROOT/'manual-12-before.png').read_bytes()
  self.receipt=json.loads(Path('python/fixtures/sanma-dd-shape-receipt.json').read_text());self.receipt['screenshot']=str(ROOT/'manual-12-before.png')
  # Simulated tenpai values exercise ranking; labels/positions come from a
  # real frame and values here are not presented as the real hand's scores.
  for row in self.receipt['structuralPositions']['candidates']:
   if row['tile'] in ('2s','9s'):row['shanten']=0
  image=Image.open(io.BytesIO(self.before)).convert('RGB')
  for i,s in enumerate(self.layout['handSlots']+[self.layout['drawSlot']]):
   if i not in (7,12):
    box=(s['x'],s['y'],s['x']+s['width'],s['y']+s['height']);image.paste(ImageEnhance.Brightness(image.crop(box)).enhance(.53),box[:2])
  out=io.BytesIO();image.save(out,format='PNG');self.frame=out.getvalue()
 def test_real_multi_candidate_display_is_detected(self):
  frame=Path('test/fixtures/riichi-two-candidates-selection-20261020.jpg').read_bytes()
  self.assertEqual(riichi_bright_slots(frame,self.layout),[0,1,7,8,9])
 def test_synthetic_two_options_uses_evaluation_and_position(self):
  self.assertEqual(riichi_bright_slots(self.frame,self.layout),[7,12])
  self.assertEqual(choose_riichi_selection(self.frame,self.layout,self.receipt),7)
  with tempfile.TemporaryDirectory() as d:
   op=Mock();op.layout=self.layout;op.frames=Path(d);op.verified_friend_300_active=True;op.sanma_friend_action_observed_at=time.monotonic()
   page=Mock();page.screenshot.return_value=self.frame
   with patch('sanma_friend_riichi_experiment.execute_friend_pon_pass'),patch('sanma_friend_riichi_experiment.send_discard_click',return_value={}) as discard:
    execute_friend_riichi(op,page,self.receipt);self.assertEqual(discard.call_args.args[7],7)
 def test_changed_glyph_color_rejected_even_if_dark_mask_matches(self):
  image=Image.open(io.BytesIO(self.frame)).convert('RGB');slot=self.layout['handSlots'][7];count=0
  for y in range(slot['y']+10,slot['y']+slot['height']-38):
   for x in range(slot['x']+10,slot['x']+slot['width']-10):
    r,g,b=image.getpixel((x,y))
    if g-r>20 and g-b>15 and round(.299*r+.587*g+.114*b)<120:
     image.putpixel((x,y),(210,0,0));count+=1
  self.assertGreater(count,100)
  out=io.BytesIO();image.save(out,format='PNG')
  self.assertIsNone(choose_riichi_selection(out.getvalue(),self.layout,self.receipt))

 def test_missing_low_confidence_inconsistent_or_moved_are_rejected(self):
  for case in ('missing','score','low_confidence','point','digest','face'):
   r=copy.deepcopy(self.receipt);frame=self.frame
   if case=='missing':r['structuralPositions']['candidates']=[]
   if case=='score':next(x for x in r['structuralPositions']['candidates'] if x['tile']=='9s')['shanten']=1
   if case=='low_confidence':r['sourceObservation']['report']['hand']['value']['matches'][0]['confidence']=.4
   if case=='point':r['sourceObservation']['report']['handGeometry']['value']['clickPoints'][7]['x']+=5
   if case=='digest':r['digest']='0'*64
   if case=='face':
    image=Image.open(io.BytesIO(frame)).convert('RGB');ImageDraw.Draw(image).rectangle((900,960,960,1000),fill='black');out=io.BytesIO();image.save(out,format='PNG');frame=out.getvalue()
   with self.subTest(case=case):self.assertIsNone(choose_riichi_selection(frame,self.layout,r))
