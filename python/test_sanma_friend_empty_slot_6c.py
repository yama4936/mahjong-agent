import io,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from sanma_friend_discard_experiment import friend_visible_empty_row_candidate
ROOT=Path('/home/yama1/.codex/sanma-run-6c090e6-20261031')
SLOTS=[{'status':'empty_candidate'},{'status':'empty_candidate'},{'status':'unresolved'}]
@unittest.skipUnless((ROOT/'manual-13-before.png').exists(),'saved friend frame unavailable')
class EmptyRow6cTests(unittest.TestCase):
 def setUp(self):self.frame=(ROOT/'manual-13-before.png').read_bytes()
 def test_actual_empty_candidate(self):self.assertTrue(friend_visible_empty_row_candidate(self.frame,SLOTS))
 def test_actual_prompt_and_uncertain_other_slot_rejected(self):
  prompt=Path('/home/yama1/.codex/sanma-run-dd7175d-20261031/manual-18-before.png')
  if prompt.exists():self.assertFalse(friend_visible_empty_row_candidate(prompt.read_bytes(),SLOTS))
  self.assertFalse(friend_visible_empty_row_candidate(self.frame,[{'status':'unresolved'},*SLOTS[1:]]))
 def test_visible_marks_at_edges_and_low_contrast_are_rejected(self):
  for box,color in [((1180,785,1195,800),(240,0,0)),((1315,850,1325,860),(240,0,0)),((1415,852,1424,864),(240,0,0)),((1280,810,1300,830),(30,30,30))]:
   image=Image.open(io.BytesIO(self.frame)).convert('RGB');ImageDraw.Draw(image).rectangle(box,fill=color);out=io.BytesIO();image.save(out,format='PNG')
   with self.subTest(box=box):self.assertFalse(friend_visible_empty_row_candidate(out.getvalue(),SLOTS))
