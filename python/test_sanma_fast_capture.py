import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sanma_fast_capture import fast_capture_driver_environment

class FastCaptureEnvironmentTest(unittest.TestCase):
 def test_driver_hook_is_temporary_and_does_not_change_process_environment(self):
  import playwright._impl._transport as transport
  original=transport.get_driver_env;before=dict(os.environ)
  with tempfile.TemporaryDirectory() as directory:
   with fast_capture_driver_environment(True,directory) as state:
    self.assertEqual(state['status'],'pending');env=transport.get_driver_env()
    self.assertIn('sanma_fast_capture_preload.cjs',env['NODE_OPTIONS']);self.assertEqual(env['SANMA_FAST_CAPTURE_STATUS'],state['marker'])
    self.assertEqual(dict(os.environ),before)
   self.assertIs(transport.get_driver_env,original);self.assertEqual(dict(os.environ),before)
 def test_incompatible_hash_uses_stock_driver(self):
  import playwright._impl._transport as transport
  original=transport.get_driver_env
  with tempfile.TemporaryDirectory() as directory,patch('sanma_fast_capture.EXPECTED_SHA256','bad'):
   with fast_capture_driver_environment(True,directory) as state:
    self.assertEqual(state['status'],'fallback_incompatible_driver');self.assertIs(transport.get_driver_env,original)
  self.assertIs(transport.get_driver_env,original)
 def test_disabled_leaves_stock_driver(self):
  import playwright._impl._transport as transport
  original=transport.get_driver_env
  with fast_capture_driver_environment(False,'/unused') as state:
   self.assertEqual(state['status'],'disabled');self.assertIs(transport.get_driver_env,original)
 def test_raising_in_context_restores_driver_environment(self):
  import playwright._impl._transport as transport
  original=transport.get_driver_env
  with tempfile.TemporaryDirectory() as directory:
   with self.assertRaisesRegex(RuntimeError,'failure'):
    with fast_capture_driver_environment(True,directory):raise RuntimeError('failure')
  self.assertIs(transport.get_driver_env,original)
 def test_option_requires_explicit_friend_scope_and_deadline(self):
  import sys
  from auto_operator import parse_args
  common=['operator','--layout','x','--templates','x','--state','x','--experimental-sanma-fast-png']
  valid=['--rules','sanma','--experimental-sanma-friend','--mode','force-auto','--action-deadline-ms','300000','--start-reviewed-friend-room','reviewed']
  with patch.object(sys,'argv',common+valid):self.assertTrue(parse_args().experimental_sanma_fast_png)
  for invalid in ([],valid+['--ranked-loop'],[v for v in valid if v!='--experimental-sanma-friend'],valid[:-2]):
   with self.subTest(invalid=invalid),patch.object(sys,'argv',common+invalid):
    with self.assertRaises(SystemExit):parse_args()
 def test_missing_status_restarts_stock_driver_before_any_browser_access(self):
  from contextlib import ExitStack,contextmanager
  from types import SimpleNamespace
  from unittest.mock import Mock,MagicMock
  from auto_operator import start_playwright_with_sanma_capture
  first,stock=MagicMock(),MagicMock();first.__enter__=Mock(return_value='first');first.__exit__=Mock(return_value=False)
  stock.__enter__=Mock(return_value='stock');stock.__exit__=Mock(return_value=False)
  @contextmanager
  def environment(enabled,directory):yield {'requested':True,'status':'pending','marker':'/nonexistent/marker'}
  operator=Mock();operator.frames=Path('/unused')
  with patch('auto_operator.fast_capture_driver_environment',side_effect=environment),patch('auto_operator.sync_playwright',side_effect=[first,stock]) as launch:
   with ExitStack() as stack:
    result=start_playwright_with_sanma_capture(stack,SimpleNamespace(experimental_sanma_fast_png=True),operator)
    self.assertEqual(result,'stock');first.__exit__.assert_called_once();self.assertEqual(launch.call_count,2)
  operator.log.assert_called_once_with('sanma_fast_png_driver',enabled=False,status='stock_fallback',operationAuthorized=False)
 def test_preloader_rejects_changed_target_without_status_marker(self):
  import subprocess
  with tempfile.TemporaryDirectory() as directory:
   target=Path(directory)/'changed.js';target.write_text('module.exports=42;')
   marker=Path(directory)/'status';preload=Path(__file__).with_name('sanma_fast_capture_preload.cjs').resolve()
   env={**os.environ,'NODE_OPTIONS':'--require='+str(preload),'SANMA_FAST_CAPTURE_TARGET':str(target),'SANMA_FAST_CAPTURE_STATUS':str(marker)}
   result=subprocess.run(['node','-e','if(require(process.argv[1])!==42)process.exit(1)',str(target)],env=env,capture_output=True,timeout=5)
   self.assertEqual(result.returncode,0);self.assertFalse(marker.exists())

@unittest.skipUnless(os.environ.get('SANMA_FAST_CAPTURE_CHROMIUM'), 'isolated Chromium path not provided')
class FastCaptureChromiumTest(unittest.TestCase):
 def test_static_css_and_webgl_pixels_match_stock_screenshots(self):
  import io,base64
  from contextlib import ExitStack
  from types import SimpleNamespace
  from unittest.mock import Mock
  from PIL import Image,ImageChops
  from auto_operator import start_playwright_with_sanma_capture
  screenshots=[]
  with tempfile.TemporaryDirectory(dir='/home/yama1/.codex') as directory:
   for enabled in (False,True):
    operator=SimpleNamespace(frames=Path(directory),log=Mock())
    with ExitStack() as stack:
     p=start_playwright_with_sanma_capture(stack,SimpleNamespace(experimental_sanma_fast_png=enabled),operator)
     browser=p.chromium.launch(executable_path=os.environ['SANMA_FAST_CAPTURE_CHROMIUM'],headless=True,args=['--no-sandbox','--disable-background-networking','--enable-unsafe-swiftshader','--use-angle=swiftshader-webgl'])
     try:
      page=browser.new_page(viewport={'width':1920,'height':1080},device_scale_factor=1)
      source=os.environ.get('SANMA_FAST_CAPTURE_IMAGE')
      if source:
       data=base64.b64encode(Path(source).read_bytes()).decode()
       page.set_content('<style>html,body{margin:0}img{display:block}</style><img src="data:image/png;base64,'+data+'">')
       page.locator('img').evaluate('(e)=>e.decode()');image=page.screenshot(animations='disabled',timeout=3000)
      else:image=None
      page.set_content('<style>html,body{margin:0}@keyframes k{from{background:red}to{background:blue}}div{height:1080px;width:1920px;animation:k 1s linear infinite}</style><div></div>')
      page.wait_for_timeout(350);css=page.screenshot(animations='disabled',timeout=3000)
      page.set_content('<style>body{margin:0;background:#385676}</style><canvas width="1920" height="1080"></canvas>')
      ok=page.evaluate("() => {let g=document.querySelector('canvas').getContext('webgl',{alpha:true,preserveDrawingBuffer:true});if(!g)return false;g.clearColor(.3,.7,.25,.5);g.clear(g.COLOR_BUFFER_BIT);g.finish();return true}")
      self.assertTrue(ok);page.wait_for_timeout(50);webgl=page.screenshot(animations='disabled',timeout=3000)
      screenshots.append((css,webgl,image))
     finally:browser.close()
    if enabled:operator.log.assert_called_once_with('sanma_fast_png_driver',enabled=True,status='patched',operationAuthorized=False)
   for a,b in zip(*screenshots):
    if a is None and b is None:continue
    ia,ib=Image.open(io.BytesIO(a)),Image.open(io.BytesIO(b));self.assertEqual((ia.size,ia.mode),(ib.size,ib.mode));self.assertIsNone(ImageChops.difference(ia,ib).getbbox())
