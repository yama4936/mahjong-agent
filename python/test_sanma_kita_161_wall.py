"""Replay friend north prompt evidence; never accesses a live browser."""
import copy,io,json,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from auto_operator import experimental_kita_glyph_stability

F=Path('/home/yama1/server/data/dev-work/jantama/evidence161/artifacts/frames')
@unittest.skipUnless(F.exists(),'retained friend evidence unavailable')
class Kita161WallTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.before=next(F.glob('*22-13-01*sanma-self-turn.png'));cls.after=next(F.glob('*22-13-04*sanma-freshness.png'))
  cls.report=json.loads(Path(str(cls.before).replace('.png','.receipt.json')).read_text())['sourceObservation']['report']
 def test_real_wall_light_pair(self):
  self.assertTrue(experimental_kita_glyph_stability(self.before.read_bytes(),self.after.read_bytes(),self.report))
 def test_changed_ron_button_hand_river_lamp_and_wall_are_rejected(self):
  other=Path('/home/yama1/server/data/dev-work/jantama/evidence149/transitions/98abd586b8a34e508fd85e990769777e/01.png')
  for kind in ('ron','hand','river','opponent_lamp','wall','self_lamp'):
   image=Image.open(self.after).convert('RGB')
   if kind=='ron':image.paste(Image.open('test/fixtures/ron-button-rows/ron2.png').convert('RGB').crop((290,0,535,90)),(600,785))
   elif kind=='hand':ImageDraw.Draw(image).rectangle((1490,930,1550,990),fill='black')
   elif kind=='river':ImageDraw.Draw(image).rectangle((770,545,820,600),fill='white')
   elif kind=='opponent_lamp':
    if not other.exists():continue
    image.paste(Image.open(other).convert('RGB').crop((910,335,1015,352)),(910,335))
   elif kind=='self_lamp':ImageDraw.Draw(image).rectangle((910,498,1010,514),fill=(40,40,40))
   else:ImageDraw.Draw(image).rectangle((320,96,340,120),fill='black')
   out=io.BytesIO();image.save(out,format='BMP')
   with self.subTest(kind=kind):self.assertFalse(experimental_kita_glyph_stability(self.before.read_bytes(),out.getvalue(),self.report))
 def test_unknown_or_ron_slot_rejected(self):
  for action in ('ron','unknown'):
   r=copy.deepcopy(self.report);r['buttonRow']['value']['slots'][1].update(action=action)
   with self.subTest(action=action):self.assertFalse(experimental_kita_glyph_stability(self.before.read_bytes(),self.after.read_bytes(),r))
