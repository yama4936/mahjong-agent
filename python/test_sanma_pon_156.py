import copy,io,json,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image,ImageDraw
from sanma_friend_pon_stability import pon_pass_stability
from sanma_friend_pass_experiment import execute_friend_pon_pass

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
