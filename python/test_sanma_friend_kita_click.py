"""Recorded kita prompt replayed against an in-memory page, never the browser."""
import hashlib
import io
import json
import copy
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw

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

    def test_rejected_preclick_screenshot_is_saved_and_no_input(self):
        self.page.screenshot.side_effect = None
        self.page.screenshot.return_value = AFTER.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'screen changed outside clock area'):
            self.operator.execute_sanma_friend_kita_candidate(self.page,self.receipt)
        event=next(call for call in self.operator.log.call_args_list if call.args[0]=='sanma_friend_kita_preclick_rejected')
        self.assertEqual(Path(event.kwargs['screenshot']).read_bytes(), AFTER.read_bytes())
        self.assertEqual(event.kwargs['digest'],hashlib.sha256(AFTER.read_bytes()).hexdigest())
        self.assertEqual(event.kwargs['baseline'],str(self.path))
        self.page.mouse.click.assert_not_called()

    def test_ba2_actual_preclick_rejection_is_distinct_and_does_not_click(self):
        from auto_operator import SanmaKitaPreclickChanged
        root=Path('/home/yama1/.codex/sanma-run-ba2a797-20261031/retry2/frames')
        before=list(root.glob('*13-22-44*sanma-self-turn.png'))
        after=list(root.glob('*sanma-kita-rejected.png'))
        if not before or not after:self.skipTest('saved ba2 friend frames unavailable')
        frame=before[0].read_bytes(); digest=hashlib.sha256(frame).hexdigest()
        self.path.write_bytes(frame)
        self.receipt['digest']=digest
        self.receipt['sourceObservation']['digest']=digest
        self.receipt['sourceObservation']['report']['digest']=digest
        self.receipt['freshness']['status']='stable_kita_glyph_candidate'
        self.page.screenshot.side_effect=None
        self.page.screenshot.return_value=after[0].read_bytes()
        with self.assertRaisesRegex(SanmaKitaPreclickChanged,'screen changed outside clock area'):
            self.operator.execute_sanma_friend_kita_candidate(self.page,self.receipt)
        self.page.mouse.click.assert_not_called()

    def test_uncertain_click_error_does_not_allow_retry(self):
        self.page.mouse.click.side_effect = RuntimeError('input acknowledgement lost')
        with self.assertRaisesRegex(RuntimeError, 'acknowledgement lost'):
            self.operator.execute_sanma_friend_kita_candidate(self.page, self.receipt)
        with self.assertRaisesRegex(RuntimeError, 'already attempted'):
            self.operator.execute_sanma_friend_kita_candidate(self.page, self.receipt)
        self.page.mouse.click.assert_called_once()

    def test_preclick_exception_type_from_click_is_uncertain_and_never_retryable(self):
        from auto_operator import SanmaKitaPreclickChanged
        self.page.mouse.click.side_effect = SanmaKitaPreclickChanged('input acknowledgement lost')
        with self.assertRaisesRegex(RuntimeError, 'click attempted; outcome unknown') as caught:
            self.operator.execute_sanma_friend_kita_candidate(self.page, self.receipt)
        self.assertNotIsInstance(caught.exception, SanmaKitaPreclickChanged)
        with self.assertRaisesRegex(RuntimeError, 'already attempted'):
            self.operator.execute_sanma_friend_kita_candidate(self.page, self.receipt)
        self.page.mouse.click.assert_called_once()

    def test_clock_change_only_does_not_prevent_real_prompt_click(self):
        with Image.open(io.BytesIO(self.frame)) as source:
            changed = source.convert('RGB')
        ImageDraw.Draw(changed).rectangle((1500,780,1550,830),fill=(11,44,99))
        data=io.BytesIO();changed.save(data,format='PNG')
        self.page.screenshot.side_effect=[data.getvalue(),AFTER.read_bytes()]
        self.receipt['freshness']['status']='stable_except_clock_candidate'
        with patch('auto_operator.latch_friend_action_target') as latch:
            result=self.operator.execute_sanma_friend_kita_candidate(self.page,self.receipt)
        self.assertTrue(result['clicked'])
        self.assertEqual(result['confirmation'],'unknown')
        self.page.mouse.click.assert_called_once_with(1012.5,830.0)
        latch.assert_called_once_with(self.operator, self.frame, 'kita')
        self.assertIn(self.digest, self.operator._sanma_friend_attempted_frames)
        event=next(call for call in self.operator.log.call_args_list if call.args[0]=='sanma_friend_candidate_click')
        self.assertEqual(Path(event.kwargs['screenshot']).read_bytes(), data.getvalue())
        self.assertEqual(event.kwargs['digest'], hashlib.sha256(data.getvalue()).hexdigest())
        self.assertEqual(event.kwargs['baselineDigest'], self.digest)
        self.assertEqual(event.kwargs['baselineScreenshot'], str(self.path))
        self.assertNotEqual(event.kwargs['digest'], event.kwargs['baselineDigest'])

    def test_a5fb00b_recorded_preclick_keeps_its_own_digest(self):
        root = Path('/home/yama1/.codex/sanma-a5fb00b-20261103/retry/frames')
        receipts = list(root.glob('*18-02-53*sanma-self-turn.receipt.json'))
        before = list(root.glob('*18-02-57*sanma-kita-before.png'))
        after = list(root.glob('*18-02-58*sanma-kita-after.png'))
        if not receipts or not before or not after:
            self.skipTest('a5fb00b friend evidence unavailable')
        receipt = json.loads(receipts[0].read_text())
        baseline = Path(receipt['screenshot']).read_bytes()
        fresh = before[0].read_bytes()
        self.assertNotEqual(hashlib.sha256(baseline).hexdigest(), hashlib.sha256(fresh).hexdigest())
        self.page.screenshot.side_effect = [fresh, after[0].read_bytes()]
        with patch('auto_operator.latch_friend_action_target') as latch:
            result = self.operator.execute_sanma_friend_kita_candidate(self.page, receipt)
        self.page.mouse.click.assert_called_once_with(1012.5, 830.0)
        latch.assert_called_once_with(self.operator, baseline, 'kita')
        self.assertIn(receipt['digest'], self.operator._sanma_friend_attempted_frames)
        event = next(c for c in self.operator.log.call_args_list if c.args[0] == 'sanma_friend_candidate_click')
        self.assertEqual(hashlib.sha256(Path(event.kwargs['screenshot']).read_bytes()).hexdigest(), event.kwargs['digest'])
        self.assertEqual(event.kwargs['baselineDigest'], hashlib.sha256(baseline).hexdigest())
        self.assertEqual(event.kwargs['baselineScreenshot'], receipt['screenshot'])
        self.assertEqual(result['confirmation'], 'unknown')


if __name__ == '__main__':
    unittest.main()
