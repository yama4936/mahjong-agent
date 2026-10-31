import copy
import io
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image,ImageDraw
from auto_operator import load_json
from sanma_friend_riichi_experiment import unique_riichi_selection,execute_friend_riichi
ROOT=Path('/home/yama1/.codex/sanma-run-dd7175d-20261031')
@unittest.skipUnless((ROOT/'manual-62-before.png').exists(),'friend riichi images unavailable')
class RiichiExperimentTests(unittest.TestCase):
 def setUp(self):
  self.layout=load_json(Path('config/layout-runtime.json'));self.selection=(ROOT/'manual-62-before.png').read_bytes()
 def test_real_unique_selection_and_ordinary_hand(self):
  self.assertEqual(unique_riichi_selection(self.selection,self.layout),7)
  self.assertIsNone(unique_riichi_selection((ROOT/'manual-61-before.png').read_bytes(),self.layout))
 def test_multiple_or_unknown_slots_rejected(self):
  image=Image.open(io.BytesIO(self.selection)).convert('RGB');image.paste(image.crop((887,921,979,1072)),(792,921));out=io.BytesIO();image.save(out,format='PNG')
  self.assertIsNone(unique_riichi_selection(out.getvalue(),self.layout))
  image=Image.open(io.BytesIO(self.selection)).convert('RGB');ImageDraw.Draw(image).rectangle((792,930,884,1030),fill=(0,0,0));out=io.BytesIO();image.save(out,format='PNG')
  self.assertIsNone(unique_riichi_selection(out.getvalue(),self.layout))
 def test_click_geometry_must_match_selected_tile(self):
  for case in ('other_tile','outside','not_finite','viewport','overlap'):
   layout=copy.deepcopy(self.layout)
   if case=='other_tile':layout['clickPoints'][7]=dict(layout['clickPoints'][6])
   if case=='outside':layout['clickPoints'][7]['x']=1900
   if case=='not_finite':layout['clickPoints'][7]['y']=float('nan')
   if case=='viewport':layout['viewport']['width']=1280
   if case=='overlap':layout['handSlots'][7]['x']=layout['handSlots'][6]['x']
   with self.subTest(case=case):self.assertIsNone(unique_riichi_selection(self.selection,layout))

 def test_mocked_button_and_discard_selection(self):
  with tempfile.TemporaryDirectory() as d:
   op=Mock();op.layout=self.layout;op.frames=Path(d);op.verified_friend_300_active=True;op.sanma_friend_action_observed_at=time.monotonic()
   page=Mock();page.screenshot.return_value=self.selection
   with patch('sanma_friend_riichi_experiment.execute_friend_pon_pass') as declare,patch('sanma_friend_riichi_experiment.send_discard_click',return_value={}) as discard:
    result=execute_friend_riichi(op,page,{})
    self.assertEqual(result['confirmation'],'unknown');self.assertTrue(declare.call_args.kwargs['declare_riichi'])
    self.assertEqual(discard.call_args.args[7],7)
 def test_changed_selection_never_discards(self):
  with tempfile.TemporaryDirectory() as d:
   op=Mock();op.layout=self.layout;op.frames=Path(d);op.verified_friend_300_active=True;op.sanma_friend_action_observed_at=time.monotonic()
   page=Mock();page.screenshot.side_effect=[self.selection,(ROOT/'manual-61-before.png').read_bytes()]
   with patch('sanma_friend_riichi_experiment.execute_friend_pon_pass'),patch('sanma_friend_riichi_experiment.send_discard_click') as discard:
    with self.assertRaisesRegex(RuntimeError,'changed before discard'):execute_friend_riichi(op,page,{})
    discard.assert_not_called()
 def test_real_resident_receipt_through_button_and_unique_discard(self):
  import json
  from screen_state import load_references
  before=(ROOT/'manual-61-before.png').read_bytes();receipt=json.loads((Path(__file__).parent/'fixtures/sanma-dd-riichi61-receipt.json').read_text())
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'before.png';path.write_bytes(before);receipt['screenshot']=str(path)
   op=Mock();op.layout=self.layout;op.frames=Path(d);op.verified_friend_300_active=True;op.sanma_friend_action_observed_at=time.monotonic()
   op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
   op.screen_references=load_references(Path('/home/yama1/projects/jantama-auto/artifacts/live'))
   page=Mock();page.screenshot.side_effect=[before,self.selection,self.selection]
   with patch('sanma_friend_riichi_experiment.send_discard_click',return_value={}) as discard:
    result=execute_friend_riichi(op,page,receipt)
    page.mouse.click.assert_called_once_with(1010,830)
    self.assertEqual(discard.call_args.args[7],7);self.assertEqual(result['confirmation'],'unknown')
   page=Mock();page.screenshot.return_value=before;op.args.ranked_loop=True
   with patch('sanma_friend_riichi_experiment.send_discard_click') as discard:
    with self.assertRaisesRegex(RuntimeError,'friend session'):execute_friend_riichi(op,page,receipt)
    discard.assert_not_called();page.mouse.click.assert_not_called()
