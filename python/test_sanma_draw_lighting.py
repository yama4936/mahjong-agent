import copy
import io
import json
import unittest
from pathlib import Path
from PIL import Image, ImageDraw
from auto_operator import experimental_draw_glyph_stability

class TestFriendDrawLighting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = Path('/home/yama1/.codex/sanma-run-dd7175d-20261031')
        if not (folder/'manual-12-before-live.png').exists():
            raise unittest.SkipTest('recorded friend-match frames unavailable')
        cls.a = (folder/'manual-12-before.png').read_bytes()
        cls.b = (folder/'manual-12-before-live.png').read_bytes()
        cls.report = json.loads((Path(__file__).parent/'fixtures/sanma-dd-normal-draw-report.json').read_text())

    def test_real_frames_and_lamp_flicker(self):
        self.assertTrue(experimental_draw_glyph_stability(self.a, self.b, self.report))

    def test_reject_hand_button_and_board_changes(self):
        for rect in [(1490,930,1550,990), (900,800,1000,850), (900,400,970,450), (920,540,970,570)]:
            with self.subTest(rect=rect):
                image = Image.open(io.BytesIO(self.b)).convert('RGB')
                ImageDraw.Draw(image).rectangle(rect, fill='black')
                out = io.BytesIO(); image.save(out,format='PNG')
                self.assertFalse(experimental_draw_glyph_stability(self.a,out.getvalue(),self.report))

    def test_reject_unknown_prompt_and_turn(self):
        for kind in ('prompt','turn'):
            report = copy.deepcopy(self.report)
            if kind == 'prompt': report['buttonRow']['value']['slots'][2]['status'] = 'unresolved'
            else: report['hand']['value']['turnReady'] = False
            self.assertFalse(experimental_draw_glyph_stability(self.a,self.b,report))

    def test_preclick_rechecks_and_ranked_is_rejected(self):
        import hashlib
        from unittest.mock import Mock, patch
        from sanma_friend_discard_experiment import execute_friend_discard
        point = {'x': 1532, 'y': 996.5}
        observation = {'status':'candidate','phase':'self_turn','promptStatus':'none','handStatus':'candidate',
                       'layoutStatus':'candidate','slots':[{'tile':'7p',**point}],
                       'frameSha256':hashlib.sha256(self.a).hexdigest(), 'referenceFrame':self.a,
                       'experimentalDrawReport':self.report}
        session = {'mode':'cpu_friend','rules':'sanma','clock':'300+0','actionDeadlineMs':300000,
                   'ranked':False,'cpuCount':2,'roomVerified':True}
        plan = {'scope':'offline_untrusted_sanma_discard_plan','operationAuthorized':False,
                'tile':'7p','clickIndex':0,'clickPoint':point}
        page=Mock();page.screenshot.return_value=self.b
        kwargs=dict(session=session,observation=observation,plan=plan,layout={'viewport':{}},
                    log=lambda event:None,turn_started_monotonic=100,clock=lambda:101)
        with patch('sanma_friend_discard_experiment.send_discard_click',return_value={}) as send:
            result=execute_friend_discard(page,**kwargs)
            self.assertEqual(result['result'],'discard_not_verified')
            send.assert_called_once()
            send.reset_mock()
            with self.assertRaises(ValueError):
                execute_friend_discard(page,**{**kwargs,'session':{**session,'ranked':True}})
            send.assert_not_called()
            image=Image.open(io.BytesIO(self.b)).convert('RGB')
            ImageDraw.Draw(image).rectangle((1490,930,1550,990),fill='black')
            out=io.BytesIO();image.save(out,format='PNG');page.screenshot.return_value=out.getvalue()
            with self.assertRaisesRegex(ValueError,'frame changed'):
                execute_friend_discard(page,**kwargs)
            send.assert_not_called()
