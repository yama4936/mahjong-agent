"""Recorded second-row overlap and adverse changes, with no live browser."""
import tempfile,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from sanma_river_cell_diagnostic import compare
F=Path('/home/yama1/server/data/dev-work/jantama/evidence179/artifacts/frames')
@unittest.skipUnless(F.exists(),'retained evidence179 unavailable')
class RiverSecondRowTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.a=next(F.glob('*10-54-00.974*sanma-self-turn.png'))
  cls.b=next(F.glob('*10-54-25.091*sanma-self-turn.png'))
 def test_actual_overlap_candidate_only_when_explicit(self):
  self.assertFalse(compare(self.a,self.b)['singlePhysicalAppendCandidate'])
  result=compare(self.a,self.b,allow_second_row_overlap=True)
  self.assertTrue(result['secondRowOverlapCandidate']);self.assertTrue(result['singlePhysicalAppendCandidate']);self.assertEqual(result['emptyToTileIndices'],[6])
 def test_existing_tile_or_neighbour_changes_are_rejected(self):
  for box in ((770,545,826,599),(780,555,815,590),(835,545,880,590),(765,604,824,670),(830,614,885,680)):
   with self.subTest(box=box),tempfile.TemporaryDirectory() as td:
    im=Image.open(self.b).convert('RGB');ImageDraw.Draw(im).rectangle(box,fill=(0,0,0));target=Path(td)/'frame.png';im.save(target)
    result=compare(self.a,target,allow_second_row_overlap=True)
    self.assertFalse(result['singlePhysicalAppendCandidate'])
