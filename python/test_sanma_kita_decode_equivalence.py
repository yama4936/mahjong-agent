"""Portable reference comparison for the friend-only image decode optimization.

The legacy function below is frozen from 61693d7; inputs are synthetic and
local anonymized crops, so no game or model is needed.
"""
import copy, io, json, unittest
from pathlib import Path
from typing import Any
from PIL import Image, ImageChops, ImageStat, ImageDraw
from auto_operator import (experimental_kita_glyph_stability, experimental_kita_wall_color_stable,
    closed_hand_face_mismatches, tile_face_structure_delta, crop_screenshot,
    experimental_kita_color_stable, experimental_kita_felt_lighting,
    experimental_kita_other_regions_stable)

def legacy_stability(before: bytes, after: bytes, report: dict[str, Any]) -> bool:
    """Lighting-tolerant visual hypothesis, only for the reviewed friend kita prompt.

    This does not prove state, turn, colors, or content concealed by overlays.
    """
    try:
        if not experimental_kita_wall_color_stable(before, after):
            return False
        hand = report['hand']; geometry = report['handGeometry']; row = report['buttonRow']
        hv = hand['value']; gv = geometry['value']; buttons = row['value']['slots']
        if (hand['status'] != 'candidate' or geometry['status'] != 'candidate' or row['status'] != 'candidate'
                or len(hv['tiles']) != 14 or 'N' not in hv['tiles'] or len(buttons) != 3
                or buttons[0].get('status') != 'empty_candidate'
                or buttons[1].get('status') != 'candidate' or buttons[1].get('action') != 'kita'
                or buttons[2].get('status') != 'candidate' or buttons[2].get('action') != 'skip'):
            return False
        layout = {'handSlots':gv['handSlots'],'drawSlot':gv['drawSlot']}
        if len(layout['handSlots']) != 13 or closed_hand_face_mismatches(before,after,layout,.5):
            return False
        boxes = [{'x':600,'y':785,'width':245,'height':90}, {'x':890,'y':785,'width':245,'height':90},
                 {'x':1180,'y':785,'width':245,'height':90}]
        if any(tile_face_structure_delta(crop_screenshot(before,box),crop_screenshot(after,box)) > .1 for box in boxes):
            return False
        with Image.open(io.BytesIO(before)) as a, Image.open(io.BytesIO(after)) as b:
            for box in boxes:
                x,y,w,h=(box[k] for k in ('x','y','width','height'))
                delta=ImageChops.difference(a.convert('RGB').crop((x,y,x+w,y+h)),b.convert('RGB').crop((x,y,x+w,y+h)))
                if max(ImageStat.Stat(delta).mean)>1:return False
        protected = layout['handSlots']+[layout['drawSlot']]+boxes+[
            {'x':845,'y':785,'width':45,'height':90}, {'x':1135,'y':785,'width':45,'height':90},
            {'x':740,'y':540,'width':420,'height':220},
            {'x':600,'y':240,'width':200,'height':360},
            {'x':1120,'y':240,'width':200,'height':360},
            {'x':800,'y':160,'width':320,'height':150}]
        if not experimental_kita_color_stable(before,after,protected):
            return False
        # Binary glyph masks can miss changes with the same luminance class.
        # Bound coherent RGB changes in the exposed gaps and own river.
        with Image.open(io.BytesIO(before)) as a, Image.open(io.BytesIO(after)) as b:
            a,b=a.convert('RGB'),b.convert('RGB')
            for index,box in enumerate(protected[-6:]):
                x,y,w,h=(box[k] for k in ('x','y','width','height'))
                delta=ImageChops.difference(a.convert('RGB').crop((x,y,x+w,y+h)),b.convert('RGB').crop((x,y,x+w,y+h)))
                for yy in range(0,h,16):
                    for xx in range(0,w,16):
                        # The opponent-side felt border has a small observed
                        # illumination shift in the saved positive pair.
                        value=max(ImageStat.Stat(delta.crop((xx,yy,min(xx+16,w),min(yy+16,h)))).mean)
                        limit=10 if index == 3 else 7 if index >= 4 else 6
                        if value > limit:
                            if not (index == 3 and xx < 64 and yy < 96 and value <= 12
                                    and experimental_kita_felt_lighting(a,b,x+xx,y+yy)):
                                return False
        if not experimental_kita_other_regions_stable(before,after,layout['handSlots']+[layout['drawSlot']]+boxes):
            return False
        center={'x':905,'y':375,'width':105,'height':90}
        return tile_face_structure_delta(crop_screenshot(before,center),crop_screenshot(after,center)) <= .5
    except (KeyError,TypeError,ValueError,OSError,IndexError):
        return False



class DecodeEquivalence(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.report=json.loads((Path(__file__).parent/'fixtures/sanma-c177-kita-report.json').read_text())
 @staticmethod
 def png(mode):
  image=Image.new('RGB',(1920,1080),(25,35,55))
  image= image.convert(mode)
  out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()
 def check(self, a,b,report):
  old=legacy_stability(a,b,report);new=experimental_kita_glyph_stability(a,b,report)
  self.assertEqual(new,old)
  return new
 def test_png_modes_and_cross_mode(self):
  frames={mode:self.png(mode) for mode in ('1','L','LA','P','RGB','RGBA')}
  for mode,frame in frames.items():
   with self.subTest(mode=mode):self.check(frame,frame,self.report)
  self.check(frames['RGB'],frames['RGBA'],self.report)
  image=Image.new('CMYK',(1920,1080));out=io.BytesIO();image.save(out,format='TIFF')
  self.assertFalse(self.check(out.getvalue(),out.getvalue(),self.report))
  image=Image.new('I',(1920,1080));out=io.BytesIO();image.save(out,format='TIFF')
  self.assertFalse(self.check(out.getvalue(),out.getvalue(),self.report))
 def test_invalid_bounds_remain_rejected(self):
  frame=self.png('RGB')
  for x in (-10,0,1860,1900,1920):
   report=copy.deepcopy(self.report);report['handGeometry']['value']['drawSlot']['x']=x
   with self.subTest(x=x):
    result=self.check(frame,frame,report)
    if x in (-10,1900,1920):self.assertFalse(result)
 def test_corrupt_and_truncated_images_fail_closed(self):
  frame=self.png('RGB')
  for a,b in ((b'',frame),(b'bad',frame),(frame[:1000],frame),(frame,frame[:1000])):
   with self.subTest(a=len(a),b=len(b)):self.assertFalse(self.check(a,b,self.report))
 def test_real_wall_motion_and_color_changes_fail_closed(self):
  root=Path(__file__).parent/'fixtures/sanma-wall-color'
  def frame(name,gray=False):
   crop=Image.open(root/name).convert('RGB')
   if gray:crop=crop.convert('L').convert('RGB')
   image=Image.new('RGB',(1920,1080),(25,35,55));image.paste(crop,(150,80));out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()
  before=frame('opponent-before.png');after=frame('opponent-after.png')
  self.assertFalse(self.check(before,after,self.report))
  original=frame('light-3.png');gray=frame('light-3.png',True)
  self.assertFalse(self.check(original,gray,self.report))
