import copy
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image,ImageDraw
from auto_operator import PythonAutoOperator,experimental_friend_abort_kita_row,experimental_kita_glyph_stability

FOLDER=Path('/home/yama1/server/data/dev-work/jantama/evidence155/artifacts/frames')
@unittest.skipUnless(FOLDER.exists(),'friend evidence unavailable')
class AbortKita155(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=next(FOLDER.glob('*19-36-15*sanma-self-turn.png'))
        cls.fresh=next(FOLDER.glob('*19-36-18*sanma-freshness.png'))
        cls.receipt=json.loads(Path(str(cls.before).replace('.png','.receipt.json')).read_text())
        cls.report=cls.receipt['sourceObservation']['report']
    def test_real_pair_is_stable(self):
        a,b=self.before.read_bytes(),self.fresh.read_bytes()
        self.assertTrue(experimental_friend_abort_kita_row(a,self.report))
        self.assertTrue(experimental_friend_abort_kita_row(b,self.report))
        self.assertTrue(experimental_kita_glyph_stability(a,b,self.report))
    def test_unrelated_or_modified_buttons_are_rejected(self):
        frame=self.before.read_bytes()
        for rect in ((620,800,700,840),(920,800,1000,840),(1200,800,1280,840)):
            image=Image.open(io.BytesIO(frame)).convert('RGB');ImageDraw.Draw(image).rectangle(rect,fill='white')
            out=io.BytesIO();image.save(out,format='BMP')
            with self.subTest(rect=rect):self.assertFalse(experimental_friend_abort_kita_row(out.getvalue(),self.report))
        report=copy.deepcopy(self.report);report['buttonRow']['value']['slots'][1]['action']='ron'
        self.assertFalse(experimental_friend_abort_kita_row(frame,report))
    def test_only_middle_north_is_clicked_in_friend_session(self):
        op=object.__new__(PythonAutoOperator)
        op.args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False,experimental_sanma_friend=True)
        op.verified_friend_300_active=True;op.verified_friend_300_started_at=time.monotonic();op.screen_references={};op.log=Mock()
        receipt=copy.deepcopy(self.receipt);receipt['freshness']['status']='stable_kita_glyph_candidate';receipt['freshness']['operationAuthorized']=False
        with tempfile.TemporaryDirectory() as path:
            op.frames=Path(path);page=Mock();page.screenshot.return_value=self.fresh.read_bytes()
            with patch('auto_operator.classify_screen',return_value=('match',1)),patch('auto_operator.latch_friend_action_target'):
                op.execute_sanma_friend_kita_candidate(page,receipt)
            page.mouse.click.assert_called_once_with(1012.5,830.0)
    def test_ranked_and_win_candidate_rejected_without_click(self):
        for variant in ('ranked','win'):
            op=object.__new__(PythonAutoOperator);op.args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=variant=='ranked',experimental_sanma_friend=True)
            op.verified_friend_300_active=True;op.verified_friend_300_started_at=time.monotonic();op.log=Mock();page=Mock()
            receipt=copy.deepcopy(self.receipt);receipt['freshness']['status']='stable_kita_glyph_candidate';receipt['freshness']['operationAuthorized']=False
            if variant=='win':receipt['candidates']['candidates'].append({'action':'ron','slot':0})
            with self.assertRaises(RuntimeError):op.execute_sanma_friend_kita_candidate(page,receipt)
            page.mouse.click.assert_not_called()
