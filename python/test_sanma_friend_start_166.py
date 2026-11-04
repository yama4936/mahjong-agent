"""Replay reviewed 300+0 room captures; no browser or click is used."""
import glob,io,unittest
from pathlib import Path
from unittest.mock import Mock
from PIL import Image,ImageDraw
from friend_start import verified_friend_room,await_reviewed_friend_room

F=Path('/home/yama1/server/data/dev-work/jantama/evidence166')
@unittest.skipUnless((F/'room.png').exists(),'retained room evidence unavailable')
class FriendStart166(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.first=(F/'room.png').read_bytes()
  cls.second=next((F/'artifacts/frames').glob('*friend-start-32.png')).read_bytes()
  captures=sorted((F/'artifacts2/frames').glob('*friend-start-*.png'))
  cls.later=[captures[-2].read_bytes(),captures[-1].read_bytes()]
 def test_actual_reviewed_petal_pairs_and_two_captures(self):
  for before in (self.first,self.second):
   for frame in self.later:self.assertTrue(verified_friend_room(frame,before,sanma=True))
   page=Mock();page.screenshot.side_effect=self.later
   self.assertEqual(await_reviewed_friend_room(page,before,attempts=2,sanma=True),2);page.mouse.click.assert_not_called()
 def test_score_cpu_room_and_rules_remain_bound(self):
  before=self.later[-1]
  for name,box in [('start_score',(1710,358,1720,375)),('required_score',(1710,433,1720,451)),
                   ('time',(1710,263,1730,284)),('other_rule',(1710,581,1720,602)),
                   ('cpu_one',(560,850,620,875)),('cpu_two',(950,850,1010,875)),('room_id',(978,75,990,102))]:
   im=Image.open(io.BytesIO(before)).convert('RGB');ImageDraw.Draw(im).rectangle(box,fill='black');out=io.BytesIO();im.save(out,format='PNG')
   with self.subTest(name=name):self.assertFalse(verified_friend_room(out.getvalue(),before,sanma=True))
 def test_yonma_never_gets_sanma_exception(self):
  self.assertFalse(verified_friend_room(self.later[-1],self.first,sanma=False))
