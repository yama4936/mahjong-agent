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
 def test_reject_buttons_even_if_first_slots_are_falsely_reported_empty(self):
  for name in ('ron','tsumo','riichi','skip'):
   image=Image.open(io.BytesIO(self.frame)).convert('RGB')
   if name=='ron':
    button=Image.open('test/fixtures/ron-button-rows/ron2.png').convert('RGB').crop((290,0,535,90))
   elif name=='skip':
    button=Image.open('test/fixtures/sanma-button-rows/kita.png').convert('RGB').crop((580,0,825,90))
   else:
    button=Image.open(f'test/fixtures/sanma-buttons/{name}.png').convert('RGB').resize((245,90))
   for position in ((600,785),(890,785)):
    modified=image.copy();modified.paste(button,position);out=io.BytesIO();modified.save(out,format='PNG')
    with self.subTest(name=name,position=position):
     self.assertFalse(friend_visible_empty_row_candidate(out.getvalue(),SLOTS))
 def test_low_contrast_mark_in_first_slot_is_rejected(self):
  image=Image.open(io.BytesIO(self.frame)).convert('RGB')
  for y in range(801,817):
   for x in range(616,632):
    image.putpixel((x,y),tuple(min(255,c+20) for c in image.getpixel((x,y))))
  out=io.BytesIO();image.save(out,format='PNG')
  self.assertFalse(friend_visible_empty_row_candidate(out.getvalue(),SLOTS))

 def test_visible_marks_at_edges_and_low_contrast_are_rejected(self):
  for box,color in [((1180,785,1195,800),(240,0,0)),((1315,850,1325,860),(240,0,0)),((1415,852,1424,864),(240,0,0)),((1280,810,1300,830),(30,30,30))]:
   image=Image.open(io.BytesIO(self.frame)).convert('RGB');ImageDraw.Draw(image).rectangle(box,fill=color);out=io.BytesIO();image.save(out,format='PNG')
   with self.subTest(box=box):self.assertFalse(friend_visible_empty_row_candidate(out.getvalue(),SLOTS))
