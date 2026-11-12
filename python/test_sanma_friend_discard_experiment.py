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


class FriendDiscardBaselineRefreshTests(unittest.TestCase):
    """Fix B (timing): a verified fresh capture may replace the aged reference.

    The reference below is seconds old by preclick time; only animation in
    the wall seam differs. Adoption still requires the hand faces to match
    the reference and an immediate confirmation capture to match the new
    baseline under the same stability chain.
    """

    def setUp(self):
        import io
        from PIL import Image, ImageDraw

        def frame(patches=()):
            image = Image.new("RGB", (1920, 1080), (190, 195, 205))
            draw = ImageDraw.Draw(image)
            for box in patches:
                draw.rectangle(box, fill=(5, 5, 5))
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()

        self.frame = frame
        self.reference = frame()
        # Animation-only drift confined to one left-wall seam block.
        self.candidate = frame([(320, 96, 351, 127)])
        # The same candidate one capture later; only the clock area moved.
        self.confirmation = frame([(320, 96, 351, 127), (1500, 800, 1531, 831)])
        self.page = Mock()
        self.session = {"mode": "cpu_friend", "rules": "sanma", "clock": "300+0",
                        "actionDeadlineMs": 300000, "ranked": False, "cpuCount": 2, "roomVerified": True}
        self.point = {"x": 200, "y": 1000}
        hand_slots = [{"x": 220 + 94 * i, "y": 921, "width": 93, "height": 151} for i in range(13)]
        draw_slot = {"x": 1485, "y": 921, "width": 93, "height": 151}
        report = {"handGeometry": {"value": {"handSlots": hand_slots, "drawSlot": draw_slot}}}
        self.observation = {"status": "candidate", "phase": "self_turn", "promptStatus": "none",
                            "handStatus": "candidate", "layoutStatus": "candidate",
                            "slots": [{"tile": "1m", **self.point}],
                            "frameSha256": hashlib.sha256(self.reference).hexdigest(),
                            "referenceFrame": self.reference, "referenceScreenshot": "original-observation.png",
                            "experimentalDrawReport": report}
        self.plan = {"scope": "offline_untrusted_sanma_discard_plan", "operationAuthorized": False,
                     "tile": "1m", "clickIndex": 0, "clickPoint": self.point}
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.logs = []
        self.kwargs = dict(session=self.session, observation=self.observation, plan=self.plan,
                           layout={"viewport": {"width": 1920, "height": 1080},
                                   "handSlots": hand_slots, "drawSlot": draw_slot},
                           log=self.logs.append, turn_started_monotonic=100, clock=lambda: 101,
                           evidence_directory=self.directory.name)

    @staticmethod
    def _fail_at_binary_frame(diagnostic):
        diagnostic.update(stage='binary_frame', blockX=320, blockY=96, changedPixels=1024, threshold=14)
        return False

    @patch('sanma_friend_self_turn_stability.self_turn_stability', return_value=False)
    @patch('auto_operator.raised_closed_hand_slots', return_value=[])
    @patch('auto_operator.closed_hand_face_mismatches', return_value=[])
    @patch('auto_operator.experimental_draw_glyph_stability')
    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_verified_candidate_becomes_baseline_and_click_proceeds(self, send, glyph, faces, raised, wall_gate):
        def stability(before, after, report, diagnostic=None, **kwargs):
            if before == self.reference:
                return self._fail_at_binary_frame(diagnostic)
            return True
        glyph.side_effect = stability
        send.return_value = {"lift": 48}
        self.page.screenshot.side_effect = [self.candidate, self.confirmation]
        result = execute_friend_discard(self.page, **self.kwargs)
        send.assert_called_once()
        self.assertEqual(result["status"], "selection_confirmed")
        self.assertEqual(result["frameSha256"], hashlib.sha256(self.reference).hexdigest())
        self.assertIs(result["baselineRefreshed"], True)
        self.assertEqual(result["baselineSha256"], hashlib.sha256(self.candidate).hexdigest())
        refreshed = next(item for item in self.logs if item.get("kind") == "sanma_discard_baseline_refreshed")
        self.assertEqual(refreshed["baselineSha256"], hashlib.sha256(self.candidate).hexdigest())
        self.assertEqual(refreshed["confirmationSha256"], hashlib.sha256(self.confirmation).hexdigest())
        self.assertEqual(refreshed["baselineCapturedAtMonotonic"], 101)
        self.assertEqual(result["refreshId"], refreshed["refreshId"])
        for role, original in (("reference", self.reference), ("candidate", self.candidate),
                               ("confirmation", self.confirmation)):
            evidence = refreshed["evidence"][role]
            self.assertEqual(Path(evidence["screenshot"]).read_bytes(), original)
            self.assertEqual(evidence["sha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual(evidence["byteLength"], len(original))
            self.assertGreater(evidence["savedAtUnix"], 0)
            if role == "reference":
                self.assertEqual(evidence["sourceScreenshot"], "original-observation.png")
                self.assertIsNone(evidence["capturedAtMonotonic"])
                self.assertIsNone(evidence["capturedAtUnix"])
            else:
                self.assertEqual(evidence["capturedAtMonotonic"], 101)
                self.assertLessEqual(evidence["capturedAtUnix"], evidence["savedAtUnix"])

    @patch('sanma_friend_self_turn_stability.self_turn_stability', return_value=True)
    @patch('auto_operator.raised_closed_hand_slots', return_value=[])
    @patch('auto_operator.closed_hand_face_mismatches', return_value=[])
    @patch('auto_operator.experimental_draw_glyph_stability')
    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_pair_explained_by_opt_in_wall_hypothesis_is_not_refreshed(self, send, glyph, faces, raised, wall_gate):
        def stability(before, after, report, diagnostic=None, **kwargs):
            return self._fail_at_binary_frame(diagnostic)
        glyph.side_effect = stability
        self.page.screenshot.side_effect = [self.candidate, self.confirmation]
        with self.assertRaises(DiscardPreclickChanged):
            execute_friend_discard(self.page, **self.kwargs)
        send.assert_not_called()
        self.assertEqual(self.page.screenshot.call_count, 1)
        self.assertFalse(any(item.get("kind") == "sanma_discard_baseline_refresh_failed" for item in self.logs))

    @patch('sanma_friend_self_turn_stability.self_turn_stability', return_value=False)
    @patch('auto_operator.raised_closed_hand_slots', return_value=[])
    @patch('auto_operator.closed_hand_face_mismatches', return_value=[])
    @patch('auto_operator.experimental_draw_glyph_stability')
    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_unconfirmed_candidate_is_not_adopted(self, send, glyph, faces, raised, wall_gate):
        unstable = self.frame([(320, 96, 351, 127), (700, 300, 731, 331)])
        def stability(before, after, report, diagnostic=None, **kwargs):
            return self._fail_at_binary_frame(diagnostic)
        glyph.side_effect = stability
        self.page.screenshot.side_effect = [self.candidate, unstable]
        saved = Mock()
        with self.assertRaises(DiscardPreclickChanged):
            execute_friend_discard(self.page, **{**self.kwargs, 'save_rejected_frame': saved})
        send.assert_not_called()
        saved.assert_called_once_with(self.candidate)
        failed = next(item for item in self.logs if item.get("kind") == "sanma_discard_baseline_refresh_failed")
        self.assertEqual(failed["reason"], "candidate baseline not confirmed by immediate capture")
        self.assertEqual(Path(failed["evidence"]["confirmation"]["screenshot"]).read_bytes(), unstable)
        self.assertEqual(failed["evidence"]["confirmation"]["sha256"], hashlib.sha256(unstable).hexdigest())

    @patch('sanma_friend_self_turn_stability.self_turn_stability', return_value=False)
    @patch('auto_operator.raised_closed_hand_slots', return_value=[])
    @patch('auto_operator.closed_hand_face_mismatches', return_value=[{"index": 13, "faceStructureDelta": 0.9}])
    @patch('auto_operator.experimental_draw_glyph_stability')
    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_hand_face_mismatch_blocks_refresh_before_confirmation_capture(self, send, glyph, faces, raised, wall_gate):
        def stability(before, after, report, diagnostic=None, **kwargs):
            return self._fail_at_binary_frame(diagnostic)
        glyph.side_effect = stability
        self.page.screenshot.side_effect = [self.candidate]
        with self.assertRaises(DiscardPreclickChanged):
            execute_friend_discard(self.page, **self.kwargs)
        send.assert_not_called()
        self.assertEqual(self.page.screenshot.call_count, 1)
        failed = next(item for item in self.logs if item.get("kind") == "sanma_discard_baseline_refresh_failed")
        self.assertEqual(failed["reason"], "hand faces differ from reference")

    @patch('sanma_friend_self_turn_stability.self_turn_stability', return_value=False)
    @patch('auto_operator.raised_closed_hand_slots', return_value=[])
    @patch('auto_operator.closed_hand_face_mismatches', return_value=[])
    @patch('auto_operator.experimental_draw_glyph_stability')
    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_binary_change_outside_animation_regions_blocks_refresh(self, send, glyph, faces, raised, wall_gate):
        changed = self.frame([(700, 300, 731, 331)])
        def stability(before, after, report, diagnostic=None, **kwargs):
            return self._fail_at_binary_frame(diagnostic)
        glyph.side_effect = stability
        self.page.screenshot.side_effect = [changed, changed]
        with self.assertRaises(DiscardPreclickChanged):
            execute_friend_discard(self.page, **{**self.kwargs,
                                                'observation': {**self.observation,
                                                                'experimentalDrawReport':
                                                                self.observation['experimentalDrawReport']}})
        send.assert_not_called()
        self.assertEqual(self.page.screenshot.call_count, 1)
        failed = next(item for item in self.logs if item.get("kind") == "sanma_discard_baseline_refresh_failed")
        self.assertEqual(failed["reason"], "binary changes outside wall/centre animation regions")

    @patch('sanma_friend_self_turn_stability.self_turn_stability', return_value=False)
    @patch('auto_operator.raised_closed_hand_slots', return_value=[])
    @patch('auto_operator.closed_hand_face_mismatches', return_value=[])
    @patch('auto_operator.experimental_draw_glyph_stability')
    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_block_straddling_wall_edge_with_pixels_outside_is_not_refreshed(self, send, glyph, faces, raised, wall_gate):
        # Block (128, 96) intersects the wall crop (x >= 150), but every
        # changed pixel sits left of it. Block intersection alone must not
        # confine them (evidence185 boundary review, reproduction 1).
        changed = self.frame([(128, 96, 149, 127)])
        def stability(before, after, report, diagnostic=None, **kwargs):
            return self._fail_at_binary_frame(diagnostic)
        glyph.side_effect = stability
        self.page.screenshot.side_effect = [changed]
        with self.assertRaises(DiscardPreclickChanged):
            execute_friend_discard(self.page, **self.kwargs)
        send.assert_not_called()
        self.assertEqual(self.page.screenshot.call_count, 1)
        failed = next(item for item in self.logs if item.get("kind") == "sanma_discard_baseline_refresh_failed")
        self.assertEqual(failed["reason"], "binary changes outside wall/centre animation regions")
        self.assertIs(failed["binaryChangesConfined"], False)

    @patch('sanma_friend_self_turn_stability.self_turn_stability', return_value=False)
    @patch('auto_operator.raised_closed_hand_slots', return_value=[])
    @patch('auto_operator.closed_hand_face_mismatches', return_value=[])
    @patch('auto_operator.experimental_draw_glyph_stability')
    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_block_straddling_centre_edge_with_pixels_outside_is_not_refreshed(self, send, glyph, faces, raised, wall_gate):
        # Block (896, 352) intersects the centre box (905, 375), but the
        # changed pixels sit left of / above it (evidence185, reproduction 2).
        changed = self.frame([(896, 352, 904, 383)])
        def stability(before, after, report, diagnostic=None, **kwargs):
            return self._fail_at_binary_frame(diagnostic)
        glyph.side_effect = stability
        self.page.screenshot.side_effect = [changed]
        with self.assertRaises(DiscardPreclickChanged):
            execute_friend_discard(self.page, **self.kwargs)
        send.assert_not_called()
        self.assertEqual(self.page.screenshot.call_count, 1)
        failed = next(item for item in self.logs if item.get("kind") == "sanma_discard_baseline_refresh_failed")
        self.assertEqual(failed["reason"], "binary changes outside wall/centre animation regions")
        self.assertIs(failed["binaryChangesConfined"], False)

    @patch('sanma_friend_self_turn_stability.self_turn_stability', return_value=False)
    @patch('auto_operator.raised_closed_hand_slots', return_value=[])
    @patch('auto_operator.closed_hand_face_mismatches', return_value=[])
    @patch('auto_operator.experimental_draw_glyph_stability')
    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_blacked_out_centre_is_not_refreshed_despite_pixel_confinement(self, send, glyph, faces, raised, wall_gate):
        # The whole centre display is blacked out. Its changed pixels are
        # pixel-confined to the centre box, so only the original guard's
        # final centre-structure stage (candidate vs the reference, never
        # candidate vs itself) can reject it (evidence185 synthetic case).
        changed = self.frame([(906, 376, 1008, 463)])
        def stability(before, after, report, diagnostic=None, **kwargs):
            return self._fail_at_binary_frame(diagnostic)
        glyph.side_effect = stability
        self.page.screenshot.side_effect = [changed, changed]
        with self.assertRaises(DiscardPreclickChanged):
            execute_friend_discard(self.page, **self.kwargs)
        send.assert_not_called()
        self.assertEqual(self.page.screenshot.call_count, 1)
        failed = next(item for item in self.logs if item.get("kind") == "sanma_discard_baseline_refresh_failed")
        self.assertEqual(failed["reason"], "centre structure differs from reference")
        self.assertGreater(failed["centreStructureDelta"], .5)
        self.assertIs(failed["binaryChangesConfined"], True)

    @patch('sanma_friend_self_turn_stability.self_turn_stability', return_value=False)
    @patch('auto_operator.raised_closed_hand_slots', return_value=[])
    @patch('auto_operator.closed_hand_face_mismatches', return_value=[])
    @patch('auto_operator.experimental_draw_glyph_stability')
    @patch("sanma_friend_discard_experiment.send_discard_click")
    def test_change_just_inside_wall_right_edge_is_still_refreshed(self, send, glyph, faces, raised, wall_gate):
        # Positive boundary case: every changed pixel is just inside the
        # wall crop's right edge (x <= 389 < 390). Pixel-level confinement
        # and the centre check must not change this adoption.
        candidate = self.frame([(358, 96, 389, 127)])
        confirmation = self.frame([(358, 96, 389, 127), (1500, 800, 1531, 831)])
        def stability(before, after, report, diagnostic=None, **kwargs):
            if before == self.reference:
                return self._fail_at_binary_frame(diagnostic)
            return True
        glyph.side_effect = stability
        send.return_value = {"lift": 48}
        self.page.screenshot.side_effect = [candidate, confirmation]
        result = execute_friend_discard(self.page, **self.kwargs)
        send.assert_called_once()
        self.assertIs(result["baselineRefreshed"], True)
        self.assertEqual(result["baselineSha256"], hashlib.sha256(candidate).hexdigest())
        refreshed = next(item for item in self.logs if item.get("kind") == "sanma_discard_baseline_refreshed")
        self.assertEqual(refreshed["centreStructureDelta"], 0)


class FriendRefreshPersistenceFailureTests(unittest.TestCase):
    setUp = FriendDiscardBaselineRefreshTests.setUp
    _fail_at_binary_frame = staticmethod(FriendDiscardBaselineRefreshTests._fail_at_binary_frame)
    @patch('sanma_friend_self_turn_stability.self_turn_stability', return_value=False)
    @patch('auto_operator.closed_hand_face_mismatches', return_value=[])
    @patch('auto_operator.experimental_draw_glyph_stability')
    @patch('sanma_friend_discard_experiment.send_discard_click')
    def test_save_failures_at_each_capture_prevent_click(self, send, glyph, faces, wall_gate):
        import sanma_friend_discard_experiment as module
        save = module._save_refresh_frame
        glyph.side_effect = lambda *a, diagnostic=None, **kw: self._fail_at_binary_frame(diagnostic)
        for failed_role in ('reference', 'candidate', 'confirmation'):
            self.logs.clear()
            self.page.screenshot.side_effect = [self.candidate, self.confirmation]
            def save_or_fail(directory, refresh_id, role, frame, **kwargs):
                if role == failed_role:
                    raise OSError('simulated full evidence disk')
                return save(directory, refresh_id, role, frame, **kwargs)
            with self.subTest(role=failed_role), patch.object(module, '_save_refresh_frame', side_effect=save_or_fail):
                with self.assertRaises(DiscardPreclickChanged):
                    execute_friend_discard(self.page, **self.kwargs)
            send.assert_not_called()
            failed = next(e for e in self.logs if e.get('kind') == 'sanma_discard_baseline_refresh_failed')
            self.assertIn('evidence unavailable', failed['reason'])
            self.assertEqual(failed['evidence'][failed_role]['status'], 'failed')
            self.assertIsNone(failed['evidence'][failed_role]['screenshot'])
            self.assertIn('simulated full evidence disk', failed['evidence'][failed_role]['error'])
            self.assertEqual(len(failed['evidence'][failed_role]['sha256']), 64)
            self.assertFalse(any(e.get('kind') == 'sanma_discard_baseline_refreshed' for e in self.logs))

    def test_saved_hash_mismatch_fails_closed(self):
        from sanma_friend_discard_experiment import _save_refresh_frame
        with patch.object(Path, 'read_bytes', return_value=b'corrupted'):
            with self.assertRaisesRegex(OSError, 'read-back hash mismatch'):
                _save_refresh_frame(self.directory.name, 'hash-mismatch', 'candidate', self.candidate)

    def test_missing_directory_does_not_create_evidence(self):
        from sanma_friend_discard_experiment import _save_refresh_frame
        with self.assertRaisesRegex(ValueError, 'evidence directory required'):
            _save_refresh_frame(None, 'missing', 'candidate', self.candidate)


    @patch('sanma_friend_self_turn_stability.self_turn_stability', return_value=False)
    @patch('auto_operator.raised_closed_hand_slots', return_value=[])
    @patch('auto_operator.closed_hand_face_mismatches', return_value=[])
    @patch('auto_operator.experimental_draw_glyph_stability')
    @patch('sanma_friend_discard_experiment.send_discard_click')
    def test_slow_evidence_save_expires_deadline_before_input(self, send, glyph, faces, raised, wall_gate):
        import sanma_friend_discard_experiment as module
        save = module._save_refresh_frame
        now = [101.0]
        def slow_save(*args, **kwargs):
            result = save(*args, **kwargs)
            now[0] = 401.0
            return result
        glyph.side_effect = lambda *a, diagnostic=None, **kw: self._fail_at_binary_frame(diagnostic)
        self.page.screenshot.side_effect = [self.candidate, self.candidate]
        with patch.object(module, '_save_refresh_frame', side_effect=slow_save):
            with self.assertRaisesRegex(RuntimeError, 'action deadline expired'):
                execute_friend_discard(self.page, **{**self.kwargs, 'clock': lambda: now[0]})
        send.assert_not_called()


class FriendRefreshAtomicPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def save(self, frame=b'complete image'):
        from sanma_friend_discard_experiment import _save_refresh_frame
        return _save_refresh_frame(self.directory.name, 'atomic', 'candidate', frame)

    def test_private_permissions_at_creation_and_publication(self):
        import os
        import stat
        real_fsync = os.fsync
        observed = []
        def fsync(fd):
            info = os.fstat(fd)
            if stat.S_ISREG(info.st_mode):
                observed.append(stat.S_IMODE(info.st_mode))
            return real_fsync(fd)
        for mask in (0, 0o22):
            old = os.umask(mask)
            try:
                with patch('sanma_friend_discard_experiment.os.fsync', side_effect=fsync):
                    saved = self.save()
                path = Path(saved['screenshot'])
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                path.unlink()
            finally:
                os.umask(old)
        self.assertEqual(observed, [0o600, 0o600])

    def test_file_and_directory_fsync_failures_leave_no_final_or_temporary(self):
        import os
        real_fsync = os.fsync
        for failed_call in (1, 2):
            calls = [0]
            def fsync(fd):
                calls[0] += 1
                if calls[0] == failed_call:
                    raise OSError('injected fsync failure')
                return real_fsync(fd)
            with self.subTest(failed_call=failed_call), patch('sanma_friend_discard_experiment.os.fsync', side_effect=fsync):
                with self.assertRaisesRegex(OSError, 'injected fsync'):
                    self.save()
            self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_partial_write_failure_leaves_no_final_or_temporary(self):
        import os
        real_fdopen = os.fdopen
        class FailedWriter:
            def __init__(self, fd, mode): self.stream = real_fdopen(fd, mode)
            def __enter__(self): return self
            def __exit__(self, *args): self.stream.close()
            def write(self, data):
                self.stream.write(data[:3])
                raise OSError('injected partial write')
        with patch('sanma_friend_discard_experiment.os.fdopen', side_effect=FailedWriter):
            with self.assertRaisesRegex(OSError, 'partial write'):
                self.save()
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_hash_failure_leaves_no_final_or_temporary(self):
        with patch.object(Path, 'read_bytes', return_value=b'corrupt'):
            with self.assertRaisesRegex(OSError, 'read-back hash mismatch'):
                self.save()
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_competing_writers_publish_exactly_one_complete_winner(self):
        import os
        import threading
        from concurrent.futures import ThreadPoolExecutor
        barrier = threading.Barrier(2)
        real_link = os.link
        def link(source, destination):
            self.assertEqual(Path(source).stat().st_mode & 0o777, 0o600)
            barrier.wait(timeout=5)
            return real_link(source, destination)
        def attempt(data):
            try:
                return self.save(data)
            except FileExistsError:
                return None
        with patch('sanma_friend_discard_experiment.os.link', side_effect=link):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(attempt, (b'a' * 10000, b'b' * 20000)))
        winners = [item for item in results if item is not None]
        self.assertEqual(len(winners), 1)
        saved = winners[0]
        content = Path(saved['screenshot']).read_bytes()
        self.assertIn(content, (b'a' * 10000, b'b' * 20000))
        self.assertEqual(hashlib.sha256(content).hexdigest(), saved['sha256'])
        self.assertEqual(len(list(Path(self.directory.name).iterdir())), 1)


class FriendDiscardBlockingWorkTests(unittest.TestCase):
    setUp = FriendDiscardBaselineRefreshTests.setUp
    _fail_at_binary_frame = staticmethod(FriendDiscardBaselineRefreshTests._fail_at_binary_frame)

    @patch('sanma_friend_self_turn_stability.self_turn_stability', return_value=False)
    @patch('auto_operator.raised_closed_hand_slots', return_value=[])
    @patch('auto_operator.closed_hand_face_mismatches', return_value=[])
    @patch('auto_operator.experimental_draw_glyph_stability')
    @patch('sanma_friend_discard_experiment.send_discard_click')
    def test_99_second_stalls_at_every_preinput_stage_reject(self, send, glyph, faces, raised, wall_gate):
        import sanma_friend_discard_experiment as module
        save = module._save_refresh_frame
        glyph.side_effect = lambda *a, diagnostic=None, **kw: self._fail_at_binary_frame(diagnostic)
        for stage in ('reference', 'candidate', 'confirmation', 'adopted_log', 'attempted_log', 'before_click', 'session_check'):
            now = [101.0]
            self.logs.clear()
            self.page.screenshot.side_effect = [self.candidate, self.candidate]
            def delayed_save(directory, refresh_id, role, frame, **kwargs):
                result = save(directory, refresh_id, role, frame, **kwargs)
                if stage == role: now[0] += 99
                return result
            def log(event):
                self.logs.append(event)
                if ((stage == 'adopted_log' and event.get('kind') == 'sanma_discard_baseline_refreshed')
                        or (stage == 'attempted_log' and event.get('status') == 'attempted')):
                    now[0] += 99
            def before_click():
                if stage == 'before_click': now[0] += 99
            def session_check():
                if stage == 'session_check': now[0] += 99
                return True
            with self.subTest(stage=stage), patch.object(module, '_save_refresh_frame', side_effect=delayed_save):
                with self.assertRaisesRegex(RuntimeError, 'freshness expired'):
                    execute_friend_discard(self.page, **{**self.kwargs, 'clock': lambda: now[0],
                        'log': log, 'before_click': before_click, 'session_check': session_check})
            send.assert_not_called()
            self.page.mouse.click.assert_not_called()

    @patch('auto_operator.raised_closed_hand_slots', return_value=[])
    @patch('auto_operator.raised_tile_confirmation_point')
    def test_real_sender_checks_receipt_age_and_original_deadline(self, confirmation, raised):
        from auto_operator import SelectionStateUncertainAbort
        for stage in ('normal', 'fresh_after_slow_poll', 'stale_receipt', 'expired_turn', 'revoked'):
            now = [101.0]
            self.page.reset_mock()
            self.page.screenshot.side_effect = None
            self.page.screenshot.return_value = self.reference
            self.page.wait_for_timeout.side_effect = (
                (lambda _: now.__setitem__(0, 110.0)) if stage == 'fresh_after_slow_poll' else None)
            def verify(*args, **kwargs):
                if stage == 'stale_receipt': now[0] += 99
                if stage == 'expired_turn': now[0] = 400.0
                return {'x': 200, 'y': 950}
            confirmation.side_effect = verify
            def session_check():
                return not (stage == 'revoked' and self.page.mouse.click.call_count)
            kwargs = {**self.kwargs, 'clock': lambda: now[0], 'session_check': session_check}
            with self.subTest(stage=stage):
                if stage in ('normal', 'fresh_after_slow_poll'):
                    result = execute_friend_discard(self.page, **kwargs)
                    self.assertEqual(result['status'], 'selection_confirmed')
                    self.assertEqual(self.page.mouse.click.call_count, 2)
                else:
                    with self.assertRaises(SelectionStateUncertainAbort):
                        execute_friend_discard(self.page, **kwargs)
                    self.assertEqual(self.page.mouse.click.call_count, 1)

    @patch('auto_operator.raised_closed_hand_slots', return_value=[])
    @patch('sanma_friend_discard_experiment.send_discard_click')
    def test_image_age_boundary_and_invalid_clocks_at_input(self, send, raised):
        for elapsed in (4.999, 5.0, -0.001, float('nan'), float('inf')):
            now = [101.0]
            send.reset_mock()
            self.page.screenshot.side_effect = None
            self.page.screenshot.return_value = self.reference
            def before_click(): now[0] += elapsed
            kwargs = {**self.kwargs, 'clock': lambda: now[0], 'before_click': before_click}
            with self.subTest(elapsed=elapsed):
                if elapsed == 4.999:
                    self.assertEqual(execute_friend_discard(self.page, **kwargs)['status'], 'selection_confirmed')
                    send.assert_called_once()
                else:
                    with self.assertRaisesRegex(RuntimeError, 'freshness expired|deadline expired'):
                        execute_friend_discard(self.page, **kwargs)
                    send.assert_not_called()
