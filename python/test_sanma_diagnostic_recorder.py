import json,os,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from sanma_diagnostic_recorder import Session,PageProxy

def make(d,**kw):
 x=dict(opt_in=True,verified_friend=True,ranked=False,deadline_ms=300000,clock='300+0',commit='a'*40);x.update(kw);return Session(d,'run',**x)
class Tests(unittest.TestCase):
 def test_gates(self):
  with tempfile.TemporaryDirectory() as d:
   for k,v in [('opt_in',False),('verified_friend',False),('ranked',True),('deadline_ms',2600),('clock','5+20')]:
    with self.assertRaises(ValueError):make(d,**{k:v})
 def test_delayed_begin_per_action_and_limits(self):
  with tempfile.TemporaryDirectory() as d:
   s=make(d); a=s.begin('discard',True); a.start-=31_000_000_000
   now=time.monotonic_ns();self.assertFalse(s._offer(a,b'a',now,now))
   a.close(); b=s.begin('kita',True);now=time.monotonic_ns();self.assertTrue(s._offer(b,b'b',now,now))
   with patch.object(s,'MAX_TOTAL',1):self.assertFalse(s._offer(b,b'c',now,now))
   s.close();s.worker.join(3); f=json.loads((s.path/'final.json').read_text());self.assertEqual((f['accepted'],f['dropped'],f['written']),(1,2,1));self.assertFalse(f['confirmed'])
 def test_close_race(self):
  with tempfile.TemporaryDirectory() as d:
   s=make(d);t=s.begin('discard',True)
   barrier=threading.Barrier(3)
   def offer():
    barrier.wait()
    for _ in range(100):
     n=time.monotonic_ns();s._offer(t,b'data',n,n)
   def close():barrier.wait();s.close()
   threads=[threading.Thread(target=offer),threading.Thread(target=close)]
   for x in threads:x.start()
   barrier.wait()
   for x in threads:x.join()
   s.worker.join(3);self.assertFalse(s.worker.is_alive());f=json.loads((s.path/'final.json').read_text());self.assertEqual(f['missingAccepted'],[])
 def test_write_failure(self):
  with tempfile.TemporaryDirectory() as d:
   s=make(d);t=s.begin('discard',True);original=Path.open
   def fail(p,*a,**kw):
    if str(p).endswith('.png.partial'):raise OSError('bad disk')
    return original(p,*a,**kw)
   with patch.object(Path,'open',fail):
    n=time.monotonic_ns();self.assertTrue(s._offer(t,b'data',n,n))
    for _ in range(100):
     if s.failed:break
     time.sleep(.01)
    self.assertTrue(s.failed);s.close();s.worker.join(3)
   f=json.loads((s.path/'final.json').read_text());self.assertEqual(f['missingAccepted'],[0]);self.assertIn('bad disk',f['error'])
 def test_proxy_and_revocation(self):
  class Page:
   def screenshot(self,**kw):return b'frame'
  with tempfile.TemporaryDirectory() as d:
   s=make(d)
   with self.assertRaises(ValueError):s.begin('discard',False)
   t=s.begin('discard',True);self.assertEqual(PageProxy(Page(),t).screenshot(),b'frame');t.close()
   now=time.monotonic_ns();self.assertFalse(s._offer(t,b'frame',now,now));s.close();s.worker.join(3)
if __name__=='__main__':unittest.main()

class ActualObservationTests(unittest.TestCase):
 def test_real_observer_proxy_preserves_unresolved_and_does_not_click(self):
  import hashlib
  from unittest.mock import Mock,patch
  from auto_operator import PythonAutoOperator
  with tempfile.TemporaryDirectory() as d:
   op=object.__new__(PythonAutoOperator);op.frames=Path(d);op.verified_friend_300_active=True;op.screen_references={};op.river_clip={};op.hand_clip={}
   before=Path(d)/'before';before.write_bytes(b'before');receipt={'screenshot':str(before),'digest':hashlib.sha256(b'before').hexdigest()}
   p=Mock();p.screenshot.return_value=b'after'
   with patch('auto_operator.classify_screen',return_value=('unknown',0.0)),patch('auto_operator.experimental_friend_score_transfer_candidate',return_value=False):
    regular=op.observe_sanma_friend_transition(p,receipt,'discard')
    session=make(d);transition=session.begin('discard',op.verified_friend_300_active)
    recorded=op.observe_sanma_friend_transition(PageProxy(p,transition),receipt,'discard')
    transition.close();session.close();session.worker.join(3)
   self.assertEqual((regular['status'],regular['reason'],regular['confirmed']),(recorded['status'],recorded['reason'],recorded['confirmed']))
   p.mouse.click.assert_not_called();self.assertFalse(session.worker.is_alive())

class HookTests(unittest.TestCase):
 def test_normal_and_enabled_paths_preserve_result_and_exception(self):
  from unittest.mock import Mock
  from auto_operator import PythonAutoOperator
  op=object.__new__(PythonAutoOperator); op.verified_friend_300_active=True
  expected={'status':'unresolved','confirmed':False}
  op._observe_sanma_friend_transition=Mock(return_value=expected)
  page=Mock();self.assertIs(op.observe_sanma_friend_transition(page,{},'discard'),expected)
  with tempfile.TemporaryDirectory() as d:
   session=make(d);op.sanma_transition_recorder=session
   self.assertIs(op.observe_sanma_friend_transition(page,{},'discard'),expected)
   self.assertIsInstance(op._observe_sanma_friend_transition.call_args.args[0],PageProxy)
   op._observe_sanma_friend_transition.side_effect=RuntimeError('observation')
   with self.assertRaisesRegex(RuntimeError,'observation'):op.observe_sanma_friend_transition(page,{},'discard')
   session.close();session.worker.join(3);self.assertFalse(session.worker.is_alive())
 def test_revoked_does_not_wrap(self):
  from unittest.mock import Mock
  from auto_operator import PythonAutoOperator
  op=object.__new__(PythonAutoOperator);op.verified_friend_300_active=False
  op.sanma_transition_recorder=Mock();op._observe_sanma_friend_transition=Mock(return_value={'confirmed':False})
  page=Mock();op.observe_sanma_friend_transition(page,{},'discard')
  op.sanma_transition_recorder.begin.assert_not_called();self.assertIs(op._observe_sanma_friend_transition.call_args.args[0],page)

class BoundaryTests(unittest.TestCase):
 def test_drop_reasons_distinguish_queue_quota_and_expiry_without_blocking(self):
  with tempfile.TemporaryDirectory() as d:
   s=make(d);t=s.begin('discard',True);ready=threading.Event();release=threading.Event();original=Path.open
   def delayed(path,*args,**kwargs):
    if str(path).endswith('.png.partial'):
     ready.set();release.wait(3)
    return original(path,*args,**kwargs)
   try:
    with patch.object(Path,'open',delayed):
     n=time.monotonic_ns();self.assertTrue(s._offer(t,b'data',n,n));self.assertTrue(ready.wait(1))
     start=time.monotonic()
     for _ in range(2):
      n=time.monotonic_ns();self.assertTrue(s._offer(t,b'data',n,n))
     n=time.monotonic_ns();self.assertFalse(s._offer(t,b'data',n,n))
     with patch.object(s,'MAX_TOTAL',s.total):
      n=time.monotonic_ns();self.assertFalse(s._offer(t,b'data',n,n))
     t.start-=31_000_000_000
     n=time.monotonic_ns();self.assertFalse(s._offer(t,b'data',n,n))
     s.close();self.assertLess(time.monotonic()-start,.1)
     release.set();s.worker.join(3)
   finally: release.set();s.close();s.worker.join(3)
   f=json.loads((s.path/'final.json').read_text())
   self.assertEqual((f['accepted'],f['dropped'],f['written']),(3,3,3))
   self.assertEqual({k:v for k,v in f['dropReasons'].items() if v},{'queue_full':1,'byte_limit':1,'time_limit':1})
   self.assertEqual(f['missingAccepted'],[])
 def test_untrusted_root_and_lock(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'root';root.mkdir(mode=0o700);alias=Path(d)/'alias';alias.symlink_to(root,target_is_directory=True)
   with self.assertRaises(ValueError):make(alias)
   root.chmod(0o755)
   with self.assertRaises(ValueError):make(root)
 def test_hard_kill_cannot_claim_final(self):
  import subprocess,sys
  with tempfile.TemporaryDirectory() as d:
   code='from sanma_diagnostic_recorder import Session; import sys,time; s=Session(sys.argv[1],"run",opt_in=True,verified_friend=True,ranked=False,deadline_ms=300000,clock="300+0",commit="a"*40);print("ready",flush=True);time.sleep(30)'
   p=subprocess.Popen([sys.executable,'-c',code,d],stdout=subprocess.PIPE,text=True)
   self.assertEqual(p.stdout.readline().strip(),'ready');p.kill();p.wait(timeout=3);p.stdout.close()
   self.assertTrue((Path(d)/'run/started.json').exists());self.assertFalse((Path(d)/'run/final.json').exists())
 def test_delayed_write_does_not_wait_on_offer_or_close(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   s=make(d);t=s.begin('discard',True);ready=threading.Event();release=threading.Event();original=Path.open
   def delayed(path,*args,**kwargs):
    if str(path).endswith('.png.partial'):ready.set();release.wait(3)
    return original(path,*args,**kwargs)
   with patch.object(Path,'open',delayed):
    now=time.monotonic_ns();self.assertTrue(s._offer(t,b'data',now,now));self.assertTrue(ready.wait(1))
    start=time.monotonic();s.close();self.assertLess(time.monotonic()-start,.1)
    self.assertTrue(s.worker.is_alive());release.set();s.worker.join(3)
   self.assertFalse(s.worker.is_alive());self.assertTrue((s.path/'final.json').exists())

class ProcessLockTests(unittest.TestCase):
 def test_same_run_name_rejected_by_second_process(self):
  import subprocess,sys
  with tempfile.TemporaryDirectory() as d:
   s=make(d)
   code='from sanma_diagnostic_recorder import Session; import sys; Session(sys.argv[1],"run",opt_in=True,verified_friend=True,ranked=False,deadline_ms=300000,clock="300+0",commit="a"*40)'
   p=subprocess.run([sys.executable,'-c',code,d],capture_output=True,text=True,timeout=3)
   self.assertNotEqual(p.returncode,0);self.assertIn('FileExistsError',p.stderr)
   s.close();s.worker.join(3);self.assertFalse(s.worker.is_alive())
 def test_replaced_root_reports_failure(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'root';root.mkdir(mode=0o700);s=make(root);t=s.begin('discard',True)
   root.rename(Path(d)/'old');root.mkdir(mode=0o700)
   n=time.monotonic_ns();self.assertTrue(s._offer(t,b'data',n,n))
   for _ in range(100):
    if s.failed:break
    time.sleep(.01)
   self.assertTrue(s.failed);s.close();s.worker.join(3);self.assertFalse(s.worker.is_alive())
   self.assertFalse((root/'run/final.json').exists())
 def test_distinct_runs_are_independent_and_each_bounded(self):
  with tempfile.TemporaryDirectory() as d:
   a=make(d);b=Session(d,'second',opt_in=True,verified_friend=True,ranked=False,deadline_ms=300000,clock='300+0',commit='a'*40)
   for s in (a,b):
    t=s.begin('discard',True);n=time.monotonic_ns()
    with patch.object(s,'MAX_TOTAL',1):
     self.assertTrue(s._offer(t,b'a',n,n));self.assertFalse(s._offer(t,b'b',n,n))
    s.close();s.worker.join(3);self.assertFalse(s.worker.is_alive())
    summary=json.loads((s.path/'started.json').read_text());self.assertIn('no shared total quota',summary['quotaScope'])
