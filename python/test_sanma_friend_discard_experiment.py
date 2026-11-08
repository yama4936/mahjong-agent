import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sanma_friend_discard_experiment import execute_friend_discard, execute_friend_draw_candidate, DiscardPreclickChanged


class FriendDiscardExperimentTests(unittest.TestCase):
    def setUp(self):
        import io
        from PIL import Image
        output=io.BytesIO();Image.new("RGB",(1920,1080),(20,30,60)).save(output,format="PNG")
        self.frame = output.getvalue()
        self.page = Mock()
        self.page.screenshot.return_value = self.frame
        self.session = {"mode": "cpu_friend", "rules": "sanma", "clock": "300+0",
                        "actionDeadlineMs": 300000, "ranked": False, "cpuCount": 2, "roomVerified": True}
        self.point = {"x": 200, "y": 1000}
        self.observation = {"status": "candidate", "phase": "self_turn", "promptStatus": "none",
                            "handStatus": "candidate", "layoutStatus": "candidate",
                            "slots": [{"tile": "1m", **self.point}],
                            "frameSha256": hashlib.sha256(self.frame).hexdigest()}
        self.plan = {"scope": "offline_untrusted_sanma_discard_plan", "operationAuthorized": False,
                     "tile": "1m", "clickIndex": 0, "clickPoint": self.point}
        self.logs = []
        self.kwargs = dict(session=self.session, observation=self.observation, plan=self.plan,
                           layout={"viewport": {"width": 1920, "height": 1080},
                                   "handSlots":[{"x":220+94*i,"y":921,"width":93,"height":151} for i in range(13)],
                                   "drawSlot":{"x":1485,"y":921,"width":93,"height":151}}, log=self.logs.append,
                           turn_started_monotonic=100, clock=lambda: 101)

    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_dispatches_selected_slot_and_records_unverified_result(self, send):
        send.return_value = {"lift": 48}
        result = execute_friend_discard(self.page, **self.kwargs)
        self.assertEqual(send.call_args.args[1], self.point)
        self.assertEqual([item["status"] for item in self.logs], ["attempted", "selection_confirmed"])
        self.assertEqual(result["result"], "discard_not_verified")

    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_revoked_friend_session_stops_before_click(self, send):
        with self.assertRaisesRegex(RuntimeError, 'friend session revoked'):
            execute_friend_discard(self.page, **{**self.kwargs, 'session_check': lambda: False})
        send.assert_not_called()

    @patch('auto_operator.experimental_draw_glyph_stability')
    @patch('sanma_friend_discard_experiment.friend_frame_stable', return_value=False)
    @patch('sanma_friend_discard_experiment.send_discard_click')
    def test_preclick_rejection_records_guard_stage_and_position(self, send, stable, glyph):
        def reject(*args, diagnostic, **kwargs):
            diagnostic.update(stage='binary_frame', blockX=320, blockY=96, changedPixels=21, threshold=14)
            return False
        glyph.side_effect = reject
        self.page.screenshot.return_value = self.frame + b'changed'
        observation = {**self.observation, 'referenceFrame': self.frame, 'experimentalDrawReport': {}}
        saved = Mock()
        with self.assertRaises(DiscardPreclickChanged):
            execute_friend_discard(self.page, **{**self.kwargs, 'observation': observation,
                                               'save_rejected_frame': saved})
        self.assertEqual(self.logs[-1]['preclickDiagnostic'], {
            'stage': 'binary_frame', 'blockX': 320, 'blockY': 96, 'changedPixels': 21, 'threshold': 14})
        saved.assert_called_once()
        send.assert_not_called()

    @patch('sanma_friend_discard_experiment.send_discard_click')
    def test_invalid_reference_records_identity_failure_without_click(self, send):
        self.page.screenshot.return_value = self.frame + b'changed'
        observation = {**self.observation, 'referenceFrame': b'wrong'}
        with self.assertRaises(DiscardPreclickChanged):
            execute_friend_discard(self.page, **{**self.kwargs, 'observation': observation})
        self.assertEqual(self.logs[-1]['preclickDiagnostic'], {'stage': 'frame_identity'})
        send.assert_not_called()

    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_ambiguous_prompts_ranked_changed_frame_and_expired_turn_are_blocked(self, send):
        variants = [dict(observation={**self.observation, "promptStatus": "unknown"}),
                    dict(session={**self.session, "ranked": True}),
                    dict(observation={**self.observation, "frameSha256": "0" * 64}),
                    dict(clock=lambda: 401),
                    dict(plan={**self.plan, "tile": "9m"})]
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                execute_friend_discard(self.page, **{**self.kwargs, **variant})
        send.assert_not_called()

    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_cd82_lighting_change_accepted_but_draw_change_rejected(self, send):
        import glob, io, json
        from PIL import Image
        root = Path('/home/yama1/.codex/sanma-run-cd82c23-20261101/run/frames')
        source = glob.glob(str(root / '*15-13-52*sanma-self-turn.png'))
        rejected = glob.glob(str(root / '*sanma-discard-preclick-rejected.png'))
        report_path = Path(__file__).parent/'fixtures'/'sanma-cd82-discard-report.json'
        if not source or not rejected or not report_path.exists(): self.skipTest('saved frames or replay unavailable')
        reference=Path(source[0]).read_bytes(); self.page.screenshot.return_value=Path(rejected[0]).read_bytes()
        report=json.loads(report_path.read_text())
        observation={**self.observation,'frameSha256':hashlib.sha256(reference).hexdigest(),
                     'referenceFrame':reference,'experimentalDrawReport':report}
        # Both retained frames show the same hand and board; the clock and
        # illumination differ. A true draw change must still stop before input.
        latch=Mock(); saved=Mock()
        send.return_value = {"lift": 48}
        execute_friend_discard(self.page,**{**self.kwargs,'observation':observation,'before_click':latch,'save_rejected_frame':saved})
        latch.assert_called_once(); send.assert_called_once(); saved.assert_not_called()
        latch.reset_mock(); send.reset_mock()
        changed = Image.open(io.BytesIO(self.page.screenshot.return_value)).convert('RGB')
        # Replace drawn south with the adjacent west, leaving all other pixels.
        changed.paste(changed.crop((1360, 922, 1453, 1073)), (1485, 922))
        output=io.BytesIO(); changed.save(output, format='PNG')
        self.page.screenshot.return_value=output.getvalue()
        with self.assertRaises(DiscardPreclickChanged):
            execute_friend_discard(self.page,**{**self.kwargs,'observation':observation,'before_click':latch,'save_rejected_frame':saved})
        saved.assert_called_once_with(self.page.screenshot.return_value)
        latch.assert_not_called();send.assert_not_called()

    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_latch_runs_only_after_matching_frame_and_before_input(self, send):
        order=[]
        send.side_effect=lambda *a,**k: order.append('click') or {}
        execute_friend_discard(self.page,**{**self.kwargs,'before_click':lambda:order.append('latch')})
        self.assertEqual(order,['latch','click'])

    @patch("sanma_friend_discard_experiment.send_discard_click", side_effect=DiscardPreclickChanged('input uncertain'))
    def test_preclick_exception_from_input_is_not_retryable(self, send):
        with self.assertRaises(RuntimeError) as error:
            execute_friend_discard(self.page,**self.kwargs)
        self.assertNotIsInstance(error.exception, DiscardPreclickChanged)
        self.assertEqual(self.logs[-1]['status'],'failed')

    @patch("sanma_friend_discard_experiment.send_discard_click", side_effect=RuntimeError('input uncertain'))
    def test_same_exception_from_failure_logger_does_not_trigger_retry(self, send):
        logger=Mock(side_effect=[None,DiscardPreclickChanged('logger failure')])
        with self.assertRaises(RuntimeError) as error:
            execute_friend_discard(self.page,**{**self.kwargs,'log':logger})
        self.assertNotIsInstance(error.exception,DiscardPreclickChanged)
        send.assert_called_once()

    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_deadline_expiring_during_attempt_log_prevents_selection(self, send):
        now = [101.0]
        def log(event):
            if event["status"] == "attempted":
                now[0] = 401.0
        with self.assertRaisesRegex(RuntimeError, "action deadline expired"):
            execute_friend_discard(self.page, **{**self.kwargs, "clock": lambda: now[0], "log": log})
        send.assert_not_called()

    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_session_revoked_during_attempt_log_prevents_selection(self, send):
        active = [True]
        def log(event):
            if event["status"] == "attempted":
                active[0] = False
        with self.assertRaisesRegex(RuntimeError, "friend session revoked"):
            execute_friend_discard(self.page, **{**self.kwargs, "session_check": lambda: active[0], "log": log})
        send.assert_not_called()

    @patch("sanma_friend_discard_experiment.send_discard_click", side_effect=RuntimeError("selection uncertain"))
    def test_failed_selection_is_logged_and_propagated(self, send):
        with self.assertRaisesRegex(RuntimeError, "selection uncertain"):
            execute_friend_discard(self.page, **self.kwargs)
        self.assertEqual(self.logs[-1]["status"], "failed")
        self.assertEqual(self.logs[-1]["result"], "discard_not_verified")


if __name__ == "__main__":
    unittest.main()


class FriendRaisedInspectionFailureTests(FriendDiscardExperimentTests):
    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_missing_invalid_geometry_and_internal_exception_fail_closed(self, send):
        import copy
        layouts=[]
        layouts.append({"viewport":{"width":1920,"height":1080}})
        bad=copy.deepcopy(self.kwargs['layout']);bad['drawSlot']['width']=0;layouts.append(bad)
        bad=copy.deepcopy(self.kwargs['layout']);bad['handSlots'][0]['x']=float('nan');layouts.append(bad)
        bad=copy.deepcopy(self.kwargs['layout']);bad['handSlots'][1]['x']=bad['handSlots'][0]['x'];layouts.append(bad)
        for layout in layouts:
            with self.subTest(layout=layout), self.assertRaises((ValueError,TypeError,KeyError)):
                execute_friend_discard(self.page,**{**self.kwargs,'layout':layout})
            send.assert_not_called()
        with patch('auto_operator.raised_closed_hand_slots',side_effect=RuntimeError('inspection failed')):
            with self.assertRaisesRegex(RuntimeError,'inspection failed'):
                execute_friend_discard(self.page,**self.kwargs)
        send.assert_not_called()


class FriendDrawBridgeTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        self.operator = Mock()
        self.operator.args = SimpleNamespace(experimental_sanma_friend=True, rules="sanma", mode="force-auto",
                                             action_deadline_ms=300000, ranked_loop=False)
        self.operator.verified_friend_300_active = True
        self.operator.verified_friend_300_started_at = 100
        self.point = {"x": 1000, "y": 1000}
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        baseline = Path(self.directory.name) / "baseline.png"
        from PIL import Image
        Image.new("RGB", (1920, 1080)).save(baseline)
        digest = hashlib.sha256(baseline.read_bytes()).hexdigest()
        self.receipt = {"scope": "sanma_self_turn_observation", "digest": digest, "screenshot": str(baseline),
                        "freshness": {"status": "identical_pixels_candidate"},
                        "drawCandidate": {"status": "candidate", "digest": digest, "index": 13,
                                          "tile": "1m", "point": self.point},
                        "sourceObservation": {"digest": digest, "report": {"digest": digest,
                            "hand": {"status": "candidate", "value": {"safe": True, "turnReady": True, "tiles": ["1m"] * 14}},
                            "handGeometry": {"status": "candidate", "value": {"clickPoints": [self.point] * 14}},
                            "buttonRow": {"status": "candidate", "value": {"slots": [{"status": "empty_candidate"}] * 3}}}}}

    @patch("sanma_friend_discard_experiment.execute_friend_discard")
    def test_uses_draw_candidate_and_friend_config(self, execute):
        execute_friend_draw_candidate(self.operator, Mock(), self.receipt)
        self.assertEqual(execute.call_args.kwargs["plan"]["clickPoint"], self.point)
        self.assertEqual(execute.call_args.kwargs["plan"]["tile"], "1m")
        self.assertEqual(execute.call_args.kwargs["turn_started_monotonic"], 100)
        event = next(c for c in self.operator.log.call_args_list if c.args[0] == 'sanma_friend_shape_candidate')
        self.assertEqual(event.kwargs['selectedPlan'], execute.call_args.kwargs['plan'])
        self.assertEqual(event.kwargs['sourceDigest'], self.receipt['digest'])

    @patch("sanma_friend_discard_experiment.execute_friend_discard")
    def test_prompt_or_ranked_never_dispatches(self, execute):
        self.receipt["sourceObservation"]["report"]["buttonRow"]["value"]["slots"][0] = {"status": "unresolved"}
        with self.assertRaises(ValueError):
            execute_friend_draw_candidate(self.operator, Mock(), self.receipt)
        self.operator.args.ranked_loop = True
        with self.assertRaises(ValueError):
            execute_friend_draw_candidate(self.operator, Mock(), self.receipt)
        execute.assert_not_called()

    @patch('sanma_friend_discard_experiment.latch_friend_action_target')
    @patch('sanma_friend_discard_experiment.send_discard_click')
    def test_bridge_saves_exact_rejected_capture_and_stops(self, send, latch):
        import time
        from PIL import Image
        self.operator.frames=Path(self.directory.name)
        self.operator.verified_friend_300_started_at=time.monotonic()
        changed=Path(self.directory.name)/'changed.png'
        Image.new('RGB',(1920,1080),(120,120,120)).save(changed)
        page=Mock();page.screenshot.return_value=changed.read_bytes()
        with self.assertRaisesRegex(ValueError,'recognition frame changed before click'):
            execute_friend_draw_candidate(self.operator,page,self.receipt)
        event=next(c for c in self.operator.log.call_args_list if c.args[0]=='sanma_friend_discard_preclick_rejected')
        self.assertEqual(Path(event.kwargs['screenshot']).read_bytes(),changed.read_bytes())
        self.assertEqual(event.kwargs['sha256'],hashlib.sha256(changed.read_bytes()).hexdigest())
        self.assertEqual(event.kwargs['referenceSha256'],self.receipt['digest'])
        send.assert_not_called()
        latch.assert_not_called()

    @patch('sanma_friend_discard_experiment.latch_friend_action_target')
    @patch('sanma_friend_discard_experiment.send_discard_click')
    def test_bridge_evidence_write_failure_stops_before_click(self, send, latch):
        import time
        from PIL import Image
        self.operator.frames=Path(self.directory.name)/'missing'
        self.operator.verified_friend_300_started_at=time.monotonic()
        changed=Path(self.directory.name)/'changed.png'
        Image.new('RGB',(1920,1080),(120,120,120)).save(changed)
        page=Mock();page.screenshot.return_value=changed.read_bytes()
        with self.assertRaisesRegex(ValueError,'recognition frame changed before click') as error:
            execute_friend_draw_candidate(self.operator,page,self.receipt)
        self.assertNotIsInstance(error.exception, DiscardPreclickChanged)
        latch.assert_not_called()
        event=next(c for c in self.operator.log.call_args_list
                   if c.args[0]=='sanma_friend_discard_experiment' and c.kwargs.get('error'))
        self.assertEqual(event.kwargs['error'],'recognition frame changed before click')
        self.assertIn('FileNotFoundError',event.kwargs['evidenceSaveError'])
        send.assert_not_called()
