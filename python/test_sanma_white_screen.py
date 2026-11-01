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
  with self.assertRaises((OSError,ValueError)):is_blank_white_client_frame(b'not a frame')
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
   page=Mock();page.screenshot.side_effect=[png(Image.new('RGB',(1920,1080),(20,30,60))),white_frame()]
   receipt={'candidates':{'candidates':[{'action':'tsumo'}]},'digest':'first','screenshot':'unused','freshness':{'status':'identical_pixels_candidate'}}
   op.inspect_sanma_self_turn=Mock(return_value=receipt);op.execute_sanma_friend_tsumo_candidate=Mock(return_value={'clicked':True});op.observe_sanma_friend_transition=Mock(return_value={'status':'visual_change_unconfirmed'})
   with patch('auto_operator.classify_screen',side_effect=[('match',1.0),('unknown',0)]):op.run_experimental_sanma_friend(page)
   event=next(c for c in op.log.call_args_list if c.kwargs.get('reason')=='white_screen_unobservable')
   self.assertTrue(event.kwargs['currentLoopUnconfirmedInputObserved']);op.execute_sanma_friend_tsumo_candidate.assert_called_once();page.mouse.click.assert_not_called();page.reload.assert_not_called()

class WhiteScreenFailureTests(unittest.TestCase):
 def setUp(self):
  self.d=tempfile.TemporaryDirectory();self.addCleanup(self.d.cleanup)
  self.frame=png(Image.new('RGB',(1920,1080),(20,30,60)))
  self.op=object.__new__(PythonAutoOperator);self.op.frames=Path(self.d.name);self.op.log=Mock();self.op.screen_references={};self.op.verified_friend_300_active=True
  self.op.args=SimpleNamespace(rules='sanma',mode='force-auto',experimental_sanma_friend=True,action_deadline_ms=300000,ranked_loop=False,start_reviewed_friend_room='reviewed',max_iterations=2)
  self.page=Mock();self.page.screenshot.return_value=white_frame()
 def test_analysis_failure_stops_even_when_classifier_says_match(self):
  self.op.inspect_sanma_self_turn=Mock()
  with patch('auto_operator.classify_screen',return_value=('match',1.0)),patch('auto_operator.is_blank_white_client_frame',side_effect=OSError('bad image')):self.op.run_experimental_sanma_friend(self.page)
  self.assertTrue(any(c.kwargs.get('reason')=='screen_observation_failed' for c in self.op.log.call_args_list));self.op.inspect_sanma_self_turn.assert_not_called();self.page.mouse.click.assert_not_called()
 def test_white_evidence_or_log_failure_never_sends_input(self):
  for failed in ('save','log'):
   with self.subTest(failed=failed):
    with patch('pathlib.Path.write_bytes',side_effect=OSError('unavailable') if failed=='save' else None),patch.object(self.op,'log',side_effect=OSError('unavailable') if failed=='log' else None):
     with self.assertRaises(OSError):self.op.run_experimental_sanma_friend(self.page)
    self.page.mouse.click.assert_not_called();self.page.reload.assert_not_called()
 def test_white_or_corrupt_precapture_stops_and_saves_evidence(self):
  from sanma_friend_discard_experiment import execute_friend_discard
  session={'mode':'cpu_friend','rules':'sanma','clock':'300+0','actionDeadlineMs':300000,'ranked':False,'cpuCount':2,'roomVerified':True};point={'x':200,'y':1000}
  observation={'status':'candidate','phase':'self_turn','promptStatus':'none','handStatus':'candidate','layoutStatus':'candidate','slots':[{'tile':'1m',**point}],'frameSha256':hashlib.sha256(self.frame).hexdigest()}
  plan={'scope':'offline_untrusted_sanma_discard_plan','operationAuthorized':False,'tile':'1m','clickIndex':0,'clickPoint':point}
  for data in (white_frame(),b'bad frame'):
   for save_fails in (False,True):
    self.page.screenshot.return_value=data;saved=Mock(side_effect=OSError('disk failed') if save_fails else None)
    with self.assertRaises((OSError,ValueError)):execute_friend_discard(self.page,session=session,observation=observation,plan=plan,layout={'viewport':{'width':1920,'height':1080}},log=lambda x:None,turn_started_monotonic=100,clock=lambda:101,save_rejected_frame=saved)
    saved.assert_called_once_with(data);self.page.mouse.click.assert_not_called()
 def test_white_second_capture_cannot_cause_confirmation_click(self):
  from sanma_friend_discard_experiment import execute_friend_discard
  session={'mode':'cpu_friend','rules':'sanma','clock':'300+0','actionDeadlineMs':300000,'ranked':False,'cpuCount':2,'roomVerified':True};point={'x':200,'y':1000}
  observation={'status':'candidate','phase':'self_turn','promptStatus':'none','handStatus':'candidate','layoutStatus':'candidate','slots':[{'tile':'1m',**point}],'frameSha256':hashlib.sha256(self.frame).hexdigest()}
  plan={'scope':'offline_untrusted_sanma_discard_plan','operationAuthorized':False,'tile':'1m','clickIndex':0,'clickPoint':point};logs=[]
  self.page.screenshot.side_effect=[self.frame,white_frame()];saved=Mock()
  with patch('auto_operator.raised_tile_confirmation_point',return_value={'x':200,'y':950}) as raised:
   with self.assertRaises(ValueError):execute_friend_discard(self.page,session=session,observation=observation,plan=plan,layout={'viewport':{'width':1920,'height':1080}},log=logs.append,turn_started_monotonic=100,clock=lambda:101,save_rejected_frame=saved)
  saved.assert_called_once_with(white_frame());self.page.mouse.click.assert_called_once_with(200,1000);raised.assert_not_called();self.assertEqual(logs[-1]['result'],'discard_not_verified')
