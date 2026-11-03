"""Replay retained friend frames; skipped when the SSD evidence is unavailable."""
import glob
import io
import json
import unittest
from pathlib import Path
from PIL import Image, ImageDraw
from auto_operator import experimental_draw_glyph_stability

ROOT=Path('/home/yama1/server/data/dev-work/jantama')
class Evidence153WallLighting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logfile=ROOT/'evidence153/operator.log'
        if not logfile.exists(): raise unittest.SkipTest('retained friend evidence unavailable')
        events=[json.loads(line) for line in logfile.read_text().splitlines()]
        obs={e.get('screenshot'):e for e in events if e.get('event')=='sanma_self_turn_observed'}
        attempts=[e for e in events if e.get('event')=='sanma_friend_discard_preclick_rejected']
        case=attempts[5]
        cls.before=Path(case['referenceScreenshot']).read_bytes()
        cls.after=Path(case['screenshot']).read_bytes()
        cls.report=json.loads(Path(obs[case['referenceScreenshot']]['receiptPath']).read_text())['sourceObservation']['report']
    def test_reviewed_lighting_pair(self):
        self.assertTrue(experimental_draw_glyph_stability(self.before,self.after,self.report))
    def test_opponent_lamp_from_real_hand_change_and_other_changes(self):
        evidence=ROOT/'evidence149/transitions/98abd586b8a34e508fd85e990769777e/01.png'
        if not evidence.exists(): self.skipTest('opponent-turn evidence unavailable')
        opponent=Image.open(evidence).convert('RGB')
        for kind in ('other_lamp','draw','prompt','river','wall'):
            image=Image.open(io.BytesIO(self.after)).convert('RGB')
            if kind=='other_lamp': image.paste(opponent.crop((910,335,1015,352)),(910,335))
            elif kind=='draw': ImageDraw.Draw(image).rectangle((1490,930,1550,990),fill='black')
            elif kind=='prompt': ImageDraw.Draw(image).rectangle((900,800,1000,850),fill='black')
            elif kind=='river': ImageDraw.Draw(image).rectangle((920,540,970,570),fill='white')
            else: ImageDraw.Draw(image).rectangle((320,96,340,120),fill='black')
            out=io.BytesIO();image.save(out,format='BMP')
            with self.subTest(kind=kind):self.assertFalse(experimental_draw_glyph_stability(self.before,out.getvalue(),self.report))
    def test_actual_turn_change(self):
        run=ROOT/'evidence149/artifacts3/frames'
        if not run.exists(): self.skipTest('real turn-change evidence unavailable')
        before=next(run.glob('*16-49-55*sanma-self-turn.png'))
        report=json.loads(Path(str(before).replace('.png','.receipt.json')).read_text())['sourceObservation']['report']
        after=ROOT/'evidence149/transitions/98abd586b8a34e508fd85e990769777e/01.png'
        self.assertFalse(experimental_draw_glyph_stability(before.read_bytes(),after.read_bytes(),report))
