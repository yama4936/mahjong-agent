import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw
from sanma_board_image import observe_sanma_image
from sanma_kita_image_experiment import detect_own_partial_north_candidate
from sanma_right_kita_experiment import right_north_candidate
ROOT=Path('/home/yama1/.codex/sanma-run-c177d5d-20261031')
FIXTURES=Path(__file__).parent/'fixtures'
OWN=FIXTURES/'sanma-own-north-partial-c177.png'
RIGHT=[FIXTURES/f'sanma-right-north-c177-{x}.png' for x in ('top','bottom')]
@unittest.skipUnless((ROOT/'manual-47-before.png').exists(),'saved friend images unavailable')
class C177NorthCandidates(unittest.TestCase):
 def test_own_occluded_and_unobserved(self):
  before=detect_own_partial_north_candidate(ROOT/'manual-42-before.png',OWN)
  after=detect_own_partial_north_candidate(ROOT/'manual-43-before.png',OWN)
  self.assertIsNone(before['candidate']);self.assertIsNotNone(after['candidate'])
  self.assertFalse(after['verified']);self.assertFalse(after['complete']);self.assertEqual(after['status'],'unknown')
 def test_right_two_positions_and_missing_are_unknown(self):
  before=right_north_candidate(ROOT/'manual-43-before.png',RIGHT)
  after=right_north_candidate(ROOT/'manual-47-before.png',RIGHT)
  self.assertEqual(before['candidates'],[]);self.assertEqual([x['slot'] for x in after['candidates']],[0,1])
  self.assertEqual(after['status'],'unknown');self.assertFalse(after['complete']);self.assertFalse(after['verified'])
 def test_covered_or_modified_glyph_not_counted(self):
  with tempfile.TemporaryDirectory() as d:
   for name,box,fn in [('own',(1390,765,1425,850),lambda p:detect_own_partial_north_candidate(p,OWN)),
                       ('right',(1410,214,1455,239),lambda p:right_north_candidate(p,RIGHT))]:
    image=Image.open(ROOT/('manual-43-before.png' if name=='own' else 'manual-47-before.png')).convert('RGB')
    ImageDraw.Draw(image).rectangle(box,fill='black');path=Path(d)/(name+'.png');image.save(path)
    result=fn(path)
    if name=='own':self.assertIsNone(result['candidate'])
    else:self.assertEqual([x['slot'] for x in result['candidates']],[1])
    self.assertFalse(result['complete'])
 def test_same_image_resident_observation_preserves_unknown(self):
  with patch('sanma_board_image.recognize_sanma_board_candidate',return_value={'verified':False}):
   observation=observe_sanma_image(ROOT/'manual-47-before.png')
  north=observation['north'];self.assertEqual(north['status'],'unknown');self.assertFalse(north['complete'])
  self.assertEqual([x['slot'] for x in north['positions']['right']['candidates']],[0,1])
  self.assertIn('partialObservation',north['positions']['own'])
  self.assertEqual(len({north['positions']['right']['frame_sha256'],north['positions']['own']['frame_sha256'],north['positions']['own']['partialObservation']['frame_sha256']}),1)
 def test_bad_input_never_becomes_zero(self):
  missing=ROOT/'does-not-exist.png'
  self.assertEqual(detect_own_partial_north_candidate(missing,OWN)['status'],'unknown')
  self.assertEqual(right_north_candidate(missing,RIGHT)['status'],'unknown')
  self.assertNotIn('candidates',right_north_candidate(missing,RIGHT))
 def test_separate_friend_game(self):
  other=Path('/home/yama1/.codex/sanma-run-41b9fb3-20261031')
  if not (other/'manual-21-before.png').exists():self.skipTest('independent game unavailable')
  image=other/'manual-21-before.png'
  self.assertIsNotNone(detect_own_partial_north_candidate(image,OWN)['candidate'])
  self.assertEqual([x['slot'] for x in right_north_candidate(image,RIGHT)['candidates']],[0,1])
  empty=other/'manual-01-before.png'
  self.assertIsNone(detect_own_partial_north_candidate(empty,OWN)['candidate'])
  self.assertEqual(right_north_candidate(empty,RIGHT)['candidates'],[])

@unittest.skipUnless((ROOT/'manual-47-before.png').exists() and Path('templates/bootstrap/1m__hf_base.png').exists(),'saved image or model unavailable')
class ResidentC177NorthCandidates(unittest.TestCase):
 def test_real_resident_never_promotes_candidates_to_counts(self):
  import json,subprocess
  from unittest.mock import Mock
  from auto_operator import PythonAutoOperator
  child=subprocess.Popen(['node','--import','tsx','src/recognition/recognitionServer.ts','config/layout-runtime.json','templates/bootstrap','examples/public-unknown.json'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8')
  try:
   self.assertTrue(json.loads(child.stdout.readline())['ready'])
   with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent) as d:
    op=object.__new__(PythonAutoOperator);op.frames=Path(d);op.recognition_request_id=0;op.recognition_server=child;op.log=Mock();page=Mock()
    for n in (43,47):
     page.screenshot.return_value=(ROOT/f'manual-{n:02}-before.png').read_bytes()
     receipt=op.inspect_sanma_self_turn(page);north=receipt['sourceObservation']['north']
     self.assertEqual(north['status'],'unknown');self.assertFalse(north['complete']);self.assertFalse(north['verified'])
     if n==43:self.assertIsNotNone(north['positions']['own']['partialObservation']['candidate'])
     else:self.assertEqual([v['slot'] for v in north['positions']['right']['candidates']],[0,1])
     self.assertFalse(receipt['operationAuthorized']);page.mouse.click.assert_not_called()
  finally:
   child.kill();child.wait();child.stdin.close();child.stdout.close()
