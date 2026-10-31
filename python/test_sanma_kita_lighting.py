import io,json,unittest,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image,ImageDraw
from auto_operator import experimental_kita_glyph_stability,PythonAutoOperator

DATA=Path('/home/yama1/projects/jantama-test-tmp/bf-recognized.json')
ROOT=Path('/home/yama1/.codex/sanma-run-bf336af-20261031/frames')
A=ROOT/'2026-10-31T02-31-28.810981+00-00.c512a926f3bd448da7c21964ab4b29d3.sanma-self-turn.png'
B=ROOT/'2026-10-31T02-31-32.215142+00-00.3a0d76469dd140f19511f89602661600.sanma-freshness.png'
@unittest.skipUnless(all(p.exists() for p in (A,B,DATA)),'saved friend observations missing')
class KitaLightingTests(unittest.TestCase):
 def setUp(self):
  self.a=A.read_bytes();self.b=B.read_bytes();self.report=json.loads(DATA.read_text())['sourceObservation']['report']
 def test_real_lighting_change_keeps_unverified_candidate(self):
  self.assertTrue(experimental_kita_glyph_stability(self.a,self.b,self.report))
 def test_changed_tile_button_or_center_rejected(self):
  for box in ((1100,900,1160,1010),(950,800,1050,850),(935,405,980,445)):
   image=Image.open(io.BytesIO(self.b)).convert('RGB');ImageDraw.Draw(image).rectangle(box,fill=(0,0,0))
   out=io.BytesIO();image.save(out,format='PNG')
   with self.subTest(box=box):self.assertFalse(experimental_kita_glyph_stability(self.a,out.getvalue(),self.report))
 def test_unchecked_river_or_red_glyph_changes_are_rejected(self):
  image=Image.open(io.BytesIO(self.b)).convert('RGB')
  ImageDraw.Draw(image).rectangle((460,510,500,550),fill=(255,255,255))
  out=io.BytesIO();image.save(out,format='PNG')
  self.assertFalse(experimental_kita_glyph_stability(self.a,out.getvalue(),self.report))
  image=Image.open(io.BytesIO(self.b)).convert('RGB')
  slot=self.report['handGeometry']['value']['handSlots']
  changed=0
  for rect in slot:
   for y in range(rect['y'],rect['y']+rect['height']):
    for x in range(rect['x'],rect['x']+rect['width']):
     r,g,b=image.getpixel((x,y))
     if r-g>35 and r-b>35:
      image.putpixel((x,y),(g,r,b));changed+=1
  self.assertGreater(changed,20)
  out=io.BytesIO();image.save(out,format='PNG')
  self.assertFalse(experimental_kita_glyph_stability(self.a,out.getvalue(),self.report))
 def test_kita_button_replaced_by_ron_is_rejected(self):
  image=Image.open(io.BytesIO(self.b)).convert('RGB')
  for name in ('tsumo','pon'):
   replacement=Image.open(f'test/fixtures/sanma-buttons/{name}.png').convert('RGB').resize((245,90))
   changed=image.copy();changed.paste(replacement,(890,785))
   out=io.BytesIO();changed.save(out,format='PNG')
   self.assertFalse(experimental_kita_glyph_stability(self.a,out.getvalue(),self.report))

 def test_kita_button_replaced_with_actual_ron_crop_rejected(self):
  image=Image.open(io.BytesIO(self.b)).convert('RGB')
  row=Image.open('test/fixtures/ron-button-rows/ron2.png').convert('RGB')
  image.paste(row.crop((290,0,535,90)),(890,785))
  out=io.BytesIO();image.save(out,format='PNG')
  self.assertFalse(experimental_kita_glyph_stability(self.a,out.getvalue(),self.report))

 def test_ambiguous_button_or_unknown_hand_rejected(self):
  self.report['buttonRow']['value']['slots'][1]['action']='ron'
  self.assertFalse(experimental_kita_glyph_stability(self.a,self.b,self.report))
 def test_observation_and_preclick_recheck_reach_only_mock_kita(self):
  with tempfile.TemporaryDirectory() as d:
   op=object.__new__(PythonAutoOperator);op.frames=Path(d);op.log=Mock();op.screen_references={}
   op.args=SimpleNamespace(rules='sanma',mode='force-auto',experimental_sanma_friend=True,
      action_deadline_ms=300000,ranked_loop=False,start_reviewed_friend_room='reviewed')
   op.verified_friend_300_active=True;op.sanma_friend_action_observed_at=time.monotonic()
   data=json.loads(DATA.read_text());op.observe_sanma_resident=Mock(return_value=data['sourceObservation'])
   page=Mock();page.screenshot.side_effect=[self.a,self.b,self.b,self.b]
   receipt=op.inspect_sanma_self_turn(page)
   self.assertEqual(receipt['freshness']['status'],'stable_kita_glyph_candidate')
   with patch('auto_operator.classify_screen',return_value=('match',1.0)):
    result=op.execute_sanma_friend_kita_candidate(page,receipt)
   page.mouse.click.assert_called_once_with(1012.5,830.0)
   self.assertEqual(result['confirmation'],'unknown')
