"""Replay observed button recognition into friend-only click methods, offline.

Only the button-row recognizer is real; receipt, freshness and page are simulated.
This does not claim a live turn, full state recognition, or actual game success.
"""
import hashlib
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from auto_operator import PythonAutoOperator
from screen_state import load_references

ROOT = Path(__file__).resolve().parents[1]
RON = Path('/home/yama1/.codex/sanma-run-1740066-20261031/manual-20-before.png')
TSUMO = Path('/home/yama1/.codex/sanma-run-0bf97c7-20261101/manual-14-before.png')
REFS = Path('/home/yama1/projects/jantama-auto/artifacts/live')

@unittest.skipUnless(RON.exists() and TSUMO.exists() and REFS.exists() and (ROOT/'node_modules/tsx').exists(), 'local real prompt evidence or node dependencies unavailable')
class PostRiichiRealPath(unittest.TestCase):
    def test_actual_recognized_row_through_win_methods(self):
        for frame_path, action in ((RON, 'ron'), (TSUMO, 'tsumo')):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as tmp:
                row = json.loads(subprocess.check_output(['node','--import','tsx','test/helpers/postRiichiRow.ts',str(frame_path)], cwd=ROOT, text=True))
                self.assertEqual(row['slots'][1]['action'], action)
                frame = frame_path.read_bytes(); digest = hashlib.sha256(frame).hexdigest()
                op=object.__new__(PythonAutoOperator)
                op.args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False,experimental_sanma_friend=True)
                op.verified_friend_300_active=True; op.sanma_friend_action_observed_at=time.monotonic()
                op.sanma_friend_riichi_attempted=True; op.frames=Path(tmp); op.screen_references=load_references(REFS); op.log=Mock()
                page=Mock();page.screenshot.return_value=frame
                receipt={'scope':'sanma_self_turn_observation','status':'blocked','operationAuthorized':False,
                         'digest':digest,'screenshot':str(frame_path),'freshness':{'status':'identical_pixels_candidate','operationAuthorized':False,'elapsedMs':1},
                         'sourceObservation':{'digest':digest,'operationAuthorized':False,'report':{'digest':digest,'buttonRow':{'status':'candidate','value':row}}}}
                other = 'tsumo' if action == 'ron' else 'ron'
                with self.assertRaisesRegex(RuntimeError, 'unknown or ambiguous'):
                    getattr(op, f'execute_sanma_friend_{other}_candidate')(page,receipt)
                page.mouse.click.assert_not_called()
                method=getattr(op, f'execute_sanma_friend_{action}_candidate')
                result=method(page,receipt)
                page.mouse.click.assert_called_once_with(1012.5,830.0)
                self.assertEqual(result['confirmation'],'unknown')
                with self.assertRaisesRegex(RuntimeError,'already attempted'):method(page,receipt)
                page.mouse.click.assert_called_once()
