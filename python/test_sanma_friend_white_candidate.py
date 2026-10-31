import copy
import hashlib
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch
import io
import json
import unittest
from pathlib import Path
from PIL import Image, ImageDraw
from sanma_friend_discard_experiment import experimental_white_hand_candidate, execute_friend_draw_candidate

LOG = Path('/home/yama1/projects/jantama-test-tmp/inspect-start-fields.log')
IMAGES = Path('/home/yama1/.codex/sanma-manual-current-01')

@unittest.skipUnless(LOG.exists() and IMAGES.exists(), 'live friend evidence unavailable')
class WhiteCandidateTests(unittest.TestCase):
    def setUp(self):
        line = next(line for line in LOG.read_text().splitlines() if line.startswith('1 '))
        report = json.loads(line[2:])
        self.hand = report['hand']['value']
        self.geometry = report['handGeometry']['value']
        self.frame = next(IMAGES.glob('*.png')).read_bytes()
    def test_live_two_white_candidates(self):
        self.assertFalse(self.hand['safe'])
        self.assertEqual(experimental_white_hand_candidate(self.frame, self.hand, self.geometry), [10, 11])
    def test_missing_geometry_low_confidence_and_nonwhite_are_rejected(self):
        for field in ('geometry', 'confidence', 'nonwhite'):
            hand, geometry, frame = copy.deepcopy(self.hand), copy.deepcopy(self.geometry), self.frame
            if field == 'geometry': geometry['evidence']['detectedTiles'] = 13
            if field == 'confidence': hand['matches'][3]['confidence'] = .4
            if field == 'nonwhite':
                image = Image.open(io.BytesIO(frame)).convert('RGB')
                ImageDraw.Draw(image).rectangle((1190,950,1240,1040), fill=(0,0,0))
                out = io.BytesIO(); image.save(out,format='PNG'); frame = out.getvalue()
            with self.subTest(field=field):
                self.assertIsNone(experimental_white_hand_candidate(frame, hand, geometry))

    @patch("sanma_friend_discard_experiment.execute_friend_discard")
    def test_friend_bridge_records_white_risk_without_promoting_safe(self, execute):
        digest = hashlib.sha256(self.frame).hexdigest()
        op = Mock()
        op.args = SimpleNamespace(experimental_sanma_friend=True, rules="sanma", mode="force-auto", action_deadline_ms=300000, ranked_loop=False)
        op.verified_friend_300_active = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frame.png"; path.write_bytes(self.frame)
            point = self.geometry['clickPoints'][-1]
            report = {'digest':digest, 'hand':{'status':'candidate','value':self.hand},
                      'handGeometry':{'status':'candidate','value':self.geometry},
                      'buttonRow':{'status':'candidate','value':{'slots':[{'status':'empty_candidate'}]*3}}}
            receipt = {'scope':'sanma_self_turn_observation','digest':digest,'screenshot':str(path),
                       'sourceObservation':{'digest':digest,'report':report},
                       'freshness':{'status':'stable_except_clock_candidate'},
                       'drawCandidate':{'status':'candidate','digest':digest,'index':13,
                                        'tile':self.hand['tiles'][-1], 'point':point}}
            execute_friend_draw_candidate(op,Mock(),receipt)
            execute.assert_called_once()
            self.assertFalse(self.hand['safe'])
            self.assertEqual(op.log.call_args.kwargs['confirmed'],False)
            self.assertIn('unloaded',op.log.call_args.kwargs['risk'])
            op.args.ranked_loop = True
            with self.assertRaises(ValueError): execute_friend_draw_candidate(op,Mock(),receipt)

    @patch("sanma_friend_discard_experiment.execute_friend_discard")
    def test_white_hypothesis_does_not_waive_draw_confidence(self, execute):
        hand=copy.deepcopy(self.hand)
        hand['matches'][-1]['confidence']=.96;hand['matches'][-1]['runnerUpConfidence']=.94
        self.assertIsNotNone(experimental_white_hand_candidate(self.frame,hand,self.geometry))
        digest=hashlib.sha256(self.frame).hexdigest();op=Mock()
        op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
        op.verified_friend_300_active=True
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'frame.png';path.write_bytes(self.frame);point=self.geometry['clickPoints'][-1]
            report={'digest':digest,'hand':{'status':'candidate','value':hand},'handGeometry':{'status':'candidate','value':self.geometry},
                    'buttonRow':{'status':'candidate','value':{'slots':[{'status':'empty_candidate'}]*3}}}
            receipt={'scope':'sanma_self_turn_observation','digest':digest,'screenshot':str(path),'sourceObservation':{'digest':digest,'report':report},
                     'freshness':{'status':'stable_except_clock_candidate'},'drawCandidate':{'status':'candidate','digest':digest,'index':13,'tile':hand['tiles'][-1],'point':point}}
            with self.assertRaisesRegex(ValueError,'unsafe hand'):
                execute_friend_draw_candidate(op,Mock(),receipt)
            execute.assert_not_called()
