import base64, io, time, unittest
from unittest.mock import patch
from PIL import Image
from sanma_png_stream import SanmaPngStream

class Session:
 def __init__(self): self.calls=[]
 def on(self, name, fn): self.fn=fn
 def send(self, name, args=None): self.calls.append(name)
 def detach(self): self.calls.append('detach')
class Page:
 def __init__(self): self.context=self;self.session=Session();self.wait=lambda:None
 def new_cdp_session(self,page): return self.session
 def wait_for_timeout(self,ms): self.wait()
def frame(t, data=None):
 if data is None:
  out=io.BytesIO();Image.new('RGB',(1920,1080)).save(out,format='PNG');data=out.getvalue()
 return {'metadata':{'timestamp':t},'data':base64.b64encode(data).decode(),'sessionId':1}
class StreamTests(unittest.TestCase):
 def setUp(self):self.page=Page();self.stream=SanmaPngStream(self.page,timeout=.02);self.stream.start()
 def tearDown(self):self.stream.close()
 def test_fresh_new_frame(self):
  threshold=time.time()-0.01;self.stream._receive(frame(time.time()));self.assertTrue(self.stream.capture_after(threshold).startswith(b'\x89PNG'))
 def test_old_frame_does_not_qualify(self):
  now=time.time();self.stream._receive(frame(now));
  with self.assertRaises(RuntimeError):self.stream.capture_after(now)
 def test_missing_timestamp(self):
  f=frame(time.time());del f['metadata']['timestamp'];self.stream._receive(f)
  with self.assertRaises(RuntimeError):self.stream.capture_after(0)
 def test_reversed_timestamp_fails_closed(self):
  now=time.time();self.stream._receive(frame(now));self.stream._receive(frame(now-.01))
  with self.assertRaises(RuntimeError):self.stream.capture_after(0)
 def test_delayed_or_future_frame_rejected(self):
  for stamp in (time.time()-2,time.time()+2):
   self.stream.error=None;self.stream._receive(frame(stamp));self.assertTrue(self.stream.error)
 def test_interrupted_stream_times_out(self):
  with self.assertRaises(RuntimeError):self.stream.capture_after(time.time())
 def test_corrupt_png_fails_closed(self):
  self.stream._receive(frame(time.time(),b'broken'))
  with self.assertRaises(RuntimeError):self.stream.capture_after(0)
 def test_ack_failure_invalidates_frame(self):
  old=self.page.session.send
  def fail(name,args=None):
   if name == "Page.screencastFrameAck": raise RuntimeError("ack failed")
   return old(name,args)
  self.page.session.send=fail;self.stream._receive(frame(time.time()))
  with self.assertRaises(RuntimeError):self.stream.capture_after(0)
 def test_ack_empty_exception_fails_closed(self):
  old=self.page.session.send
  def fail(name,args=None):
   if name == 'Page.screencastFrameAck': raise RuntimeError('')
   return old(name,args)
  self.page.session.send=fail;self.stream._receive(frame(time.time()))
  with self.assertRaises(RuntimeError): self.stream.capture_after(0)
 def test_close_stops_and_detaches(self):
  self.stream.close();self.assertIn('Page.stopScreencast',self.page.session.calls);self.assertIn('detach',self.page.session.calls)
