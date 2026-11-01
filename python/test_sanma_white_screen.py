import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw
from auto_operator import PythonAutoOperator
from screen_state import classify_screen, is_blank_white_client_frame


def png(image):
 out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()

def white_frame():
 im=Image.new('RGB',(1920,1080),'white');ImageDraw.Draw(im).rectangle((10,10,19,19),fill=(90,90,90));return png(im)

class WhiteScreenTests(unittest.TestCase):
 def test_white_error_signature_is_unknown_and_real_white_frames_detect(self):
  image=white_frame();self.assertTrue(is_blank_white_client_frame(image));self.assertEqual(classify_screen(image,{})[0],'unknown')
  frame=Path('/home/yama1/.codex/sanma-reduced-608612a-20261102/manual-50-fresh.png')
  if frame.exists():self.assertTrue(is_blank_white_client_frame(frame))
 def test_normal_result_and_unreviewed_image_do_not_get_blank_signature(self):
  for path in (Path('test/fixtures/sanma-result/positive-redacted.png'),Path('test/fixtures/self-win-away-overlay-20261030.png')):
   self.assertFalse(is_blank_white_client_frame(path))
  self.assertFalse(is_blank_white_client_frame(b'not a frame'))
  self.assertFalse(is_blank_white_client_frame(png(Image.new('RGB',(1920,1080),'black'))))
 def test_unknown_white_stops_and_preserves_evidence_without_input_or_reload(self):
  with tempfile.TemporaryDirectory() as d:
   op=object.__new__(PythonAutoOperator);op.frames=Path(d);op.log=Mock();op.screen_references={};op.verified_friend_300_active=True
   op.args=SimpleNamespace(rules='sanma',mode='force-auto',experimental_sanma_friend=True,action_deadline_ms=300000,ranked_loop=False,start_reviewed_friend_room='reviewed',max_iterations=2)
   page=Mock();page.screenshot.return_value=white_frame()
   op.run_experimental_sanma_friend(page)
   event=next(c for c in op.log.call_args_list if c.kwargs.get('reason')=='white_screen_unobservable')
   self.assertEqual(Path(event.kwargs['screenshot']).read_bytes(),page.screenshot.return_value)
   self.assertEqual(event.kwargs['digest'],hashlib.sha256(page.screenshot.return_value).hexdigest())
   self.assertEqual(event.kwargs['recovery'],'manual_review_required');self.assertFalse(event.kwargs['operationAuthorized'])
   page.mouse.click.assert_not_called();page.reload.assert_not_called();page.goto.assert_not_called()
 def test_white_frame_stops_even_if_another_classifier_mistakes_it_for_a_match(self):
  with tempfile.TemporaryDirectory() as d:
   op=object.__new__(PythonAutoOperator);op.frames=Path(d);op.log=Mock();op.screen_references={};op.verified_friend_300_active=True
   op.args=SimpleNamespace(rules='sanma',mode='force-auto',experimental_sanma_friend=True,action_deadline_ms=300000,ranked_loop=False,start_reviewed_friend_room='reviewed',max_iterations=2)
   op.inspect_sanma_self_turn=Mock();page=Mock();page.screenshot.return_value=white_frame()
   with patch('auto_operator.classify_screen',return_value=('match',1.0)):op.run_experimental_sanma_friend(page)
   op.inspect_sanma_self_turn.assert_not_called();page.mouse.click.assert_not_called();page.reload.assert_not_called()
   self.assertTrue(any(c.kwargs.get('reason')=='white_screen_unobservable' for c in op.log.call_args_list))
 def test_prior_unconfirmed_action_is_latched_without_input_or_reload(self):
  with tempfile.TemporaryDirectory() as d:
   op=object.__new__(PythonAutoOperator);op.frames=Path(d);op.log=Mock();op.screen_references={};op.verified_friend_300_active=True
   op.args=SimpleNamespace(rules='sanma',mode='force-auto',experimental_sanma_friend=True,action_deadline_ms=300000,ranked_loop=False,start_reviewed_friend_room='reviewed',max_iterations=3)
   page=Mock();page.screenshot.side_effect=[b'match frame',white_frame()]
   receipt={'candidates':{'candidates':[{'action':'tsumo'}]},'digest':'first','screenshot':'unused','freshness':{'status':'identical_pixels_candidate'}}
   op.inspect_sanma_self_turn=Mock(return_value=receipt);op.execute_sanma_friend_tsumo_candidate=Mock(return_value={'clicked':True});op.observe_sanma_friend_transition=Mock(return_value={'status':'visual_change_unconfirmed'})
   with patch('auto_operator.classify_screen',side_effect=[('match',1.0),('unknown',0)]):op.run_experimental_sanma_friend(page)
   event=next(c for c in op.log.call_args_list if c.kwargs.get('reason')=='white_screen_unobservable')
   self.assertTrue(event.kwargs['currentLoopUnconfirmedInputObserved']);op.execute_sanma_friend_tsumo_candidate.assert_called_once();page.mouse.click.assert_not_called();page.reload.assert_not_called()
