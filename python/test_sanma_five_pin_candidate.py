import io
import json
import unittest
from pathlib import Path
from PIL import Image, ImageEnhance
from sanma_five_pin_candidate import ordinary_five_pin_face_candidate

ROOT=Path('/home/yama1/server/data/dev-work/jantama')
TEMPLATES=Path('/home/yama1/projects/jantama-auto/templates/live-verified')

class FivePinCandidateTest(unittest.TestCase):
    slot={'x':1486,'y':921,'width':92,'height':151}
    def frame(self,tile):
        image=Image.new('RGB',(1920,1080),'white')
        image.paste(tile.convert('RGB').resize((92,151)),(1486,921))
        output=io.BytesIO();image.save(output,format='BMP');return output.getvalue()
    @unittest.skipUnless(TEMPLATES.exists(),'local templates unavailable')
    def test_all_available_tiles_except_ordinary_5p_are_rejected(self):
        for path in TEMPLATES.glob('*.png'):
            if path.name.startswith('5p__'):continue
            with self.subTest(name=path.name),Image.open(path) as tile:
                self.assertFalse(ordinary_five_pin_face_candidate(self.frame(tile),self.slot))
    @unittest.skipUnless((ROOT/'evidence148/artifacts2/frames').exists(),'saved red 5p unavailable')
    def test_real_red_five_and_faded_versions_are_rejected(self):
        folder=ROOT/'evidence148/artifacts2/frames'
        receipt=json.loads(next(folder.glob('*16-22-31*.sanma-self-turn.receipt.json')).read_text())
        report=receipt['sourceObservation']['report'];i=report['hand']['value']['tiles'].index('0p')
        geo=report['handGeometry']['value'];slot=([*geo['handSlots'],geo['drawSlot']])[i]
        with Image.open(receipt['screenshot']) as src:
            x,y,w,h=(slot[k] for k in ('x','y','width','height'));tile=src.convert('RGB').crop((x,y,x+w,y+h))
            for saturation in (1,.6,.3,.1):
                with self.subTest(saturation=saturation):
                    self.assertFalse(ordinary_five_pin_face_candidate(self.frame(ImageEnhance.Color(tile).enhance(saturation)),self.slot))
