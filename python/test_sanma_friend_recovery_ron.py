"""Real saved ron frame, existing ron click path, and recovery bounds."""
import json
import subprocess
from pathlib import Path
import time
import unittest
from unittest.mock import Mock

from sanma_friend_recovery_ron import execute_recovery_ron
from test_sanma_friend_ron_click import AFTER, SanmaFriendRonTest


class RecoveryRonTest(SanmaFriendRonTest):
    def setUp(self):
        super().setUp()
        now = time.monotonic()
        self.watch = Mock()
        self.watch.alive.return_value = True
        self.recovery = {'watch': self.watch, 'started': now-3,
                         'attempted_monotonic': now-2, 'selected_monotonic': now-1}
        self.receipt['candidates'] = {'candidates': [{'action':'ron'}, {'action':'skip'}]}
        self.observation = now-.5

    def run_recovery(self):
        return execute_recovery_ron(self.operator, self.page, self.recovery, self.receipt, self.observation)

    @unittest.skipUnless(Path('templates/bootstrap/1m__hf_base.png').exists() and Path('node_modules/tsx').exists(),
                         'resident recognition dependencies unavailable')
    def test_real_resident_observation_through_recovery_click(self):
        child = subprocess.Popen(['node', '--import', 'tsx', 'src/recognition/recognitionServer.ts',
                                  'config/layout-runtime.json', 'templates/bootstrap', 'examples/public-unknown.json'],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, encoding='utf-8')
        try:
            self.assertTrue(json.loads(child.stdout.readline())['ready'])
            self.operator.recognition_request_id = 0
            self.operator.recognition_server = child
            self.operator.args.experimental_sanma_fast_png = False
            self.page.screenshot.side_effect = None
            self.page.screenshot.return_value = self.frame
            observation = time.monotonic()
            self.receipt = self.operator.inspect_sanma_self_turn(self.page)
            self.observation = observation
            self.assertIn('ron', [item['action'] for item in self.receipt['candidates']['candidates']])
            self.assertEqual(self.run_recovery()['action'], 'ron')
            self.page.mouse.click.assert_called_once_with(1012.5, 830.0)
        finally:
            child.terminate()
            child.wait(timeout=5)
            child.stdin.close()
            child.stdout.close()

    def test_real_frame_through_recovery_clicks_once(self):
        result = self.run_recovery()
        self.assertEqual(result['action'], 'ron')
        self.page.mouse.click.assert_called_once_with(1012.5,830.0)
        self.assertIsNone(self.operator._sanma_friend_resume_guard)

    def test_false_prompt_changed_screen_deadline_disconnect_or_bad_order_block(self):
        def changed():
            self.page.screenshot.side_effect = None
            self.page.screenshot.return_value = b'not a frame'
        variants = [lambda: self.receipt['sourceObservation']['report']['buttonRow']['value']['slots'][1].update(action='pon'),
                    changed,
                    lambda: self.recovery.update(started=time.monotonic()-301),
                    lambda: self.watch.alive.configure_mock(return_value=False),
                    lambda: self.recovery.update(selected_monotonic=self.observation+1),
                    lambda: setattr(self.operator,'verified_friend_300_active',False)]
        for variant in variants:
            with self.subTest(variant=variant):
                self.setUp(); variant()
                with self.assertRaises(RuntimeError): self.run_recovery()
                self.page.mouse.click.assert_not_called()

    def test_repeated_attempt_is_blocked(self):
        self.page.screenshot.side_effect = None
        self.page.screenshot.return_value = self.frame
        self.run_recovery()
        with self.assertRaises(RuntimeError): self.run_recovery()
        self.page.mouse.click.assert_called_once()

    def test_disconnect_at_final_guard_blocks_click(self):
        self.watch.alive.side_effect = [True, True, False]
        with self.assertRaises(RuntimeError): self.run_recovery()
        self.page.mouse.click.assert_not_called()

    def test_real_changed_screen_is_rejected(self):
        self.page.screenshot.side_effect = None
        self.page.screenshot.return_value = AFTER.read_bytes()
        with self.assertRaises(RuntimeError): self.run_recovery()
        self.page.mouse.click.assert_not_called()

    def test_failed_log_and_ambiguous_input_never_repeat(self):
        self.operator.log.side_effect = OSError('log unavailable')
        with self.assertRaises(OSError): self.run_recovery()
        self.page.mouse.click.assert_not_called()
        self.operator.log.side_effect = None
        self.page.screenshot.side_effect = None
        self.page.screenshot.return_value = self.frame
        with self.assertRaises(RuntimeError): self.run_recovery()
        self.page.mouse.click.assert_not_called()

    def test_transport_error_after_click_attempt_latches_target(self):
        self.page.screenshot.side_effect = None
        self.page.screenshot.return_value = self.frame
        self.page.mouse.click.side_effect = OSError('outcome unknown')
        with self.assertRaises(OSError): self.run_recovery()
        with self.assertRaises(RuntimeError): self.run_recovery()
        self.page.mouse.click.assert_called_once()

    def test_non_ron_does_not_click(self):
        self.receipt['candidates']['candidates'] = [{'action':'pon'}]
        self.assertIsNone(self.run_recovery())
        self.page.mouse.click.assert_not_called()
