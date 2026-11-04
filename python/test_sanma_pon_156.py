import copy,io,json,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image,ImageDraw
from sanma_friend_pon_stability import pon_pass_stability
from sanma_friend_pass_experiment import execute_friend_pon_pass

F159=Path('/home/yama1/server/data/dev-work/jantama/evidence159/artifacts/frames')
F166=Path('/home/yama1/server/data/dev-work/jantama/evidence166/artifacts3/frames')
@unittest.skipUnless(F166.exists(),'retained opposite-player pon evidence unavailable')
class Pon166Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=next(F166.glob('*01-20-21*sanma-self-turn.png'))
        cls.receipt=json.loads(cls.before.with_suffix('.receipt.json').read_text())
        cls.after=Path(cls.receipt['freshness']['screenshot']);cls.report=cls.receipt['sourceObservation']['report']
    def test_opposite_highlight_and_turn_pulse(self):
        self.assertTrue(pon_pass_stability(self.before.read_bytes(),self.after.read_bytes(),self.report))
    def test_recorded_prompt_clicks_skip_once_in_friend_session(self):
        op=Mock();op.args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False,experimental_sanma_friend=True)
        op.verified_friend_300_active=True;op.sanma_friend_action_observed_at=time.monotonic();op._sanma_friend_attempted_targets=set();op._sanma_friend_resume_guard=None
        page=Mock();page.screenshot.return_value=self.after.read_bytes();receipt=copy.deepcopy(self.receipt)
        receipt['freshness']['status']='stable_pon_pass_candidate';receipt['freshness']['operationAuthorized']=False
        with patch('sanma_friend_pass_experiment.classify_screen',return_value=('match',1)):
            execute_friend_pon_pass(op,page,receipt)
            with self.assertRaises(RuntimeError):execute_friend_pon_pass(op,page,receipt)
        page.mouse.click.assert_called_once_with(1300,830)
    def test_real_target_ron_score_hand_or_button_changes_rejected(self):
        for box in ((1068,240,1120,296),(1124,225,1140,250),(910,322,1008,350),(832,380,856,466),(700,300,775,350),(620,800,700,840),(930,800,1000,840),
                    (1200,800,1300,840),(920,400,970,450),(500,930,550,1000)):
            with self.subTest(box=box):
                image=Image.open(self.after).convert('RGB');ImageDraw.Draw(image).rectangle(box,fill='white')
                out=io.BytesIO();image.save(out,format='BMP')
                self.assertFalse(pon_pass_stability(self.before.read_bytes(),out.getvalue(),self.report))
        report=copy.deepcopy(self.report);report['buttonRow']['value']['slots'][0].update(status='candidate',action='ron',confidence=1)
        self.assertFalse(pon_pass_stability(self.before.read_bytes(),self.after.read_bytes(),report))

@unittest.skipUnless(F159.exists(),'retained evidence unavailable')
class Pon159Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=next(F159.glob('*21-16-56*sanma-self-turn.png'))
        cls.receipt=json.loads(cls.before.with_suffix('.receipt.json').read_text())
        cls.after=Path(cls.receipt['freshness']['screenshot']);cls.report=cls.receipt['sourceObservation']['report']
    def test_partial_skip_with_highlight_is_stable_but_changes_fail(self):
        self.assertTrue(pon_pass_stability(self.before.read_bytes(),self.after.read_bytes(),self.report))
        for box in ((620,800,700,840),(930,800,1000,840),(1200,800,1300,840),
                    (715,329,762,362),(920,400,970,450),(500,930,550,1000)):
            image=Image.open(self.after).convert('RGB');ImageDraw.Draw(image).rectangle(box,fill='white')
            data=io.BytesIO();image.save(data,format='BMP')
            with self.subTest(box=box):self.assertFalse(pon_pass_stability(self.before.read_bytes(),data.getvalue(),self.report))
        row=copy.deepcopy(self.report);row['buttonRow']['value']['slots'][0].update(status='candidate',action='ron',confidence=1)
        self.assertFalse(pon_pass_stability(self.before.read_bytes(),self.after.read_bytes(),row))
    def test_skip_loses_continuity_before_click(self):
        op=Mock();op.args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False,experimental_sanma_friend=True)
        op.verified_friend_300_active=True;op.sanma_friend_action_observed_at=time.monotonic();op._sanma_friend_attempted_targets=set()
        watch=Mock();watch.alive.side_effect=[True,False];op._sanma_friend_resume_guard=(watch,time.monotonic(),300000)
        page=Mock();page.screenshot.return_value=self.after.read_bytes();receipt=copy.deepcopy(self.receipt)
        receipt['freshness']['status']='stable_pon_pass_candidate';receipt['freshness']['operationAuthorized']=False
        with patch('sanma_friend_pass_experiment.classify_screen',return_value=('match',1)), self.assertRaises(RuntimeError):
            execute_friend_pon_pass(op,page,receipt)
        page.mouse.click.assert_not_called()
    def test_skip_with_continuity_and_original_deadline(self):
        op=Mock();op.args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False,experimental_sanma_friend=True)
        op.verified_friend_300_active=True;op.sanma_friend_action_observed_at=time.monotonic();op._sanma_friend_attempted_targets=set()
        watch=Mock();watch.alive.return_value=True;op._sanma_friend_resume_guard=(watch,time.monotonic(),300000)
        page=Mock();page.screenshot.return_value=self.after.read_bytes();receipt=copy.deepcopy(self.receipt)
        receipt['freshness']['status']='stable_pon_pass_candidate';receipt['freshness']['operationAuthorized']=False
        with patch('sanma_friend_pass_experiment.classify_screen',return_value=('match',1)):
            execute_friend_pon_pass(op,page,receipt)
        page.mouse.click.assert_called_once_with(1300,830)
    def test_discard_recovery_passes_pon_at_most_once(self):
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        case=ExperimentalSanmaFriendLoopTest('runTest');case.setUp();self.addCleanup(case.doCleanups)
        case.op.args.max_iterations=4
        first=copy.deepcopy(self.receipt);first['candidates']={'candidates':[]};first['drawCandidate']={'status':'candidate'}
        first['freshness']={'status':'identical_pixels_candidate'}
        pon=copy.deepcopy(self.receipt);pon['freshness']['status']='stable_pon_pass_candidate'
        case.op.inspect_sanma_self_turn.side_effect=[first,pon,pon,pon]
        case.op.observe_sanma_friend_transition.return_value={'status':'visual_change_unconfirmed','confirmed':False}
        watch=Mock();watch.alive.return_value=True
        output={'status':'selection_confirmed','result':'discard_not_verified','tile':'E','clickIndex':0,
                'clickPoint':{'x':1,'y':1},'frameSha256':first['digest']}
        with patch('sanma_friend_discard_recovery.MatchContinuity',return_value=watch), \
             patch('sanma_friend_discard_experiment.execute_friend_draw_candidate',return_value=output) as discard, \
             patch('sanma_friend_pass_experiment.execute_friend_pon_pass',return_value={'clicked':True}) as skip:
            case.run_room()
        self.assertEqual(discard.call_count,1);self.assertEqual(skip.call_count,1)
        self.assertTrue(any(c.args[0]=='sanma_friend_recovery_pon_pass' for c in case.op.log.call_args_list))

F=Path('/home/yama1/server/data/dev-work/jantama/evidence156/artifacts/frames')
@unittest.skipUnless(F.exists(),'retained evidence unavailable')
class Pon156Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=next(F.glob('*20-11-57*sanma-self-turn.png'));cls.after=next(F.glob('*20-12-00*sanma-freshness.png'))
        cls.receipt=json.loads(Path(str(cls.before).replace('.png','.receipt.json')).read_text());cls.report=cls.receipt['sourceObservation']['report']
    def test_real_pon_pair(self):
        self.assertTrue(pon_pass_stability(self.before.read_bytes(),self.after.read_bytes(),self.report))
    def test_ron_prompt_tile_and_river_changes_rejected(self):
        for box in ((620,800,700,840),(930,800,1000,840),(1200,800,1300,840),(1000,250,1100,320),(920,400,970,450),(500,930,550,1000)):
            im=Image.open(self.after).convert('RGB');ImageDraw.Draw(im).rectangle(box,fill='white');out=io.BytesIO();im.save(out,format='BMP')
            with self.subTest(box=box):self.assertFalse(pon_pass_stability(self.before.read_bytes(),out.getvalue(),self.report))
        r=copy.deepcopy(self.report);r['buttonRow']['value']['slots'][0].update(status='candidate',action='ron',confidence=1)
        self.assertFalse(pon_pass_stability(self.before.read_bytes(),self.after.read_bytes(),r))
        for name in ('ron','tsumo'):
            if name == 'ron': replacement=Image.open('test/fixtures/ron-button-rows/ron2.png').convert('RGB').crop((290,0,535,90))
            else: replacement=Image.open('test/fixtures/sanma-buttons/tsumo.png').convert('RGB').resize((245,90))
            image=Image.open(self.after).convert('RGB');image.paste(replacement,(600,785));out=io.BytesIO();image.save(out,format='BMP')
            with self.subTest(button=name):self.assertFalse(pon_pass_stability(self.before.read_bytes(),out.getvalue(),self.report))
    def test_click_skip_only_and_ranked_refused(self):
        for ranked in (False,True):
            op=Mock();op.args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=ranked,experimental_sanma_friend=True)
            op.verified_friend_300_active=True;op.verified_friend_300_started_at=time.monotonic();op._sanma_friend_attempted_targets=set()
            op._sanma_friend_resume_guard=None
            page=Mock();page.screenshot.return_value=self.after.read_bytes();receipt=copy.deepcopy(self.receipt);receipt['freshness']['status']='stable_pon_pass_candidate';receipt['freshness']['operationAuthorized']=False
            with patch('sanma_friend_pass_experiment.classify_screen',return_value=('match',1)):
                if ranked:
                    with self.assertRaises(RuntimeError):execute_friend_pon_pass(op,page,receipt)
                    page.mouse.click.assert_not_called()
                else:
                    execute_friend_pon_pass(op,page,receipt);page.mouse.click.assert_called_once_with(1300,830)
