"""Opt-in CPU-friend read-only resident pon observer; never clicks.

Delivery gaps, disconnects, unexpected navigation and elapsed deadlines
invalidate the observation. CDP has no source frame counter: its delivered
frames cannot prove that a visually identical prompt did not disappear and
reappear between emissions. Results are experimental candidates, never proof.
"""
import base64
import math
import time
import json
from sanma_stream_interval import DeliveryInterval
from sanma_pon_sequence_evidence import compare_sequence

class FriendPonMonitor:
 def __init__(self,page,*,enabled,friend_active,ranked,deadline_ms,started,clock=time.monotonic,wall=time.time):
  if (enabled is not True or friend_active() is not True or ranked is not False or deadline_ms!=300000
      or type(started) not in (int,float) or not math.isfinite(started) or not 0<=clock()-started<300):
   raise ValueError('explicit active non-ranked 300+0 CPU friend required')
  self.page=page;self.friend_active=friend_active;self.started=started;self.clock=clock;self.wall=wall
  self.timeline=DeliveryInterval(max_gap=1.5);self.frames=[];self.session=None;self.invalid=None
  self.report_key=None;self.report=None;self.total=0;self.validated=0
 def fail(self,reason):
  if self.invalid is None:self.invalid=reason
 def start(self):
  if self.session is not None or self.invalid:raise RuntimeError('monitor unavailable')
  self.session=self.page.context.new_cdp_session(self.page)
  try:
   self.session.on('Page.screencastFrame',self.receive)
   for name in ('Network.webSocketCreated','Network.webSocketClosed','Network.webSocketFrameError'):
    self.session.on(name,lambda event,name=name:self.fail(name))
   self.session.send('Network.enable')
   for name in ('Page.frameStartedLoading','Page.frameDetached','Inspector.detached','Inspector.targetCrashed'):
    self.session.on(name,lambda event,name=name:self.fail(name))
   self.session.send('Page.enable');self.session.send('Page.startScreencast',{'format':'png','everyNthFrame':1})
  except Exception:
   self.fail('startup');self.close();raise
 def receive(self,event):
  try:
   now=self.clock();stamp=event['metadata']['timestamp'];age=self.wall()-stamp
   if not math.isfinite(age) or age<0 or age>1.5:raise ValueError('stale')
   self.timeline.add(stamp,now)
   if self.timeline.error:raise ValueError(self.timeline.error)
   data=base64.b64decode(event['data'],validate=True)
   if len(self.frames)>=128:raise ValueError('bounded history exhausted')
   self.frames.append({'frame':data,'sequence':self.total,'capturedAt':now});self.total+=1
   if self.report is not None:self._validate_pending()
  except Exception:self.fail('invalid_frame')
  finally:
   try:self.session.send('Page.screencastFrameAck',{'sessionId':event['sessionId']})
   except Exception:self.fail('ack_failed')
 def _validate_pending(self):
  # DeliveryInterval establishes actual order and gaps. Synthetic positions
  # are only for image comparison so the fixed baseline can outlive 20 s.
  while len(self.frames)>=3:
   samples=[{'frame':item['frame'],'sequence':i,'capturedAt':float(i)}
            for i,item in enumerate((self.frames[0],self.frames[1],self.frames[2]))]
   if compare_sequence(samples,self.report).get('status')!='candidate':
    self.fail('frame_changed');return
   self.validated+=1
   del self.frames[1]
 def alive(self):
  try:
   if self.invalid or self.session is None or self.page.is_closed():return False
   self.session.send('Runtime.evaluate',{'expression':'1','returnByValue':True})
   return not self.invalid
  except Exception:
   self.fail('session_unavailable');return False
 def candidate(self,report):
  rejected={'status':'rejected','confirmed':False,'operationAuthorized':False}
  try:
   if (not self.alive() or self.friend_active() is not True or
       not 0<=self.clock()-self.started<300 or self.page.is_closed() or
       self.timeline.result(self.clock(),max_age=1.5)['status']!='bounded_delivery_candidate' or
       self.total<3):return rejected
   key=json.dumps(report,sort_keys=True,separators=(',',':'))
   if self.report_key is None:self.report_key=key;self.report=report
   if self.report_key != key:self.fail('report_changed');return rejected
   self._validate_pending()
   if self.invalid or self.friend_active() is not True or not 0<=self.clock()-self.started<300:return rejected
   return {'status':'candidate','scope':'untrusted_friend_pon_delivery',
           'confirmed':False,'operationAuthorized':False,'framesChecked':self.validated+2,
           'limitations':['CDP does not prove that unreceived frames did not exist']}
  except Exception:return rejected
 def matches(self,report,baseline,fresh):
  # Also check the independently recognized baseline and fresh screenshot
  # against observed frames; these comparisons do not imply capture continuity.
  if self.candidate(report).get('status')!='candidate':return False
  try:
   for frame in (baseline,fresh):
    sample=[{'frame':frame,'sequence':0,'capturedAt':0.0},
            {'frame':self.frames[0]['frame'],'sequence':1,'capturedAt':1.0},
            {'frame':self.frames[-1]['frame'],'sequence':2,'capturedAt':2.0}]
    if compare_sequence(sample,report).get('status')!='candidate':return False
   return (self.alive() and self.friend_active() is True and
           0<=self.clock()-self.started<300 and
           self.timeline.result(self.clock(),max_age=1.5)['status']=='bounded_delivery_candidate')
  except Exception:return False
 def close(self):
  self.timeline.detach();self.fail('closed')
  if self.session is not None:
   session,self.session=self.session,None
   try:session.send('Page.stopScreencast')
   finally:session.detach()
