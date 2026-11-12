"""Three-button friend-only row: strict reference and guarded click tests."""
import copy
import hashlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image
from auto_operator import experimental_friend_kita_kan_row, PythonAutoOperator

ROOT = Path(__file__).resolve().parents[1]
ROW = ROOT/'python/fixtures/sanma-kita-kan-skip-131-row.png'


def encoded(image):
    output = io.BytesIO(); image.save(output, format='PNG'); return output.getvalue()


class ThreeButtonTest(unittest.TestCase):
    def setUp(self):
        self.image = Image.new('RGB', (1920, 1080), '#183050')
        self.image.paste(Image.open(ROW).convert('RGB'), (600, 785))
        self.frame = encoded(self.image)
        self.report = {'digest': hashlib.sha256(self.frame).hexdigest(),
            'buttonRow': {'status':'candidate', 'value': {'ronReferenceCompared':True, 'slots':[
                {'slot':0,'status':'candidate','action':'kita','confidence':.9855},
                {'slot':1,'status':'candidate','action':'kan','confidence':1.0},
                {'slot':2,'status':'candidate','action':'skip','confidence':.999}]}},
            'hand':{'status':'candidate','value':{'tiles':['1p','1p','1p','5p','7p','9p','1s','3s','7s','W','N','F','C','1p']}}}

    def test_row_rejects_replaced_button_or_unverified_evidence(self):
        self.assertTrue(experimental_friend_kita_kan_row(self.frame,self.report))
        for name in ('kan','pon','riichi','tsumo'):
            altered=self.image.copy(); other=Image.open(ROOT/'test/fixtures/sanma-buttons'/f'{name}.png').convert('RGB')
            altered.paste(other,(600,785)); self.assertFalse(experimental_friend_kita_kan_row(encoded(altered),self.report),name)
        for name in ('ron1','ron2'):
            altered=self.image.copy(); other=Image.open(ROOT/'test/fixtures/ron-button-rows'/f'{name}.png').convert('RGB')
            # Full independent ron-row replacement, not a label-only test.
            altered.paste(other,(600,785)); self.assertFalse(experimental_friend_kita_kan_row(encoded(altered),self.report),name)
        altered=self.image.copy(); altered.paste(altered.crop((890,785,1135,875)),(600,785))
        self.assertFalse(experimental_friend_kita_kan_row(encoded(altered),self.report))
        for mutation in (lambda r:r['buttonRow']['value'].update(ronReferenceCompared=False),
                         lambda r:r['buttonRow']['value']['slots'][0].update(confidence=.98),
                         lambda r:r['buttonRow']['value']['slots'][1].update(action='ron'),
                         lambda r:r['buttonRow']['value']['slots'][2].update(status='unresolved')):
            report=copy.deepcopy(self.report); mutation(report);self.assertFalse(experimental_friend_kita_kan_row(self.frame,report))

    def test_click_and_preclick_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'before.png';path.write_bytes(self.frame)
            digest=self.report['digest'];op=object.__new__(PythonAutoOperator)
            op.args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False,experimental_sanma_friend=True)
            op.verified_friend_300_active=True;op.verified_friend_300_started_at=time.monotonic()
            op.frames=Path(directory);op.screen_references={};op.log=Mock()
            receipt={'scope':'sanma_self_turn_observation','status':'blocked','operationAuthorized':False,'digest':digest,'screenshot':str(path),
                'sourceObservation':{'digest':digest,'operationAuthorized':False,'report':self.report},
                'freshness':{'status':'identical_pixels_candidate','operationAuthorized':False,'elapsedMs':1000},
                'candidates':{'candidates':[{'action':'kita','slot':0},{'action':'kan','slot':1}]}}
            op.args.force_auto_click_budget_ms=8000;receipt['captureStartedMonotonic']=time.monotonic()
            op._sanma_friend_discard_observation=(receipt,receipt['digest'],receipt['captureStartedMonotonic'])
            page=Mock();page.screenshot.return_value=self.frame
            with patch('auto_operator.classify_screen',return_value=('match',1.0)):
                op.execute_sanma_friend_kita_candidate(page,receipt)
            page.mouse.click.assert_called_once_with(722.5,830.0)
            for failure in ('prior_input','win','deadline','fresh_replaced','north_missing','short_hand','candidate_slot'):
                op._sanma_friend_attempted_frames=set();op._sanma_friend_attempted_targets=set();page.reset_mock();page.screenshot.return_value=self.frame
                copy_receipt=copy.deepcopy(receipt)
                if failure=='prior_input':op._sanma_friend_attempted_targets={'old'}
                if failure=='win':copy_receipt['candidates']['candidates'].append({'action':'ron'})
                if failure=='deadline':op.verified_friend_300_started_at=time.monotonic()-301
                if failure=='north_missing':copy_receipt['sourceObservation']['report']['hand']['value']['tiles'][10]='E'
                if failure=='short_hand':copy_receipt['sourceObservation']['report']['hand']['value']['tiles'].pop()
                if failure=='candidate_slot':copy_receipt['candidates']['candidates'][0]['slot']=1
                if failure=='fresh_replaced':
                    image=self.image.copy();image.paste(image.crop((890,785,1135,875)),(600,785));page.screenshot.return_value=encoded(image)
                with patch('auto_operator.classify_screen',return_value=('match',1.0)):
                    with self.assertRaises(RuntimeError):op.execute_sanma_friend_kita_candidate(page,copy_receipt)
                page.mouse.click.assert_not_called()
                op.verified_friend_300_started_at=time.monotonic()


    def test_independent_real_pon_kan_rows_cannot_impersonate_kita(self):
        directory=Path('/home/yama1/server/data/dev-work/jantama/regression-454fb40-125/artifacts/frames')
        if not directory.exists(): self.skipTest('private 125 regression evidence unavailable')
        checked=0
        for path in directory.glob('*.sanma-self-turn.receipt.json'):
            receipt=json.loads(path.read_text())
            slots=receipt.get('sourceObservation',{}).get('report',{}).get('buttonRow',{}).get('value',{}).get('slots',[])
            if [v.get('action') for v in slots] != ['pon','kan','skip']: continue
            for filename in (receipt['screenshot'],receipt['freshness']['screenshot']):
                self.assertFalse(experimental_friend_kita_kan_row(Path(filename).read_bytes(),self.report))
                checked+=1
        self.assertGreaterEqual(checked,2)

    def test_saved_friend_receipt_dispatches_real_executor(self):
        saved = Path('/home/yama1/server/data/dev-work/jantama/regression-59751b2-131/artifacts/frames/2026-11-03T10-53-58.431852+00-00.355bf669576744c5a846da93b51d7167.sanma-self-turn.receipt.json')
        if not saved.exists(): self.skipTest('private 131 regression evidence unavailable')
        from auto_operator import experimental_kita_glyph_stability
        receipt=json.loads(saved.read_text())
        before=Path(receipt['screenshot']).read_bytes(); after=Path(receipt['freshness']['screenshot']).read_bytes()
        self.assertTrue(experimental_kita_glyph_stability(before,after,receipt['sourceObservation']['report']))
        receipt['freshness']['status']='stable_kita_glyph_candidate'
        with tempfile.TemporaryDirectory() as directory:
            op=object.__new__(PythonAutoOperator)
            op.args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False,
                experimental_sanma_friend=True, max_iterations=1, start_reviewed_friend_room="verified.png")
            op.verified_friend_300_active=True;op.verified_friend_300_started_at=time.monotonic()
            op.frames=Path(directory);op.screen_references={};op.log=Mock()
            op.args.force_auto_click_budget_ms=8000;receipt['captureStartedMonotonic']=time.monotonic()
            op._sanma_friend_discard_observation=(receipt,receipt['digest'],receipt['captureStartedMonotonic'])
            op.inspect_sanma_self_turn=Mock(return_value=receipt)
            op.observe_sanma_friend_transition=Mock(return_value={'status':'unresolved','confirmed':False})
            page=Mock();page.screenshot.return_value=after
            with patch('auto_operator.classify_screen',return_value=('match',1.0)):
                op.run_experimental_sanma_friend(page)
            page.mouse.click.assert_called_once_with(722.5,830.0)
            self.assertTrue(any(c.args[0]=='sanma_friend_candidate_click' for c in op.log.call_args_list))

if __name__=='__main__': unittest.main()
