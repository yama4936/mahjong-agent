import base64,io,unittest
from unittest.mock import Mock
from PIL import Image,ImageDraw
from sanma_friend_pon_monitor import FriendPonMonitor
from test_sanma_pon_sequence_evidence import SequenceTest

class MonitorTest(unittest.TestCase):
 def setUp(self):
  fixture=SequenceTest();fixture.setUp();self.frame=fixture.frame;self.report=fixture.report
  self.page=Mock();self.page.is_closed.return_value=False;self.session=Mock();self.page.context.new_cdp_session.return_value=self.session
  self.now=100.;self.active=True
  self.kw=dict(enabled=True,friend_active=lambda:self.active,ranked=False,deadline_ms=300000,started=100,clock=lambda:self.now,wall=lambda:1000+self.now)
 def start(self):
  self.m=FriendPonMonitor(self.page,**self.kw);self.m.start()
 def send(self,frame=None):
  self.now+=.2;data=base64.b64encode(frame or self.frame).decode();self.m.receive({'metadata':{'timestamp':1000+self.now},'data':data,'sessionId':1})
 def test_friend_only_and_deadline(self):
  for field,value in [('enabled',False),('ranked',True),('deadline_ms',2600)]:
   with self.subTest(field=field),self.assertRaises(ValueError):FriendPonMonitor(self.page,**{**self.kw,field:value})
  self.start();[self.send() for _ in range(3)];self.assertEqual(self.m.candidate(self.report)['status'],'candidate')
  self.now=400.;self.assertEqual(self.m.candidate(self.report)['status'],'rejected');self.m.close()
 def test_visible_ron_or_disappearance_then_reappearance(self):
  self.start();self.send();image=Image.open(io.BytesIO(self.frame)).convert('RGB');ImageDraw.Draw(image).rectangle((900,785,1100,875),fill='white');out=io.BytesIO();image.save(out,format='PNG');self.send(out.getvalue());self.send()
  self.assertEqual(self.m.candidate(self.report)['status'],'rejected');self.m.close()
 def test_frame_gap_disconnect_and_no_click(self):
  self.start();self.send();self.now+=2;self.send();self.send();self.assertEqual(self.m.candidate(self.report)['status'],'rejected');self.m.close();self.page.mouse.click.assert_not_called()
  self.start();[self.send() for _ in range(3)];self.m.fail('Inspector.detached');self.assertEqual(self.m.candidate(self.report)['status'],'rejected');self.m.close()
 def test_compacted_history_latches_intermediate_change(self):
  self.start();[self.send() for _ in range(3)]
  self.assertEqual(self.m.candidate(self.report)['status'],'candidate')
  for _ in range(150):self.send()
  self.assertEqual(len(self.m.frames),2);self.assertEqual(self.m.total,153)
  self.assertEqual(self.m.candidate(self.report)['status'],'candidate')
  image=Image.open(io.BytesIO(self.frame)).convert('RGB');ImageDraw.Draw(image).rectangle((900,785,1100,875),fill='white');out=io.BytesIO();image.save(out,format='PNG')
  self.send(out.getvalue());self.send()
  self.assertEqual(self.m.candidate(self.report)['status'],'rejected');self.assertEqual(self.m.invalid,'frame_changed');self.m.close()
 def test_unexpected_detached_session_rejected_before_stale_timeout(self):
  self.start();[self.send() for _ in range(3)]
  self.assertEqual(self.m.candidate(self.report)['status'],'candidate')
  self.session.send.side_effect=RuntimeError('detached')
  self.assertEqual(self.m.candidate(self.report)['status'],'rejected')
  self.session.send.side_effect=None;self.m.close()
 def test_session_revoked(self):
  self.start();[self.send() for _ in range(3)];self.active=False;self.assertEqual(self.m.candidate(self.report)['status'],'rejected');self.m.close()
