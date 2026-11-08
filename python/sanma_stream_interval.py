"""Read-only bounded CDP delivery interval; does not prove all frames were emitted.

Local sequence counts delivered events only. CDP screencast provides no source
frame index, so gaps shorter than max_gap cannot prove an absence of omissions.
This diagnostic does not authorize input.
"""
import math
from collections import deque

class DeliveryInterval:
 def __init__(self, max_gap=0.8):
  if type(max_gap) not in (int,float) or not math.isfinite(max_gap) or max_gap<=0:raise ValueError('invalid gap')
  self.max_gap=max_gap;self.events=deque(maxlen=3);self.count=0;self.error=None;self.closed=False
 def invalidate(self, reason):
  if self.error is None:self.error=reason
 def add(self, source_time, received_at):
  if self.closed:self.invalidate('closed');return
  if any(type(t) not in (int,float) or not math.isfinite(t) for t in (source_time,received_at)):
   self.invalidate('invalid_time');return
  if self.events:
   previous=self.events[-1]
   if source_time<=previous[0] or received_at<=previous[1]:self.invalidate('nonmonotonic');return
   if source_time-previous[0]>self.max_gap or received_at-previous[1]>self.max_gap:self.invalidate('delivery_gap');return
  self.events.append((source_time,received_at));self.count+=1
 def detach(self):self.closed=True;self.invalidate('detached')
 def result(self, now, max_age=0.8):
  valid=(self.error is None and not self.closed and len(self.events)>=3 and type(now) in (int,float)
         and math.isfinite(now) and 0<=now-self.events[-1][1]<=max_age)
  return {'status':'bounded_delivery_candidate' if valid else 'rejected','confirmed':False,
          'operationAuthorized':False,'events':self.count,'reason':self.error,
          'limitations':['CDP does not expose source frame numbers; omitted frames cannot be ruled out',
                         'delivery continuity does not establish scene identity or authorize input']}
