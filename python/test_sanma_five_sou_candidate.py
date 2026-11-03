import copy
import io
from pathlib import Path
import unittest
from PIL import Image
from sanma_five_sou_candidate import ordinary_five_sou_candidate

FIXTURES = Path(__file__).parent / 'fixtures' / 'sanma-five-sou-review'

class FiveSouCandidateTest(unittest.TestCase):
    def setUp(self):
        self.hand={'turnReady':True, 'tiles':['1m']*13+['5s'],
                   'matches':[{'tile':'1m'}]*13+[{'tile':'5s','confidence':.970336,'runnerUpConfidence':.732356}]}
        self.geometry={'confidence':.99,'drawSlot':{'x':1486,'y':921,'width':92,'height':151},
                       'evidence':{'detectedTiles':14,'drawGap':25,'medianGap':5,'rowBottomSpread':1}}
        self.draw={'index':13,'tile':'5s'}
    def frame(self, name):
        image=Image.new('RGB',(1920,1080),'white')
        with Image.open(FIXTURES / name) as tile:
            image.paste(tile.convert('RGB').resize((92,151)),(1486,921))
        data=io.BytesIO(); image.save(data,format='BMP'); return data.getvalue()
    def test_retained_real_draw_and_other_bamboo(self):
        self.assertTrue(ordinary_five_sou_candidate(self.frame('5s-evidence150.png'),self.hand,self.geometry,self.draw))
        for name in ['0s.png','9s.png']:
            with self.subTest(name=name):
                self.assertFalse(ordinary_five_sou_candidate(self.frame(name),self.hand,self.geometry,self.draw))
    def test_other_classes_in_retained_runtime_templates(self):
        path=Path('/home/yama1/projects/jantama-auto/templates/live-verified')
        if not path.is_dir(): self.skipTest('runtime comparison templates unavailable')
        image=Image.new('RGB',(1920,1080),'white')
        for tilefile in path.glob('*.png'):
            if tilefile.name.startswith('5s__'): continue
            with Image.open(tilefile) as tile: image.paste(tile.convert('RGB').resize((92,151)),(1486,921))
            data=io.BytesIO(); image.save(data,format='BMP')
            with self.subTest(tile=tilefile.name):
                self.assertFalse(ordinary_five_sou_candidate(data.getvalue(),self.hand,self.geometry,self.draw))
    def test_unreliable_data_is_rejected(self):
        frame=self.frame('5s-evidence150.png')
        for attr,value in [('confidence',.95),('confidence',float('nan')),('runnerUpConfidence',.95)]:
            hand=copy.deepcopy(self.hand); hand['matches'][-1][attr]=value
            self.assertFalse(ordinary_five_sou_candidate(frame,hand,self.geometry,self.draw))
        for value in [float('nan'), -1, 3]:
            geo=copy.deepcopy(self.geometry); geo['evidence']['rowBottomSpread']=value
            self.assertFalse(ordinary_five_sou_candidate(frame,self.hand,geo,self.draw))
