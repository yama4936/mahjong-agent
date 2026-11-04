"""Retained friend frames: countdown intrudes into a template background corner."""
import io,json,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from sanma_friend_pon_stability import pon_pass_stability

F=Path('/home/yama1/server/data/dev-work/jantama/evidence168')
@unittest.skipUnless((F/'operator.log').exists(),'retained friend evidence unavailable')
class PonClock168(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  es=[json.loads(x) for x in (F/'operator.log').read_text().splitlines()]
  event=next(e for e in es if e.get('event')=='sanma_self_turn_observed' and e['timestamp'].startswith('2026-11-04T02:09:38'))
  cls.before=Path(event['screenshot']).read_bytes();cls.after=Path(event['freshness']['screenshot']).read_bytes()
  cls.report=json.loads(Path(event['receiptPath']).read_text())['sourceObservation']['report']
 def test_reviewed_countdown_pair(self):self.assertTrue(pon_pass_stability(self.before,self.after,self.report))
 def test_prompt_ron_hand_and_river_changes_rejected(self):
  for kind in ('skip','pon','ron','hand','river'):
   im=Image.open(io.BytesIO(self.after)).convert('RGB')
   if kind=='ron':im.paste(Image.open('test/fixtures/ron-button-rows/ron2.png').convert('RGB').crop((290,0,535,90)),(600,785))
   else:ImageDraw.Draw(im).rectangle({'skip':(1250,810,1300,840),'pon':(950,810,1000,840),'hand':(500,930,550,1000),'river':(770,545,820,600)}[kind],fill='white')
   out=io.BytesIO();im.save(out,format='BMP')
   with self.subTest(kind=kind):self.assertFalse(pon_pass_stability(self.before,out.getvalue(),self.report))
