import io,json,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from auto_operator import experimental_kita_glyph_stability
ROOT=Path('/home/yama1/.codex/sanma-run-6c090e6-20261031')
@unittest.skipUnless((ROOT/'python-operator.jsonl').exists(),'friend capture unavailable')
class Kita6cLightingTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.report=json.loads((Path(__file__).parent/'fixtures/sanma-6c-kita-report.json').read_text())
  cls.rows=[json.loads(x) for x in (ROOT/'python-operator.jsonl').read_text().splitlines() if 'sanma_self_turn_observed' in x]
 def test_real_frames_lamp_changes_can_reach_candidate(self):
  for i in (7,10):
   row=self.rows[i];a=Path(row['screenshot']).read_bytes();b=Path(row['freshness']['screenshot']).read_bytes()
   with self.subTest(pair=i):self.assertEqual(row['freshness']['status'],'changed');self.assertTrue(experimental_kita_glyph_stability(a,b,self.report))
 def test_changed_hand_button_gap_and_river_are_rejected(self):
  row=self.rows[7];a=Path(row['screenshot']).read_bytes();b=Path(row['freshness']['screenshot']).read_bytes()
  for box in ((1300,940,1350,1000),(900,800,1000,850),(850,850,875,865),(900,550,950,580)):
   image=Image.open(io.BytesIO(b)).convert('RGB');ImageDraw.Draw(image).rectangle(box,fill=(250,0,0));out=io.BytesIO();image.save(out,format='PNG')
   with self.subTest(box=box):self.assertFalse(experimental_kita_glyph_stability(a,out.getvalue(),self.report))

 def test_same_luminance_changes_in_river_rejected(self):
  row=self.rows[7];a=Path(row['screenshot']).read_bytes();b=Path(row['freshness']['screenshot']).read_bytes()
  image=Image.open(io.BytesIO(b)).convert('RGB');ImageDraw.Draw(image).rectangle((900,550,950,580),fill=(20,20,20));out=io.BytesIO();image.save(out,format='PNG')
  self.assertFalse(experimental_kita_glyph_stability(a,out.getvalue(),self.report))

 def test_opponent_river_same_dark_class_is_rejected(self):
  row=self.rows[7];a=Path(row['screenshot']).read_bytes();b=Path(row['freshness']['screenshot']).read_bytes()
  for box in ((680,330,730,370),(1140,330,1190,370),(850,230,900,270)):
   image=Image.open(io.BytesIO(b)).convert('RGB');ImageDraw.Draw(image).rectangle(box,fill=(0,0,0));out=io.BytesIO();image.save(out,format='PNG')
   with self.subTest(box=box):self.assertFalse(experimental_kita_glyph_stability(a,out.getvalue(),self.report))
