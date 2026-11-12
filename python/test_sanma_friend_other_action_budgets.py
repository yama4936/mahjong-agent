"""Real dispatch paths, fake clocks/screens; no game input."""
import hashlib
import io
from PIL import Image
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from auto_operator import PythonAutoOperator, SelectionStateUncertainAbort
from sanma_friend_pass_experiment import execute_friend_pon_pass
from sanma_friend_riichi_experiment import execute_friend_riichi

class OtherActionBudgetTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.t=100.;buffer=io.BytesIO();Image.new('RGB',(1920,1080),(25,50,75)).save(buffer,format='PNG');self.frame=buffer.getvalue();self.digest=hashlib.sha256(self.frame).hexdigest()
  self.path=Path(self.tmp.name)/'frame.png';self.path.write_bytes(self.frame)
  self.op=object.__new__(PythonAutoOperator);self.op.args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,force_auto_click_budget_ms=8000,ranked_loop=False,experimental_sanma_friend=True)
  self.op.verified_friend_300_active=True;self.op.verified_friend_300_started_at=100.;self.op.frames=Path(self.tmp.name);self.op.log=Mock();self.op.screen_references={};self.op._sanma_friend_resume_guard=None
  self.op.layout={'viewport':{'width':1920,'height':1080},'clickPoints':[{'x':300,'y':1000}]}
  self.page=Mock();self.page.screenshot.return_value=self.frame
  self.patches=[patch('time.monotonic',side_effect=lambda:self.t),patch('auto_operator.require_sanma_observable_frame'),patch('sanma_friend_pass_experiment.require_sanma_observable_frame'),patch('sanma_friend_riichi_experiment.require_sanma_observable_frame'),patch('auto_operator.friend_frame_stable',return_value=True),patch('sanma_friend_pass_experiment.friend_frame_stable',return_value=True),patch('sanma_friend_riichi_experiment.friend_frame_stable',return_value=True),patch('auto_operator.classify_screen',return_value=('match',1)),patch('sanma_friend_pass_experiment.classify_screen',return_value=('match',1))]
  for p in self.patches: p.start();self.addCleanup(p.stop)
 def receipt(self, action):
  slots=[{'slot':0,'status':'empty_candidate'}, {'slot':1,'status':'candidate','action':action,'confidence':1.}, {'slot':2,'status':'candidate','action':'skip','confidence':1.}]
  report={'digest':self.digest,'buttonRow':{'status':'candidate','value':{'slots':slots,'ronReferenceCompared':True}},'hand':{'status':'candidate','value':{'tiles':['N']+['1m']*13}}}
  r={'scope':'sanma_self_turn_observation','status':'blocked','operationAuthorized':False,'digest':self.digest,'captureStartedMonotonic':100.,'screenshot':str(self.path),'freshness':{'status':'identical_pixels_candidate','operationAuthorized':False,'elapsedMs':1},'sourceObservation':{'digest':self.digest,'operationAuthorized':False,'report':report},'candidates':{'candidates':[{'action':action}]}}
  self.op._sanma_friend_discard_observation=(r,self.digest,100.)
  return r
 def run_action(self, action, receipt):
  if action=='pon': return execute_friend_pon_pass(self.op,self.page,receipt)
  return getattr(self.op,'execute_sanma_friend_'+action+'_candidate')(self.page,receipt)
 def test_valid_and_expired_each_single_action(self):
  for action in ('pon','kita','ron','tsumo'):
   for expired in (False,True):
    with self.subTest(action=action,expired=expired):
     self.setUp();r=self.receipt(action);self.t=108 if expired else 101
     if expired:
      with self.assertRaisesRegex(RuntimeError,'budget expired'):self.run_action(action,r)
      self.page.mouse.click.assert_not_called();self.assertFalse(getattr(self.op,'_sanma_friend_attempted_frames',set()))
     else:
      self.run_action(action,r);self.page.mouse.click.assert_called_once()
 def test_slow_capture_and_log_stop_before_click(self):
  for action in ('pon','kita','ron','tsumo'):
   for phase in ('capture','log'):
    with self.subTest(action=action,phase=phase):
     self.setUp();r=self.receipt(action);self.t=101
     if phase=='capture':
      def capture(**kw): self.t=108;return self.frame
      self.page.screenshot.side_effect=capture
     else:
      def log(name,**kw):
       if name=='sanma_friend_candidate_click':self.t=108
      self.op.log.side_effect=log
     with self.assertRaises(RuntimeError):self.run_action(action,r)
     self.page.mouse.click.assert_not_called()
 def test_ron_priority_rejects_pass(self):
  r=self.receipt('pon');slots=r['sourceObservation']['report']['buttonRow']['value']['slots'];slots[0].update(status='candidate',action='ron',confidence=1.)
  with self.assertRaisesRegex(RuntimeError,'ambiguous'):execute_friend_pon_pass(self.op,self.page,r)
  self.page.mouse.click.assert_not_called()
 def test_riichi_timeout_after_declaration_keeps_lock(self):
  r=self.receipt('riichi');self.t=101
  def delay(_):self.t=108
  self.page.wait_for_timeout.side_effect=delay
  with patch('sanma_friend_riichi_experiment.choose_riichi_selection',return_value=0),patch('sanma_friend_riichi_experiment.riichi_bright_slots',return_value=[0]):
   with self.assertRaisesRegex(RuntimeError,'budget expired'):execute_friend_riichi(self.op,self.page,r)
  self.page.mouse.click.assert_called_once_with(1010,830)
  self.assertTrue(self.op.sanma_friend_riichi_attempted)
 def test_riichi_timeout_after_selection_keeps_uncertain_state(self):
  r=self.receipt('riichi');self.t=101
  def capture(**kw):
   if self.page.screenshot.call_count == 4:self.t=108
   return self.frame
  self.page.screenshot.side_effect=capture
  with patch('sanma_friend_riichi_experiment.choose_riichi_selection',return_value=0),patch('sanma_friend_riichi_experiment.riichi_bright_slots',return_value=[0]):
   with self.assertRaises(SelectionStateUncertainAbort):execute_friend_riichi(self.op,self.page,r)
  self.assertEqual(self.page.mouse.click.call_count,2)
  self.assertTrue(self.op.sanma_friend_riichi_attempted)
