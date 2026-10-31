import io
import json
import unittest
from pathlib import Path
from PIL import Image, ImageDraw
from auto_operator import experimental_draw_glyph_stability
from sanma_friend_discard_experiment import friend_visible_empty_row_candidate

ROOT=Path('/home/yama1/.codex/sanma-run-dd7175d-20261031')
@unittest.skipUnless((ROOT/'manual-25-before.png').exists(), 'friend frame unavailable')
class TwoNorthCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame=(ROOT/'manual-25-before.png').read_bytes()
        cls.report=json.loads((Path(__file__).parent/'fixtures/sanma-dd-two-north-report.json').read_text())
        cls.slots=cls.report['buttonRow']['value']['slots']
    def test_real_partial_row_and_lighting(self):
        self.assertTrue(friend_visible_empty_row_candidate(self.frame,self.slots))
        image=Image.open(io.BytesIO(self.frame)).convert('RGB')
        ImageDraw.Draw(image).rectangle((922,511,950,514), fill='black')
        out=io.BytesIO();image.save(out,format='PNG')
        self.assertTrue(experimental_draw_glyph_stability(self.frame,out.getvalue(),self.report))
    def test_actual_buttons_over_partial_row_rejected(self):
        for name in ('ron','tsumo','skip'):
            image=Image.open(io.BytesIO(self.frame)).convert('RGB')
            if name=='ron':
                overlay=Image.open('test/fixtures/ron-button-rows/ron2.png').convert('RGB').crop((290,0,535,90));position=(890,785)
            elif name=='tsumo':
                overlay=Image.open('test/fixtures/sanma-buttons/tsumo.png').convert('RGB').resize((245,90));position=(890,785)
            else:
                overlay=Image.open('test/fixtures/sanma-button-rows/kita.png').convert('RGB').crop((580,0,825,90));position=(1180,785)
            image.paste(overlay,position);out=io.BytesIO();image.save(out,format='PNG')
            with self.subTest(name=name):
                self.assertFalse(experimental_draw_glyph_stability(self.frame,out.getvalue(),self.report))
                if name=='skip':self.assertFalse(friend_visible_empty_row_candidate(out.getvalue(),self.slots))

    def test_visible_changes_and_prompts_rejected(self):
        for box in ((1180,785,1200,805),(1315,855,1321,864),(1391,855,1424,864),(1405,785,1424,800)):
            with self.subTest(box=box):
                image=Image.open(io.BytesIO(self.frame)).convert('RGB');ImageDraw.Draw(image).rectangle(box,fill=(220,20,20))
                out=io.BytesIO();image.save(out,format='PNG')
                self.assertFalse(friend_visible_empty_row_candidate(out.getvalue(),self.slots))
                self.assertFalse(experimental_draw_glyph_stability(self.frame,out.getvalue(),self.report))
        for name in ('manual-23-before.png','manual-24-before.png'):
            self.assertFalse(friend_visible_empty_row_candidate((ROOT/name).read_bytes(),self.slots))
        self.assertFalse(friend_visible_empty_row_candidate(self.frame,[{'status':'unresolved'},*self.slots[1:]]))
