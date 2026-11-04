import copy,json,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sanma_friend_pass_experiment import execute_friend_pon_pass,PassPreclickChanged,pass_was_not_sent,may_reobserve_unsent_pass
from sanma_friend_pon_stability import pon_pass_stability

F=Path('/home/yama1/server/data/dev-work/jantama/evidence165/artifacts/frames')
@unittest.skipUnless(F.exists(),'retained evidence unavailable')
class PassPreclick165(unittest.TestCase):
 def setUp(self):
  self.before=next(F.glob('*00-23-48*sanma-self-turn.png'))
  self.fresh=next(F.glob('*00-23-52*sanma-freshness.png'))
  self.stop=next(F.glob('*00-23-54*sanma-friend-stop.png'))
  self.receipt=json.loads(Path(str(self.before).replace('.png','.receipt.json')).read_text())
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.op=Mock();self.op.args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False,experimental_sanma_friend=True)
  self.op.verified_friend_300_active=True;self.op.verified_friend_300_started_at=time.monotonic();self.op._sanma_friend_resume_guard=None;self.op._sanma_friend_attempted_targets=set();self.op.frames=Path(self.temp.name)
  self.page=Mock();self.page.screenshot.return_value=self.stop.read_bytes()
 def test_recorded_stop_frame_is_diagnostic_only_and_safe_to_reobserve(self):
  with self.assertRaises(PassPreclickChanged) as e:execute_friend_pon_pass(self.op,self.page,self.receipt)
  self.assertTrue(pass_was_not_sent(e.exception));self.page.mouse.click.assert_not_called()
  call=next(c for c in self.op.log.call_args_list if c.args[0]=='sanma_friend_pass_preclick_rejected')
  self.assertEqual(Path(call.kwargs['screenshot']).read_bytes(),self.stop.read_bytes())
  self.assertEqual(call.kwargs['diagnostic']['stage'],'pon_row');self.assertEqual(call.kwargs['diagnostic']['blockX'],912)
  watch=Mock();watch.alive.return_value=True
  self.assertTrue(may_reobserve_unsent_pass(e.exception,1,watch,True,100,101))
  for failures,alive,active,now in ((30,True,True,101),(1,False,True,101),(1,True,False,101),(1,True,True,400)):
   watch.alive.return_value=alive
   self.assertFalse(may_reobserve_unsent_pass(e.exception,failures,watch,active,100,now))
 def test_saved_observation_pair_is_accepted_but_unrelated_row_rejected(self):
  report=self.receipt['sourceObservation']['report']
  self.assertTrue(pon_pass_stability(self.before.read_bytes(),self.fresh.read_bytes(),report))
  r=copy.deepcopy(report);r['buttonRow']['value']['slots'][1]['action']='ron'
  self.assertFalse(pon_pass_stability(self.before.read_bytes(),self.fresh.read_bytes(),r))
 def test_evidence_failure_is_not_retryable(self):
  self.op.frames=Path(self.temp.name)/'absent'
  with self.assertRaises(RuntimeError) as e:execute_friend_pon_pass(self.op,self.page,self.receipt)
  self.assertFalse(pass_was_not_sent(e.exception));self.page.mouse.click.assert_not_called()
 def test_input_exception_is_not_retryable(self):
  self.page.screenshot.return_value=self.fresh.read_bytes()
  self.page.mouse.click.side_effect=PassPreclickChanged('input uncertain')
  with patch('sanma_friend_pass_experiment.classify_screen',return_value=('match',1)):
   with self.assertRaises(PassPreclickChanged) as e:execute_friend_pon_pass(self.op,self.page,self.receipt)
  self.assertFalse(pass_was_not_sent(e.exception));self.page.mouse.click.assert_called_once()
 def test_expired_deadline_and_ranked_refused(self):
  for reason in ('deadline','ranked'):
   if reason=='deadline':self.op.verified_friend_300_started_at=time.monotonic()-301
   else:self.op.verified_friend_300_started_at=time.monotonic();self.op.args.ranked_loop=True
   with self.subTest(reason=reason),self.assertRaises(RuntimeError):execute_friend_pon_pass(self.op,self.page,self.receipt)
   self.page.mouse.click.assert_not_called()
