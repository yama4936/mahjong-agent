import hashlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image
from auto_operator import PythonAutoOperator, experimental_draw_glyph_stability

class FreshnessDiagnosticsTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  output=io.BytesIO();Image.new('RGB',(1920,1080),(25,35,55)).save(output,format='PNG');self.frame=output.getvalue()
  self.digest=hashlib.sha256(self.frame).hexdigest()
  report=json.loads((Path(__file__).parent/'fixtures/sanma-c177-kita-report.json').read_text());report['digest']=self.digest
  result={'assembly':{'operationAuthorized':False,'priority':{'status':'blocked'},'evaluation':{'status':'blocked'}},'digest':self.digest,'report':report,'structuralPositions':{'status':'blocked','operationAuthorized':False,'digest':self.digest,'candidates':[]}}
  self.op=object.__new__(PythonAutoOperator);self.op.frames=Path(self.temp.name);self.op.log=Mock();self.op.observe_sanma_resident=Mock(return_value=result);self.op.verified_friend_300_active=True;self.op.verified_friend_300_started_at=time.monotonic()
  self.op.args=SimpleNamespace(rules='sanma',mode='force-auto',experimental_sanma_friend=True,action_deadline_ms=300000,ranked_loop=False,start_reviewed_friend_room='reviewed')
  self.page=Mock();self.page.screenshot.return_value=self.frame
 def test_real_guard_exception_and_rejection_are_distinct(self):
  detail={};self.assertFalse(experimental_draw_glyph_stability(b'bad',b'bad',{},diagnostic=detail));self.assertEqual(detail['outcome'],'exception');self.assertIn('errorType',detail)
  detail={};report={'hand':{'status':'unresolved','value':{}},'handGeometry':{'status':'candidate','value':{}},'buttonRow':{'status':'candidate','value':{'slots':[]}}}
  self.assertFalse(experimental_draw_glyph_stability(self.frame,self.frame,report,diagnostic=detail));self.assertEqual(detail['stage'],'recognition_and_prompt');self.assertNotEqual(detail.get('outcome'),'exception')
 def test_observation_records_durations_rejection_and_frame_hashes(self):
  def kita(*args,diagnostic=None,**kwargs):diagnostic['stage']='wall_color';return False
  def draw(*args,diagnostic=None,**kwargs):diagnostic.update(stage='recognition_and_prompt',outcome='exception',errorType='KeyError');return False
  with patch('auto_operator.friend_frame_changes',return_value={'hand':True,'actions':False,'fullFrame':True,'clock':False}),patch('auto_operator.experimental_kita_glyph_stability',side_effect=kita),patch('auto_operator.experimental_draw_glyph_stability',side_effect=draw):
   receipt=self.op.inspect_sanma_self_turn(self.page)
  f=receipt['freshness'];self.assertEqual(f['status'],'changed');self.assertFalse(f['operationAuthorized']);self.assertEqual(receipt['digest'],self.digest);self.assertEqual(f['digest'],self.digest)
  self.assertEqual(f['guards']['kita']['outcome'],'rejected');self.assertEqual(f['guards']['draw']['outcome'],'exception');self.assertEqual(f['guards']['draw']['errorType'],'KeyError')
  self.assertEqual(f['captureMode'],'screenshot');self.assertIsNone(f['timingMs']['streamWait'])
  self.assertTrue(all(type(v) is int and v>=0 for v in f['timingMs'].values() if v is not None))
  self.assertTrue(all(type(v['elapsedMs']) is int and v['elapsedMs']>=0 for v in f['guards'].values()))
  self.page.mouse.click.assert_not_called()
 def test_stream_wait_is_not_reported_as_screenshot_duration(self):
  self.op.args.experimental_sanma_png_stream=True
  stream=Mock();stream.capture_after.return_value=self.frame
  with patch('auto_operator.require_verified_png_stream_clock'),patch('auto_operator.SanmaPngStream',return_value=stream):
   receipt=self.op.inspect_sanma_self_turn(self.page)
  timing=receipt['freshness']['timingMs']
  self.assertEqual(receipt['freshness']['captureMode'],'png_stream')
  self.assertIsNone(timing['freshCapture']);self.assertIsNone(timing['betweenCaptureReturns'])
  self.assertIsInstance(timing['streamWait'],int);stream.capture_after.assert_called_once();stream.close.assert_called_once()
  self.page.mouse.click.assert_not_called()
 def test_observation_log_failure_never_returns_actionable_receipt(self):
  self.op.log.side_effect=OSError('log unavailable')
  with self.assertRaises(OSError):self.op.inspect_sanma_self_turn(self.page)
  self.page.mouse.click.assert_not_called()
 def test_receipt_write_failure_never_returns_actionable_receipt(self):
  with patch('auto_operator.os.open',side_effect=OSError('record unavailable')):
   with self.assertRaises(RuntimeError):self.op.inspect_sanma_self_turn(self.page)
  self.page.mouse.click.assert_not_called()
 def test_parallel_guard_diagnostics_remain_independent(self):
  from concurrent.futures import ThreadPoolExecutor
  def invalid_frame():
   diagnostic={};result=experimental_draw_glyph_stability(b'bad',b'bad',{},diagnostic=diagnostic);return result,diagnostic
  def missing_data():
   diagnostic={};result=experimental_draw_glyph_stability(self.frame,self.frame,{},diagnostic=diagnostic);return result,diagnostic
  with ThreadPoolExecutor(max_workers=2) as pool:
   first=pool.submit(invalid_frame);second=pool.submit(missing_data)
   a,b=first.result(),second.result()
  self.assertFalse(a[0]);self.assertFalse(b[0])
  self.assertEqual(a[1]['outcome'],'exception');self.assertEqual(b[1]['outcome'],'exception')
  self.assertEqual(a[1]['errorType'],'UnidentifiedImageError');self.assertEqual(b[1]['errorType'],'KeyError')
