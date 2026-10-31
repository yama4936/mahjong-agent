import io,json,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from auto_operator import experimental_kita_glyph_stability
ROOT=Path('/home/yama1/.codex/sanma-run-c177d5d-20261031/frames')
@unittest.skipUnless(ROOT.exists(),'saved friend frames unavailable')
class KitaC177LightingTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.report=json.loads((Path(__file__).parent/'fixtures/sanma-c177-kita-report.json').read_text())
  cls.pairs=[]
  for before,after in (('10-57-19','10-57-25'),('10-58-56','10-59-02')):
   a=next(ROOT.glob(f'*{before}*sanma-self-turn.png')).read_bytes()
   b=next(ROOT.glob(f'*{after}*sanma-freshness.png')).read_bytes()
   cls.pairs.append((a,b))
 def test_two_real_pairs_are_lighting_candidates(self):
  for a,b in self.pairs:
   with self.subTest(a=a[:40]):self.assertTrue(experimental_kita_glyph_stability(a,b,self.report))
 def test_changed_hand_buttons_and_rivers_still_rejected(self):
  for a,b in self.pairs:
   for box in ((1100,950,1150,1010),(900,800,1000,850),(850,850,875,865),(620,300,650,330),(680,330,730,370),(1140,330,1190,370),(850,230,900,270)):
    im=Image.open(io.BytesIO(b)).convert('RGB');ImageDraw.Draw(im).rectangle(box,fill=(0,0,0));out=io.BytesIO();im.save(out,format='PNG')
    with self.subTest(box=box):self.assertFalse(experimental_kita_glyph_stability(a,out.getvalue(),self.report))
 def test_wall_or_lamp_significant_change_still_rejected(self):
  a,b=self.pairs[-1]
  for box in ((320,96,351,127),(896,480,927,511)):
   im=Image.open(io.BytesIO(b)).convert('RGB');ImageDraw.Draw(im).rectangle(box,fill=(255,255,255));out=io.BytesIO();im.save(out,format='PNG')
   with self.subTest(box=box):self.assertFalse(experimental_kita_glyph_stability(a,out.getvalue(),self.report))
 def test_real_later_turn_with_different_rivers_and_hand_is_rejected(self):
  after=ROOT.parent/'continuous'/'frame-000074-2026-10-31T11-05-06-295Z.png'
  if not after.exists():self.skipTest('later live frame unavailable')
  for before,_ in self.pairs:
   self.assertFalse(experimental_kita_glyph_stability(before,after.read_bytes(),self.report))
 def test_real_opponent_discards_and_riichi_stick_are_rejected(self):
  later=ROOT.parent/'continuous'/'frame-000074-2026-10-31T11-05-06-295Z.png'
  riichi=Path('/home/yama1/.codex/sanma-run-41b9fb3-20261031/manual-21-before.png')
  if not later.exists() or not riichi.exists():self.skipTest('real later frames unavailable')
  before,after=self.pairs[0]
  for source,box in ((later,(680,285,780,390)),(later,(1140,470,1240,550)),(riichi,(803,350,840,470))):
   image=Image.open(io.BytesIO(after)).convert('RGB');other=Image.open(source).convert('RGB')
   image.paste(other.crop(box),box[:2]);out=io.BytesIO();image.save(out,format='PNG')
   with self.subTest(box=box):self.assertFalse(experimental_kita_glyph_stability(before,out.getvalue(),self.report))
 def test_isolated_low_contrast_blue_patch_is_not_lighting(self):
  before,_=self.pairs[0]
  for adjustment in (-11,11):
   image=Image.open(io.BytesIO(before)).convert('RGB')
   for y in range(256,272):
    for x in range(600,616):
     image.putpixel((x,y),tuple(max(0,min(255,v+adjustment)) for v in image.getpixel((x,y))))
   out=io.BytesIO();image.save(out,format='PNG')
   with self.subTest(adjustment=adjustment):self.assertFalse(experimental_kita_glyph_stability(before,out.getvalue(),self.report))
