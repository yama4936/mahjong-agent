import copy
import json
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from sanma_intermediate_diagnostic import record

ROOT=Path('/home/yama1/server/data/dev-work/jantama/evidence172/artifacts/frames')
@unittest.skipUnless(ROOT.exists(), 'saved evidence172 unavailable')
class IntermediateDiagnosticTest(unittest.TestCase):
    def setUp(self):
        p=next(ROOT.glob('*04-39-42.276*.receipt.json'))
        self.receipt=json.loads(p.read_text())
        self.op=Mock(); self.op.args.action_deadline_ms=300000;self.op.verified_friend_300_active=True
        self.watch=Mock();self.watch.alive.return_value=True
        self.recovery={'watch':self.watch,'started':100.,'selected_monotonic':101.,'before':{'digest':'old'}}
    def invoke(self,receipt=None,observed_at=102.,now=lambda:103.):
        return record(self.op,self.recovery,receipt or self.receipt,observed_at,now=now)
    def test_saved_pon_image_is_attributed_without_authorization(self):
        self.assertIsNone(self.invoke())
        self.assertEqual(self.op.log.call_args.args[0],'sanma_friend_discard_intermediate_evidence')
        self.assertFalse(self.op.log.call_args.kwargs['operationAuthorized'])
        self.assertEqual(self.op.log.call_args.kwargs['digest'],self.receipt['digest'])
        self.op.execute_sanma_friend_discard_candidate.assert_not_called()
    def test_monitor_deadline_order_and_tamper_fail_closed(self):
        for case in ('monitor','deadline','revoked','order','digest','expired','receipt'):
            self.setUp();r=copy.deepcopy(self.receipt);at=102.; now=lambda:103.
            if case=='monitor': self.watch.alive.return_value=False
            if case=='deadline': self.op.args.action_deadline_ms=8000
            if case=='revoked': self.op.verified_friend_300_active=False
            if case=='order': at=100.
            if case=='digest': r['digest']='0'*64
            if case=='receipt': r['screenshot']='/nonexistent/evidence.png'
            if case=='expired': now=lambda:400.
            self.assertIsNone(self.invoke(r,at,now));self.op.log.assert_not_called()
    def test_monitor_failure_during_check_is_nonfatal(self):
        self.watch.alive.side_effect=[True,False]
        self.assertIsNone(self.invoke()); self.op.log.assert_not_called()
