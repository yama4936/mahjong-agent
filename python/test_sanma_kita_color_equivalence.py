"""Compare color guard with the pre-optimization scalar predicate."""
import builtins
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import numpy as np
from auto_operator import experimental_kita_color_stable, _kita_color_labels


def legacy(before,after,boxes):
 def kind(p):
  r,g,b=p
  return 1 if r-g>35 and r-b>35 else 2 if g-r>20 and g-b>15 else 0
 def open_frame(frame):
  return frame.copy() if isinstance(frame,Image.Image) else Image.open(io.BytesIO(frame))
 with open_frame(before) as a,open_frame(after) as b:
  a,b=a.convert('RGB'),b.convert('RGB')
  if a.size!=(1920,1080) or b.size!=a.size:return False
  for box in boxes:
   x,y,w,h=(int(box[k]) for k in ('x','y','width','height'))
   if x<0 or y<0 or w<=0 or h<=0 or x+w>1920 or y+h>1080:return False
   first=list(a.crop((x,y,x+w,y+h)).getdata());second=list(b.crop((x,y,x+w,y+h)).getdata())
   if sum(kind(p)!=kind(q) for p,q in zip(first,second))>max(2,len(first)*.001):return False
  return True

class KitaColorEquivalenceTest(unittest.TestCase):
 def test_exhaustive_all_rgb_classes_including_threshold_boundaries(self):
  # 256^3 classes; the scalar predicate is an independent copy of the old code.
  green,blue=np.indices((256,256),dtype=np.uint8)
  for red in range(256):
   pixels=np.stack((np.full((256,256),red,dtype=np.uint8),green,blue),axis=2)
   actual=_kita_color_labels(Image.fromarray(pixels),np).ravel()
   expected=np.fromiter((1 if int(r)-int(g)>35 and int(r)-int(b)>35 else 2 if int(g)-int(r)>20 and int(g)-int(b)>15 else 0 for r,g,b in pixels.reshape(-1,3)),dtype=np.int8,count=65536)
   self.assertTrue(np.array_equal(actual,expected),f'red={red}')
 def test_real_full_frames_all_pixels_and_saved_rejections(self):
  path=Path('/home/yama1/.codex/sanma-d55a036-20261102/retry/python-operator.jsonl')
  if not path.exists():self.skipTest('saved real regression unavailable')
  pairs=[json.loads(line) for line in path.read_text().splitlines() if 'sanma_friend_kita_preclick_rejected' in line]
  self.assertEqual(len(pairs),3)
  for event in pairs:
   a,b=(Path(event[key]).read_bytes() for key in ('baseline','screenshot'))
   for data in (a,b):
    with Image.open(io.BytesIO(data)) as image:
     image=image.convert('RGB');actual=_kita_color_labels(image,np).ravel()
     expected=np.fromiter((1 if r-g>35 and r-b>35 else 2 if g-r>20 and g-b>15 else 0 for r,g,b in image.getdata()),dtype=np.int8,count=1920*1080)
     self.assertTrue(np.array_equal(actual,expected))
   receipt=json.loads(Path(event['baseline']).with_suffix('.receipt.json').read_text());g=receipt['sourceObservation']['report']['handGeometry']['value']
   boxes=g['handSlots']+[g['drawSlot'],{'x':600,'y':785,'width':245,'height':90},{'x':890,'y':785,'width':245,'height':90},{'x':1180,'y':785,'width':245,'height':90},
     {'x':845,'y':785,'width':45,'height':90},{'x':1135,'y':785,'width':45,'height':90},
     {'x':740,'y':540,'width':420,'height':220},{'x':600,'y':240,'width':200,'height':360},
     {'x':1120,'y':240,'width':200,'height':360},{'x':800,'y':160,'width':320,'height':150}]
   self.assertEqual(experimental_kita_color_stable(a,b,boxes),legacy(a,b,boxes))
 def test_modes_and_count_threshold_edges(self):
  for mode in ('RGB','RGBA','L','P'):
   for w,h in ((20,100),(30,100),(31,100)):
    base=Image.new('RGB',(1920,1080),(100,100,100));box={'x':0,'y':0,'width':w,'height':h}
    for changes in (2,3,4):
     altered=base.copy()
     for x in range(changes):altered.putpixel((x,0),(255,0,0))
     a,b=base.convert(mode),altered.convert(mode)
     with self.subTest(mode=mode,area=w*h,changes=changes):self.assertEqual(experimental_kita_color_stable(a,b,[box]),legacy(a,b,[box]))
 def test_no_numpy_uses_old_predicate_and_runtime_errors_fail_closed(self):
  a=Image.new('RGB',(1920,1080),(100,100,100));b=a.copy();box={'x':0,'y':0,'width':20,'height':100}
  for x in range(3):b.putpixel((x,0),(255,0,0))
  original=builtins.__import__
  def missing(name,*args,**kwargs):
   if name=='numpy':raise ImportError('simulated absence')
   return original(name,*args,**kwargs)
  with patch('builtins.__import__',side_effect=missing):self.assertEqual(experimental_kita_color_stable(a,b,[box]),legacy(a,b,[box]))
  with patch('auto_operator._kita_color_labels',side_effect=RuntimeError('array failure')):self.assertFalse(experimental_kita_color_stable(a,a,[box]))
 def test_invalid_geometry_and_wrong_dimensions_match_old_result(self):
  image=Image.new('RGB',(1920,1080));small=Image.new('RGB',(100,100))
  for a,b,boxes in ((small,small,[]),(image,small,[]),(image,image,[{'x':-1,'y':0,'width':2,'height':2}]),(image,image,[{'x':1919,'y':0,'width':2,'height':2}])):
   self.assertEqual(experimental_kita_color_stable(a,b,boxes),legacy(a,b,boxes))
