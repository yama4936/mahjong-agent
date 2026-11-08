import io,json,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from PIL import Image, ImageEnhance, ImageDraw
from sanma_five_pin_candidate import red_five_pin_face_candidate
from sanma_friend_discard_recovery import candidate
ROOT=Path('/home/yama1/server/data/dev-work/jantama/evidence181/retry-artifacts')
TEMPLATES=Path('/home/yama1/projects/jantama-auto/templates/live-verified')
FIXTURE=Path(__file__).parent/'fixtures/sanma-red5pin-181.png'
class RedFivePinTests(unittest.TestCase):
 slot={'x':1486,'y':921,'width':92,'height':151}
 def frame(self,tile):
  frame=Image.new('RGB',(1920,1080),'white');frame.paste(tile.convert('RGB').resize((92,151)),(1486,921));out=io.BytesIO();frame.save(out,format='PNG');return out.getvalue()
 def test_portable_positive_and_blank_faded_covered_negative(self):
  tile=Image.open(FIXTURE).convert('RGB');self.assertTrue(red_five_pin_face_candidate(self.frame(tile),self.slot))
  for value in (0,.1,.3,.6):self.assertFalse(red_five_pin_face_candidate(self.frame(ImageEnhance.Color(tile).enhance(value)),self.slot))
  self.assertFalse(red_five_pin_face_candidate(self.frame(Image.new('RGB',(93,151),'white')),self.slot))
  covered=tile.copy();ImageDraw.Draw(covered).rectangle((0,0,46,151),fill='white');self.assertFalse(red_five_pin_face_candidate(self.frame(covered),self.slot))
 @unittest.skipUnless(TEMPLATES.exists(),'local templates unavailable')
 def test_all_other_available_tile_templates_rejected(self):
  for path in TEMPLATES.glob('*.png'):
   if path.name.startswith('0p__'):continue
   with self.subTest(name=path.name),Image.open(path) as tile:self.assertFalse(red_five_pin_face_candidate(self.frame(tile),self.slot))
 def test_retained_real_red_sou_and_normal_pin_are_rejected(self):
  with Image.open(Path(__file__).parent/'fixtures/sanma-five-sou-review/0s.png') as tile:
   self.assertFalse(red_five_pin_face_candidate(self.frame(tile),self.slot))
  folder=Path('/home/yama1/server/data/dev-work/jantama/evidence179/artifacts/frames')
  if not folder.exists():self.skipTest('normal 5p evidence unavailable')
  receipt=json.loads(next(folder.glob('*10-52-29.684*receipt.json')).read_text())
  geometry=receipt['sourceObservation']['report']['handGeometry']['value'];slot=geometry['drawSlot'];data=Path(receipt['screenshot']).read_bytes()
  self.assertFalse(red_five_pin_face_candidate(data,slot))
 def test_independent_real_red_pin(self):
  folder=Path('/home/yama1/server/data/dev-work/jantama/evidence148/artifacts2/frames')
  if not folder.exists():self.skipTest('independent red 5p evidence unavailable')
  receipt=json.loads(next(folder.glob('*16-22-31*.sanma-self-turn.receipt.json')).read_text());report=receipt['sourceObservation']['report'];index=report['hand']['value']['tiles'].index('0p');geometry=report['handGeometry']['value'];slot=([*geometry['handSlots'],geometry['drawSlot']])[index]
  self.assertTrue(red_five_pin_face_candidate(Path(receipt['screenshot']).read_bytes(),slot))
 @unittest.skipUnless(ROOT.exists(),'181 evidence unavailable')
 def test_recorded_recovery_candidate_and_unconfirmed_state(self):
  p=ROOT/'frames';paths=[next(p.glob('*'+prefix+'*receipt.json')) for prefix in ('12-03-34.348','12-03-48.517','12-03-53.386')];receipts=[json.loads(x.read_text()) for x in paths]
  events=map(json.loads,(ROOT/'python-operator.jsonl').read_text().splitlines());journal=[e for e in events if e['event']=='sanma_friend_discard_experiment' and e.get('frameSha256','').startswith('022a')]
  watch=Mock();watch.alive.return_value=True
  self.assertTrue(candidate(receipts[0],receipts[1:],journal,continuity=watch,active=lambda:True,started=100,deadline_ms=300000,now=lambda:101))
  with patch('sanma_five_pin_candidate.red_five_pin_face_candidate',return_value=False):
   self.assertFalse(candidate(receipts[0],receipts[1:],journal,continuity=watch,active=lambda:True,started=100,deadline_ms=300000,now=lambda:101))
