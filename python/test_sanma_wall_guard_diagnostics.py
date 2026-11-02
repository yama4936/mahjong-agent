import builtins
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from auto_operator import experimental_kita_wall_color_stable, experimental_draw_glyph_stability, experimental_kita_glyph_stability

class WallGuardDiagnostics(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  out=io.BytesIO(); Image.new('RGB',(1920,1080),(25,35,55)).save(out,format='PNG');cls.frame=out.getvalue()
  cls.report=json.loads((Path(__file__).parent/'fixtures/sanma-c177-kita-report.json').read_text())
 def import_failure(self,callback):
  original=builtins.__import__
  def missing(name,*args,**kwargs):
   if name=='numpy': raise ImportError('simulated missing numpy')
   return original(name,*args,**kwargs)
  with patch('builtins.__import__',side_effect=missing):return callback()
 def test_numpy_error_has_environment_and_fails_closed(self):
  errors=[]
  self.assertFalse(self.import_failure(lambda:experimental_kita_wall_color_stable(self.frame,self.frame,on_error=errors.append)))
  self.assertEqual(len(errors),1);e=errors[0];self.assertEqual(e['errorType'],'ImportError');self.assertEqual(e['pythonVersion'],sys.version.split()[0])
  self.assertIsNone(e['numpyVersion']);self.assertFalse(e['numpyAvailable']);self.assertNotIn('error',e);self.assertNotIn('numpyPath',e);self.assertFalse(e['operationAuthorized'])
 def test_callback_failure_is_also_fail_closed(self):
  def broken(_):raise RuntimeError('logging unavailable')
  self.assertFalse(self.import_failure(lambda:experimental_kita_wall_color_stable(self.frame,self.frame,on_error=broken)))
 def test_normal_visual_mismatch_is_not_reported_as_runtime_error(self):
  bad=Image.new('RGB',(1920,1080),(255,0,0));out=io.BytesIO();bad.save(out,format='PNG');errors=[]
  self.assertFalse(experimental_kita_wall_color_stable(self.frame,out.getvalue(),on_error=errors.append));self.assertEqual(errors,[])
 def test_kita_and_draw_paths_propagate_guard_errors(self):
  reports=[];self.assertFalse(self.import_failure(lambda:experimental_kita_glyph_stability(self.frame,self.frame,self.report,on_wall_error=reports.append)));self.assertEqual(len(reports),1)
  report=json.loads(json.dumps(self.report));report['hand']['value']['turnReady']=True;report['buttonRow']['value']['slots']=[{'slot':i,'status':'empty_candidate'} for i in range(3)]
  reports=[];self.assertFalse(self.import_failure(lambda:experimental_draw_glyph_stability(self.frame,self.frame,report,on_wall_error=reports.append)));self.assertEqual(len(reports),1)

class WallGuardIntegration(unittest.TestCase):
 def setUp(self):
  import tempfile,hashlib,time
  from types import SimpleNamespace
  from unittest.mock import Mock
  from auto_operator import PythonAutoOperator
  self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup);self.frames=Path(self.directory.name)
  out=io.BytesIO();Image.new('RGB',(1920,1080),(25,35,55)).save(out,format='PNG');self.frame=out.getvalue()
  self.digest=hashlib.sha256(self.frame).hexdigest();self.path=self.frames/'before.png';self.path.write_bytes(self.frame)
  self.report=json.loads((Path(__file__).parent/'fixtures/sanma-c177-kita-report.json').read_text());self.report['digest']=self.digest
  self.op=object.__new__(PythonAutoOperator);self.op.frames=self.frames;self.op.log=Mock();self.op.screen_references={};self.op.verified_friend_300_active=True;self.op.verified_friend_300_started_at=time.monotonic()
  self.op.args=SimpleNamespace(rules='sanma',mode='force-auto',experimental_sanma_friend=True,action_deadline_ms=300000,ranked_loop=False,start_reviewed_friend_room='reviewed')
  self.page=Mock();self.page.screenshot.return_value=self.frame
  self.failure={'errorType':'ImportError','pythonVersion':'3','numpyAvailable':False,'numpyVersion':None,'operationAuthorized':False}
 def failed_kita(self,*args,on_wall_error=None,**kwargs):
  try:on_wall_error(self.failure)
  except Exception:pass
  return False
 def test_observation_latches_failure_even_if_second_guard_would_succeed_or_log_fails(self):
  from unittest.mock import Mock,patch
  result={'assembly':{'operationAuthorized':False,'priority':{'status':'blocked'},'evaluation':{'status':'blocked'}},'digest':self.digest,'report':self.report,'structuralPositions':{'status':'blocked','operationAuthorized':False,'digest':self.digest,'candidates':[]}}
  self.op.observe_sanma_resident=Mock(return_value=result)
  for logger_fails in (False,True):
   with self.subTest(logger_fails=logger_fails):
    self.op.log.side_effect=(lambda event,**kwargs: (_ for _ in ()).throw(OSError('log unavailable')) if event=='sanma_wall_guard_error' else None) if logger_fails else None
    with patch('auto_operator.friend_frame_changes',return_value={'hand':True,'actions':True,'fullFrame':True,'clock':False}),patch('auto_operator.experimental_kita_glyph_stability',side_effect=self.failed_kita),patch('auto_operator.experimental_draw_glyph_stability',return_value=True) as draw:
     receipt=self.op.inspect_sanma_self_turn(self.page)
    self.assertEqual(receipt['freshness']['status'],'unknown');self.assertFalse(receipt['freshness']['operationAuthorized']);draw.assert_not_called();self.page.mouse.click.assert_not_called()
 def test_kita_preclick_guard_error_or_failed_log_never_clicks(self):
  from unittest.mock import patch
  receipt={'scope':'sanma_self_turn_observation','status':'blocked','operationAuthorized':False,'digest':self.digest,'screenshot':str(self.path),'sourceObservation':{'digest':self.digest,'operationAuthorized':False,'report':self.report},'freshness':{'status':'stable_kita_glyph_candidate','operationAuthorized':False,'elapsedMs':1000}}
  for logger_fails in (False,True):
   with self.subTest(logger_fails=logger_fails):
    self.op.log.side_effect=(lambda event,**kwargs: (_ for _ in ()).throw(OSError('log unavailable')) if event=='sanma_wall_guard_error' else None) if logger_fails else None
    with patch('auto_operator.friend_frame_stable',return_value=False),patch('auto_operator.experimental_kita_glyph_stability',side_effect=self.failed_kita):
     with self.assertRaises(RuntimeError):self.op.execute_sanma_friend_kita_candidate(self.page,receipt)
    self.page.mouse.click.assert_not_called()
 def test_draw_preclick_guard_error_or_failed_log_never_clicks(self):
  from unittest.mock import Mock,patch
  from sanma_friend_discard_experiment import execute_friend_discard, DiscardPreclickChanged
  session={'mode':'cpu_friend','rules':'sanma','clock':'300+0','actionDeadlineMs':300000,'ranked':False,'cpuCount':2,'roomVerified':True}
  point={'x':200,'y':1000};observation={'status':'candidate','phase':'self_turn','promptStatus':'none','handStatus':'candidate','layoutStatus':'candidate','slots':[{'tile':'1m',**point}],'frameSha256':self.digest,'referenceFrame':self.frame,'experimentalDrawReport':self.report}
  plan={'scope':'offline_untrusted_sanma_discard_plan','operationAuthorized':False,'tile':'1m','clickIndex':0,'clickPoint':point}
  observation['experimentalDrawReport']=json.loads(json.dumps(self.report))
  observation['experimentalDrawReport']['hand']['value']['turnReady']=True
  observation['experimentalDrawReport']['buttonRow']['value']['slots']=[{'slot':i,'status':'empty_candidate'} for i in range(3)]
  changed=io.BytesIO();Image.new('RGB',(1920,1080),(35,45,65)).save(changed,format='PNG')
  self.page.screenshot.return_value=changed.getvalue();records=[]
  for logger_fails in (False,True):
   def log(data):
    records.append(data)
    if logger_fails and data.get('kind')=='sanma_wall_guard_error':raise OSError('log unavailable')
   original_import=builtins.__import__
   def missing_numpy(name,*args,**kwargs):
    if name=='numpy':raise ImportError('simulated missing numpy')
    return original_import(name,*args,**kwargs)
   with self.subTest(logger_fails=logger_fails),patch('sanma_friend_discard_experiment.friend_frame_stable',return_value=False),patch('builtins.__import__',side_effect=missing_numpy),patch('sanma_friend_discard_experiment.send_discard_click') as send:
    with self.assertRaises(DiscardPreclickChanged):execute_friend_discard(self.page,session=session,observation=observation,plan=plan,layout={'viewport':{'width':1920,'height':1080}},log=log,turn_started_monotonic=100,clock=lambda:101)
    send.assert_not_called();self.page.mouse.click.assert_not_called()
    self.assertEqual(records[-2]['kind'],'sanma_wall_guard_error')
  self.assertTrue(any(x.get('kind')=='sanma_wall_guard_error' for x in records))
