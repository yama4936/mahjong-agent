"""Offline portable old/new comparison; no browser, model or private path."""
import copy,io,json,unittest
from pathlib import Path
from typing import Any
from PIL import Image,ImageChops,ImageStat
from auto_operator import (experimental_draw_glyph_stability, closed_hand_face_mismatches,
    tile_face_structure_delta,crop_screenshot,experimental_kita_color_stable)

def legacy_draw_stability(before: bytes, after: bytes, report: dict[str, Any]) -> bool:
    """Friend-only lighting hypothesis; does not establish turn or legal actions."""
    try:
        hand, geometry, row = (report[k] for k in ('hand', 'handGeometry', 'buttonRow'))
        value, shape = hand['value'], geometry['value']
        slots = row['value']['slots']
        if (any(x['status'] != 'candidate' for x in (hand, geometry, row))
                or value.get('turnReady') is not True or len(value['tiles']) != 14
                or len(slots) != 3):
            return False
        if any(x.get('status') != 'empty_candidate' for x in slots):
            # The concealed action is still unknown; only accept a previously
            # reviewed partial-row candidate for both independent captures.
            from sanma_friend_discard_experiment import friend_visible_row_with_north_overlap, friend_visible_empty_row_candidate
            partial = lambda frame: (friend_visible_row_with_north_overlap(frame, slots)
                                     or friend_visible_empty_row_candidate(frame, slots))
            if not partial(before) or not partial(after): return False
        layout = {'handSlots': shape['handSlots'], 'drawSlot': shape['drawSlot']}
        if len(layout['handSlots']) != 13 or closed_hand_face_mismatches(before, after, layout, .5):
            return False
        boxes = [{'x':600,'y':785,'width':245,'height':90}, {'x':890,'y':785,'width':245,'height':90},
                 {'x':1180,'y':785,'width':245,'height':90}]
        if any(tile_face_structure_delta(crop_screenshot(before,b), crop_screenshot(after,b)) > .1 for b in boxes):
            return False
        if not experimental_kita_color_stable(before, after, layout['handSlots']+[layout['drawSlot']]+boxes):
            return False
        with Image.open(io.BytesIO(before)) as a, Image.open(io.BytesIO(after)) as b:
            if a.size != (1920,1080) or b.size != a.size: return False
            for box in boxes:
                x,y,w,h = (box[k] for k in ('x','y','width','height'))
                delta = ImageChops.difference(a.convert('RGB').crop((x,y,x+w,y+h)), b.convert('RGB').crop((x,y,x+w,y+h)))
                if max(ImageStat.Stat(delta).mean) > 1: return False
            diff = ImageChops.difference(*(im.convert('L').point(lambda v: 255 if v < 120 else 0) for im in (a,b)))
            # The illuminated self-turn indicator flickers independently of the board.
            for rect in ((1425,755,1650,870),(920,510,992,516)):
                diff.paste(0, rect)
            # Mask only actual hand and action rectangles already compared.
            # Gaps between buttons and beside the hand remain observable.
            for box in layout['handSlots'] + [layout['drawSlot']] + boxes:
                x,y,w,h=(int(box[k]) for k in ('x','y','width','height'))
                if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > 1920 or y+h > 1080:return False
                diff.paste(0,(x,y,x+w,y+h))
            for y in range(0,1080,32):
                for x in range(0,1920,32):
                    if diff.crop((x,y,min(x+32,1920),min(y+32,1080))).histogram()[255] > 14: return False
        center={'x':905,'y':375,'width':105,'height':90}
        return tile_face_structure_delta(crop_screenshot(before,center),crop_screenshot(after,center)) <= .5
    except (KeyError,TypeError,ValueError,OSError,IndexError):
        return False



class DrawDecodeEquivalence(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.report=json.loads((Path(__file__).parent/'fixtures/sanma-c177-kita-report.json').read_text())
  cls.report['buttonRow']['value']['slots']=[{'status':'empty_candidate','slot':i} for i in range(3)]
  cls.report['hand']['value']['turnReady']=True
 @staticmethod
 def image(mode):
  im=Image.new('RGB',(1920,1080),(25,35,55)).convert(mode);out=io.BytesIO();im.save(out,format='PNG');return out.getvalue()
 def check(self,a,b,report):
  old=legacy_draw_stability(a,b,report);new=experimental_draw_glyph_stability(a,b,report)
  self.assertEqual(new,old);return new
 def test_full_images_decoded_once_per_comparison(self):
  from unittest.mock import patch
  image=self.image('RGB');original=Image.open;opened=[]
  def tracked(*args,**kwargs):
   result=original(*args,**kwargs)
   if result.size==(1920,1080):opened.append(result)
   return result
  with patch('auto_operator.Image.open',side_effect=tracked):
   experimental_draw_glyph_stability(image,image,self.report)
  self.assertEqual(len(opened),2)
 def test_image_modes_and_unsupported_types(self):
  for mode in ('1','L','LA','P','RGB','RGBA'):
   with self.subTest(mode=mode):
    a=self.image(mode);self.check(a,a,self.report)
  for mode in ('CMYK','I'):
   image=Image.new(mode,(1920,1080));out=io.BytesIO();image.save(out,format='TIFF')
   self.assertFalse(self.check(out.getvalue(),out.getvalue(),self.report))
 def test_corrupt_and_truncated_fail_closed(self):
  a=self.image('RGB')
  for first,second in ((b'',a),(b'broken',a),(a[:1000],a),(a,a[:1000])):
   self.assertFalse(self.check(first,second,self.report))
 def test_slot_coordinate_boundaries(self):
  a=self.image('RGB')
  for x in (-10,0,1860,1900,1920):
   report=copy.deepcopy(self.report);report['handGeometry']['value']['drawSlot']['x']=x
   result=self.check(a,a,report)
   if x in (-10,1900,1920):self.assertFalse(result)
 def test_real_wall_motion_and_color_only_change(self):
  root=Path(__file__).parent/'fixtures/sanma-wall-color'
  def frame(name,gray=False):
   crop=Image.open(root/name).convert('RGB')
   if gray:crop=crop.convert('L').convert('RGB')
   im=Image.new('RGB',(1920,1080),(25,35,55));im.paste(crop,(150,80));out=io.BytesIO();im.save(out,format='PNG');return out.getvalue()
  self.check(frame('opponent-before.png'),frame('opponent-after.png'),self.report)
  self.check(frame('light-3.png'),frame('light-3.png',True),self.report)
