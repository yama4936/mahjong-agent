import hashlib, json, time, unittest
from pathlib import Path
from unittest.mock import Mock
from test_sanma_wall_guard_diagnostics import WallGuardIntegration

class ClassifiedFrameReuse(WallGuardIntegration):
 def evidence(self, path):
  path=Path(path)
  if not path.is_file(): self.skipTest(f'optional local evidence unavailable: {path}')
  return path.read_bytes()
 def prepare(self, frame):
  digest=hashlib.sha256(frame).hexdigest(); self.report['digest']=digest
  result={'assembly':{'operationAuthorized':False,'priority':{'status':'blocked'},'evaluation':{'status':'blocked'}},'digest':digest,'report':self.report,'structuralPositions':{'status':'blocked','operationAuthorized':False,'digest':digest,'candidates':[]}}
  self.op.observe_sanma_resident=Mock(return_value=result)
 def test_saved_image_reuses_exact_bytes_but_still_captures_fresh(self):
  source=self.evidence('/home/yama1/server/data/dev-work/jantama/evidence173/artifacts/frames/2026-11-04T05-22-17.749993+00-00.420d5d77b53b4885a47362379d2439ba.sanma-self-turn.png')
  self.prepare(source);self.page.screenshot.return_value=source
  r=self.op.inspect_sanma_self_turn(self.page,classified_frame=source,classified_started=time.monotonic())
  self.assertEqual(r['digest'],hashlib.sha256(source).hexdigest());self.assertEqual(self.page.screenshot.call_count,1);self.assertFalse(r['operationAuthorized'])
 def test_reject_stale_future_unverified_and_bad_frame(self):
  self.prepare(self.frame)
  for frame,stamp,verified in [(self.frame,time.monotonic()-4,True),(self.frame,time.monotonic()+1,True),(self.frame,time.monotonic(),False),(b'',time.monotonic(),True)]:
   self.op.verified_friend_300_active=verified
   with self.assertRaises(RuntimeError):self.op.inspect_sanma_self_turn(self.page,classified_frame=frame,classified_started=stamp)
   self.page.screenshot.assert_not_called()
 def test_freshness_change_remains_fail_closed(self):
  self.prepare(self.frame)
  source=self.frame
  other=self.evidence('/home/yama1/server/data/dev-work/jantama/evidence173/artifacts/frames/2026-11-04T05-22-17.749993+00-00.420d5d77b53b4885a47362379d2439ba.sanma-self-turn.png')
  self.page.screenshot.return_value=other
  r=self.op.inspect_sanma_self_turn(self.page,classified_frame=source,classified_started=time.monotonic())
  self.assertIn(r['freshness']['status'],('changed','unknown'));self.assertFalse(r['freshness']['operationAuthorized']);self.page.mouse.click.assert_not_called()
 def test_saved_real_transition_does_not_become_authorized(self):
  root=Path('/home/yama1/server/data/dev-work/jantama/evidence172')
  initial=self.evidence(root/'transitions/ff8da6037a8e451680719ae61a080f5a/05.png')
  later=self.evidence(root/'artifacts/frames/2026-11-04T04-39-47.411428+00-00.06207a22446b404c8e61133cdda8ff16.sanma-self-turn.png')
  self.prepare(initial);self.page.screenshot.return_value=later
  r=self.op.inspect_sanma_self_turn(self.page,classified_frame=initial,classified_started=time.monotonic())
  self.assertIn(r['freshness']['status'],('changed','unknown'));self.assertFalse(r['operationAuthorized']);self.page.mouse.click.assert_not_called()
