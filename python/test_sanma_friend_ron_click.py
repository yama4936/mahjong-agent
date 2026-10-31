"""Recorded ron prompt replayed against an in-memory page, never the browser."""
import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from auto_operator import PythonAutoOperator
from screen_state import load_references

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = ROOT / 'artifacts/sanma-manual-e48c562-20261031/actions'
BEFORE = Path('/home/yama1/.codex/sanma-run-1740066-20261031/manual-20-before.png')
AFTER = Path('/home/yama1/.codex/sanma-run-1740066-20261031/manual-20-after.png')
REFS = Path('/home/yama1/projects/jantama-auto/artifacts/live')


@unittest.skipUnless(BEFORE.exists() and AFTER.exists() and REFS.exists(), 'saved image or screen references unavailable')
class SanmaFriendRonTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.frames = Path(self.directory.name)
        self.frame = BEFORE.read_bytes()
        self.path = self.frames / 'before.png'
        self.path.write_bytes(self.frame)
        self.digest = hashlib.sha256(self.frame).hexdigest()
        self.operator = object.__new__(PythonAutoOperator)
        self.operator.args = SimpleNamespace(rules='sanma', mode='force-auto', action_deadline_ms=300000,
                                             ranked_loop=False, experimental_sanma_friend=True)
        self.operator.verified_friend_300_active = True
        self.operator.verified_friend_300_started_at = time.monotonic()
        self.operator.frames = self.frames
        self.operator.screen_references = load_references(REFS)
        self.operator.log = Mock()
        self.page = Mock()
        self.page.screenshot.side_effect = [self.frame, AFTER.read_bytes()]
        slots = [{'slot': 0, 'status': 'empty_candidate'},
                 {'slot': 1, 'status': 'candidate', 'action': 'ron', 'confidence': 0.9982238902505447},
                 {'slot': 2, 'status': 'candidate', 'action': 'skip'}]
        self.receipt = {'scope': 'sanma_self_turn_observation', 'status': 'blocked', 'operationAuthorized': False,
            'digest': self.digest, 'screenshot': str(self.path),
            'sourceObservation': {'digest': self.digest, 'operationAuthorized': False,
                'report': {'digest': self.digest, 'buttonRow': {'status': 'candidate', 'value': {'slots': slots}}}},
            'freshness': {'status': 'identical_pixels_candidate', 'operationAuthorized': False, 'elapsedMs': 1000}}

    def test_real_prompt_clicks_once_and_stops_with_unknown_outcome(self):
        result = self.operator.execute_sanma_friend_ron_candidate(self.page, self.receipt)
        self.page.mouse.click.assert_called_once_with(1012.5, 830.0)
        self.assertEqual(result['confirmation'], 'unknown')
        self.assertTrue(result['stopped'])
        self.assertEqual(Path(result['before']).read_bytes(), self.frame)
        self.assertEqual(Path(result['after']).read_bytes(), AFTER.read_bytes())

    def test_session_revoked_during_capture_stops_before_click(self):
        def capture(**_):
            self.operator.verified_friend_300_active = False
            return self.frame
        self.page.screenshot.side_effect = capture
        with self.assertRaisesRegex(RuntimeError, 'session or timing expired'):
            self.operator.execute_sanma_friend_ron_candidate(self.page, self.receipt)
        self.page.mouse.click.assert_not_called()

    def test_same_frame_cannot_be_clicked_twice(self):
        self.page.screenshot.side_effect = None
        self.page.screenshot.return_value = self.frame
        self.operator.execute_sanma_friend_ron_candidate(self.page, self.receipt)
        with self.assertRaisesRegex(RuntimeError, 'already attempted'):
            self.operator.execute_sanma_friend_ron_candidate(self.page, self.receipt)
        self.page.mouse.click.assert_called_once()

    def test_ranked_wrong_time_unknown_button_or_changed_frame_stop_before_click(self):
        variants = [lambda: setattr(self.operator, 'verified_friend_300_started_at', time.monotonic()-301),
                    lambda: setattr(self.operator.args, 'ranked_loop', True),
                    lambda: setattr(self.operator.args, 'action_deadline_ms', 2600),
                    lambda: self.receipt['sourceObservation']['report']['buttonRow']['value']['slots'][1].update(confidence=0.8),
                    lambda: self.receipt['sourceObservation']['report']['buttonRow']['value']['slots'][1].update(action='tsumo'),
                    lambda: self.receipt['sourceObservation']['report']['buttonRow']['value']['slots'][0].update(status='unresolved'),
                    lambda: self.page.screenshot.configure_mock(side_effect=None, return_value=AFTER.read_bytes())]
        for variant in variants:
            with self.subTest(variant=variant):
                self.setUp()
                variant()
                with self.assertRaises(RuntimeError):
                    self.operator.execute_sanma_friend_ron_candidate(self.page, self.receipt)
                self.page.mouse.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
