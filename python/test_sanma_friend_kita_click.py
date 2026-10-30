"""Recorded kita prompt replayed against an in-memory page, never the browser."""
import hashlib
import json
import copy
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
ACTIONS = Path('/home/yama1/sanma-independent-20261031')
BEFORE = ACTIONS / '20-turn.png'
AFTER = ACTIONS / '21-kita.png'
REFS = Path('/home/yama1/projects/jantama-auto/artifacts/live')


@unittest.skipUnless(BEFORE.exists() and AFTER.exists() and REFS.exists(), 'saved image or screen references unavailable')
class SanmaFriendKitaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = '''
import {readFile} from 'node:fs/promises'; import sharp from 'sharp';
import {layoutSchema} from './src/recognition/layout.js';
import {EXPERIMENTAL_BUTTONS} from './src/recognition/sanmaButtonExperiment.js';
import {inspectSanmaFrame} from './src/recognition/sanmaFrameExperiment.js';
const layout=layoutSchema.parse(JSON.parse(await readFile('config/layout-runtime.json','utf8')));
const buttonTemplates=Object.fromEntries(await Promise.all(EXPERIMENTAL_BUTTONS.map(async n=>[n,await readFile(`test/fixtures/sanma-buttons/${n}.png`)])));
const row=await readFile('test/fixtures/sanma-button-rows/kita.png');
const buttonRowReferences={skip:await sharp(row).extract({left:580,top:0,width:245,height:90}).png().toBuffer(),emptyRow:await readFile('test/fixtures/sanma-button-rows/empty.png')};
const frame=await readFile(process.argv[1]);
const report=await inspectSanmaFrame({frame,layout,templates:'templates/bootstrap',buttonTemplates,buttonRowReferences,publicClassifier:{async classifyTileImages(){throw Error('not evaluated')}}});
process.stdout.write(JSON.stringify(report));
'''
        cls.report = json.loads(subprocess.run(['node', '--import', 'tsx', '--input-type=module', '-e', script, str(BEFORE)],
                                              cwd=ROOT, capture_output=True, text=True, check=True, timeout=45).stdout)

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
        self.receipt = {'scope': 'sanma_self_turn_observation', 'status': 'blocked', 'operationAuthorized': False,
            'digest': self.digest, 'screenshot': str(self.path),
            'sourceObservation': {'digest': self.digest, 'operationAuthorized': False,
                'report': copy.deepcopy(self.report)},
            'freshness': {'status': 'identical_pixels_candidate', 'operationAuthorized': False, 'elapsedMs': 1000}}

    def test_real_prompt_clicks_once_and_stops_with_unknown_outcome(self):
        result = self.operator.execute_sanma_friend_kita_candidate(self.page, self.receipt)
        self.page.mouse.click.assert_called_once_with(1012.5, 830.0)
        self.assertEqual(result['confirmation'], 'unknown')
        self.assertTrue(result['stopped'])
        self.assertEqual(Path(result['before']).read_bytes(), self.frame)
        self.assertEqual(Path(result['after']).read_bytes(), AFTER.read_bytes())
        with self.assertRaisesRegex(RuntimeError, 'already attempted'):
            self.operator.execute_sanma_friend_kita_candidate(self.page, self.receipt)
        self.page.mouse.click.assert_called_once()

    def test_ranked_wrong_time_unknown_button_or_changed_frame_stop_before_click(self):
        variants = [lambda: setattr(self.operator.args, 'ranked_loop', True),
                    lambda: self.receipt['sourceObservation']['report']['hand']['value'].update(tiles=['1p'] * 14),
                    lambda: setattr(self.operator.args, 'action_deadline_ms', 2600),
                    lambda: setattr(self.operator, 'verified_friend_300_active', False),
                    lambda: self.receipt['freshness'].update(elapsedMs=20001),
                    lambda: self.receipt['sourceObservation']['report']['buttonRow']['value']['slots'][1].update(confidence=0.8),
                    lambda: self.receipt['sourceObservation']['report']['buttonRow']['value']['slots'][0].update(status='unresolved'),
                    lambda: self.page.screenshot.configure_mock(side_effect=None, return_value=AFTER.read_bytes())]
        for variant in variants:
            with self.subTest(variant=variant):
                self.setUp()
                variant()
                with self.assertRaises(RuntimeError):
                    self.operator.execute_sanma_friend_kita_candidate(self.page, self.receipt)
                self.page.mouse.click.assert_not_called()

    def test_uncertain_click_error_does_not_allow_retry(self):
        self.page.mouse.click.side_effect = RuntimeError('input acknowledgement lost')
        with self.assertRaisesRegex(RuntimeError, 'acknowledgement lost'):
            self.operator.execute_sanma_friend_kita_candidate(self.page, self.receipt)
        with self.assertRaisesRegex(RuntimeError, 'already attempted'):
            self.operator.execute_sanma_friend_kita_candidate(self.page, self.receipt)
        self.page.mouse.click.assert_called_once()


if __name__ == '__main__':
    unittest.main()
