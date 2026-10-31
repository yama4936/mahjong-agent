import io,json,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from auto_operator import closed_hand_face_mismatches,crop_screenshot,tile_face_structure_delta
ROOT=Path('/home/yama1/.codex/sanma-run-c177d5d-20261031/frames')

def original(a,b,layout,threshold):
 result=[]
 for index,slot in enumerate([*layout['handSlots'],layout['drawSlot']]):
  face={'x':float(slot['x'])+10,'y':float(slot['y'])+10,'width':float(slot['width'])-20,'height':float(slot['height'])-38}
  delta=tile_face_structure_delta(crop_screenshot(a,face),crop_screenshot(b,face))
  if delta>threshold:result.append({'index':index,'faceStructureDelta':round(delta,3)})
 return result

@unittest.skipUnless(ROOT.exists(),'saved friend frames unavailable')
class ClosedHandFastEquivalence(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.a=next(ROOT.glob('*10-57-19*sanma-self-turn.png')).read_bytes()
  cls.b=next(ROOT.glob('*10-57-25*sanma-freshness.png')).read_bytes()
  report=json.loads((Path(__file__).parent/'fixtures/sanma-c177-kita-report.json').read_text())
  geometry=report['handGeometry']['value'];cls.layout={'handSlots':geometry['handSlots'],'drawSlot':geometry['drawSlot']}
 def test_equivalent_real_and_changed_faces(self):
  im=Image.open(io.BytesIO(self.b)).convert('RGB');ImageDraw.Draw(im).rectangle((1100,950,1150,1010),fill='black');o=io.BytesIO();im.save(o,format='PNG')
  for after in (self.a,self.b,o.getvalue()):
   for threshold in (.5,10):
    self.assertEqual(closed_hand_face_mismatches(self.a,after,self.layout,threshold),original(self.a,after,self.layout,threshold))
 def test_unreadable_frames_fail_closed(self):
  self.assertEqual(closed_hand_face_mismatches(b'bad',self.b,self.layout,.5),[{'index':-1,'faceStructureDelta':None}])
