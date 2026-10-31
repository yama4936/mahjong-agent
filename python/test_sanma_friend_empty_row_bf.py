import io,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from sanma_friend_discard_experiment import friend_visible_empty_row_candidate

ROOT=Path('/home/yama1/.codex/sanma-run-bf336af-20261031')
SLOTS=[{'status':'empty_candidate'},{'status':'empty_candidate'},{'status':'unresolved'}]
@unittest.skipUnless((ROOT/'manual-24-before.png').exists(),'saved friend image missing')
class EmptyFriendRowTests(unittest.TestCase):
 def test_observed_empty_slot_is_a_candidate(self):
  self.assertTrue(friend_visible_empty_row_candidate((ROOT/'manual-24-before.png').read_bytes(),SLOTS))
 def test_actual_skip_and_visible_modifications_are_rejected(self):
  for name in ('manual-19-before.png','manual-21-before.png'):
   if (ROOT/name).exists():self.assertFalse(friend_visible_empty_row_candidate((ROOT/name).read_bytes(),SLOTS))
  frame=(ROOT/'manual-24-before.png').read_bytes()
  for box in ((1180,785,1200,800),(1300,820,1340,850),(1405,785,1424,800)):
   image=Image.open(io.BytesIO(frame)).convert('RGB');ImageDraw.Draw(image).rectangle(box,fill=(220,20,20));out=io.BytesIO();image.save(out,format='PNG')
   with self.subTest(box=box):self.assertFalse(friend_visible_empty_row_candidate(out.getvalue(),SLOTS))
 def test_coherent_subthreshold_visible_change_is_rejected(self):
  frame=(ROOT/'manual-24-before.png').read_bytes();image=Image.open(io.BytesIO(frame)).convert('RGB')
  for y in range(817,833):
   for x in range(1372,1388):
    color=image.getpixel((x,y)); image.putpixel((x,y),tuple(min(255,c+20) for c in color))
  out=io.BytesIO();image.save(out,format='PNG')
  self.assertFalse(friend_visible_empty_row_candidate(out.getvalue(),SLOTS))
 def test_clock_area_change_is_unobserved(self):
  frame=(ROOT/'manual-24-before.png').read_bytes();image=Image.open(io.BytesIO(frame)).convert('RGB')
  ImageDraw.Draw(image).rectangle((1430,785,1500,850),fill=(220,20,20))
  out=io.BytesIO();image.save(out,format='PNG')
  self.assertTrue(friend_visible_empty_row_candidate(out.getvalue(),SLOTS))
 def test_independent_known_minor_lighting_variation(self):
  path=ROOT/'manual-42-before.png'
  if not path.exists():self.skipTest('additional image unavailable')
  self.assertTrue(friend_visible_empty_row_candidate(path.read_bytes(),SLOTS))

 def test_ambiguous_first_slot_is_rejected(self):
  self.assertFalse(friend_visible_empty_row_candidate((ROOT/'manual-24-before.png').read_bytes(),[{'status':'unresolved'},*SLOTS[1:]]))
