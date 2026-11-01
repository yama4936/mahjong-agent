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
  self.assertEqual(len(errors),1);e=errors[0];self.assertEqual(e['errorType'],'ImportError');self.assertEqual(e['pythonExecutable'],sys.executable)
  self.assertIsNone(e['numpyVersion']);self.assertIsNone(e['numpyPath']);self.assertFalse(e['operationAuthorized'])
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
