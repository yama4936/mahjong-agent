"""Retained friend-match regression: the opposite offer moves between river cells."""
import copy
import io
import json
import time
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw
from sanma_friend_pon_stability import pon_pass_stability
from sanma_friend_pass_experiment import execute_friend_pon_pass
from auto_operator import PythonAutoOperator

ROOT = Path('/home/yama1/server/data/dev-work/jantama/evidence190/attempt/artifacts/frames')

@unittest.skipUnless(ROOT.exists(), 'retained friend-match evidence unavailable')
class DynamicOppositeOffer190(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = next(ROOT.glob('*07-18-36*sanma-self-turn.receipt.json'))
        cls.receipt = json.loads(path.read_text())
        cls.before = Path(cls.receipt['screenshot']).read_bytes()
        cls.after = Path(cls.receipt['freshness']['screenshot']).read_bytes()
        cls.report = cls.receipt['sourceObservation']['report']

    def test_observation_and_preclick_recheck_reach_only_mock_skip(self):
        with tempfile.TemporaryDirectory() as directory:
            op=object.__new__(PythonAutoOperator);op.frames=Path(directory);op.log=Mock();op.screen_references={}
            op.args=SimpleNamespace(rules='sanma',mode='force-auto',experimental_sanma_friend=True,
                action_deadline_ms=300000,ranked_loop=False,start_reviewed_friend_room='reviewed')
            op.args.force_auto_click_budget_ms=8000
            op.verified_friend_300_active=True;op.sanma_friend_action_observed_at=time.monotonic()
            op._sanma_friend_attempted_targets=set();op._sanma_friend_resume_guard=None
            op.observe_sanma_resident=Mock(return_value=self.receipt['sourceObservation'])
            page=Mock();page.screenshot.side_effect=[self.before,self.after,self.after]
            receipt=op.inspect_sanma_self_turn(page)
            self.assertEqual(receipt['freshness']['status'],'stable_pon_pass_candidate')
            with patch('sanma_friend_pass_experiment.classify_screen',return_value=('match',1)):
                result=execute_friend_pon_pass(op,page,receipt)
            page.mouse.click.assert_called_once_with(1300,830)
            self.assertEqual(result['confirmation'],'unknown')

    def test_ron_at_freshness_or_preclick_never_clicks(self):
        image=Image.open(io.BytesIO(self.after)).convert('RGB')
        with Image.open('test/fixtures/ron-button-rows/ron2.png') as source:
            image.paste(source.convert('RGB').crop((290,0,535,90)),(600,785))
        data=io.BytesIO();image.save(data,format='PNG');ron=data.getvalue()
        for during_preclick in (False,True):
            with self.subTest(during_preclick=during_preclick), tempfile.TemporaryDirectory() as directory:
                op=object.__new__(PythonAutoOperator);op.frames=Path(directory);op.log=Mock();op.screen_references={}
                op.args=SimpleNamespace(rules='sanma',mode='force-auto',experimental_sanma_friend=True,
                    action_deadline_ms=300000,ranked_loop=False,start_reviewed_friend_room='reviewed')
                op.args.force_auto_click_budget_ms=8000
                op.verified_friend_300_active=True;op.sanma_friend_action_observed_at=time.monotonic()
                op._sanma_friend_attempted_targets=set();op._sanma_friend_resume_guard=None
                op.observe_sanma_resident=Mock(return_value=self.receipt['sourceObservation'])
                page=Mock();page.screenshot.side_effect=[self.before,self.after if during_preclick else ron,ron]
                receipt=op.inspect_sanma_self_turn(page)
                self.assertEqual(receipt['freshness']['status'], 'stable_pon_pass_candidate' if during_preclick else 'changed')
                with patch('sanma_friend_pass_experiment.classify_screen',return_value=('match',1)):
                    with self.assertRaises(RuntimeError):execute_friend_pon_pass(op,page,receipt)
                page.mouse.click.assert_not_called()

    def test_real_ron_button_and_ambiguous_report_are_rejected(self):
        image=Image.open(io.BytesIO(self.after)).convert('RGB')
        ron=Image.open('test/fixtures/ron-button-rows/ron2.png').convert('RGB')
        image.paste(ron.crop((290,0,535,90)),(600,785))
        out=io.BytesIO();image.save(out,format='PNG')
        self.assertFalse(pon_pass_stability(self.before,out.getvalue(),self.report))
        for key in ('ron','unknown'):
            report=copy.deepcopy(self.report)
            report['buttonRow']['value']['slots'][0].update(status='candidate',action=key)
            self.assertFalse(pon_pass_stability(self.before,self.after,report))
        report=copy.deepcopy(self.report);report['buttonRow']['value']['ronReferenceCompared']=False
        self.assertFalse(pon_pass_stability(self.before,self.after,report))

    def test_actual_tile_replacements_are_rejected(self):
        for source,target in [((1070,240,1120,296),(1016,240)),((1016,240,1066,296),(1070,240))]:
            image=Image.open(io.BytesIO(self.after)).convert('RGB')
            image.paste(image.crop(source),target)
            out=io.BytesIO();image.save(out,format='PNG')
            self.assertFalse(pon_pass_stability(self.before,out.getvalue(),self.report))

    def test_recorded_inactive_seat_indicator_rejected(self):
        # An independently captured later frame has a different seat indicator.
        other=ROOT.parent.parent.parent / 'manual6-before.png'
        image=Image.open(io.BytesIO(self.after)).convert('RGB')
        with Image.open(other) as source:
            image.paste(source.convert('RGB').crop((890,320,1010,352)),(890,320))
        out=io.BytesIO();image.save(out,format='PNG')
        self.assertFalse(pon_pass_stability(self.before,out.getvalue(),self.report))

    def test_rejects_green_replacement_of_neighbor(self):
        image=Image.open(io.BytesIO(self.after)).convert('RGB')
        ImageDraw.Draw(image).rectangle((1074,250,1089,275),fill=(20,220,20))
        out=io.BytesIO();image.save(out,format='PNG')
        self.assertFalse(pon_pass_stability(self.before,out.getvalue(),self.report))

    def test_real_pair_rejects_material_changes(self):
        for label,box in [('offered',(1020,252,1055,283)),('neighbor',(1077,253,1110,285)),
                          ('hand',(260,950,300,1000)),('round',(920,400,970,450)),
                          ('ron',(640,805,750,850)),('skip',(1230,810,1300,845)),
                          ('arrow',(1025,210,1060,235)),('indicator',(970,330,980,340))]:
            with self.subTest(label=label):
                image=Image.open(io.BytesIO(self.after)).convert('RGB')
                ImageDraw.Draw(image).rectangle(box,fill='black')
                out=io.BytesIO();image.save(out,format='PNG')
                self.assertFalse(pon_pass_stability(self.before,out.getvalue(),self.report))

if __name__ == '__main__': unittest.main()
