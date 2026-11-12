import copy,json,time,unittest,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sanma_friend_pass_experiment import execute_friend_pon_pass
ROOT=Path('/home/yama1/server/data/dev-work/jantama/evidence182/retry2-artifacts')
@unittest.skipUnless(ROOT.exists(),'retained 182 evidence unavailable')
class Integration(unittest.TestCase):
 def setUp(self):
  events=[e for e in map(json.loads,(ROOT/'python-operator.jsonl').read_text().splitlines()) if e.get('event')=='sanma_self_turn_observed'];self.receipt=json.loads(Path(events[0]['receiptPath']).read_text())
  self.op=Mock();self.op.args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False,experimental_sanma_friend=True,experimental_sanma_pon_monitor=True)
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.op.frames=Path(temp.name)
  self.op.verified_friend_300_active=True;self.op.sanma_friend_action_observed_at=time.monotonic();self.op._sanma_friend_attempted_targets=set();self.op._sanma_friend_resume_guard=None
  self.op.force_auto_click_budget_ms.return_value=8000
  self.receipt['captureStartedMonotonic']=time.monotonic()
  self.op._sanma_friend_discard_observation=(self.receipt,self.receipt['digest'],self.receipt['captureStartedMonotonic'])
  self.page=Mock();self.page.screenshot.return_value=Path(self.receipt['freshness']['screenshot']).read_bytes();self.monitor=Mock();self.monitor.matches.return_value=True
 def call(self):
  with patch('sanma_friend_pass_experiment.classify_screen',return_value=('match',1)):
   return execute_friend_pon_pass(self.op,self.page,self.receipt,pon_monitor=self.monitor)
 def test_enabled_click_once_then_never_repeat(self):
  self.call();self.page.mouse.click.assert_called_once_with(1300,830)
  with self.assertRaises(RuntimeError):self.call()
  self.page.mouse.click.assert_called_once()
 def test_reject_unenabled_revoked_expired_or_unsafe_monitor(self):
  for mode in ('unenabled','revoked','expired','unsafe'):
   with self.subTest(mode=mode):
    self.setUp()
    if mode=='unenabled':self.op.args.experimental_sanma_pon_monitor=False
    if mode=='revoked':self.op.verified_friend_300_active=False
    if mode=='expired':self.op.sanma_friend_action_observed_at=time.monotonic()-301
    if mode=='unsafe':self.monitor.matches.return_value=False
    with self.assertRaises(RuntimeError):self.call()
    self.page.mouse.click.assert_not_called()
