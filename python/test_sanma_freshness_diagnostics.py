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
  self.assertTrue(all(type(v) is int and v>=0 for v in f['timingMs'].values()))
  self.assertTrue(all(type(v['elapsedMs']) is int and v['elapsedMs']>=0 for v in f['guards'].values()))
  self.page.mouse.click.assert_not_called()
