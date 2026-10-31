import io
import unittest
from pathlib import Path
from PIL import Image, ImageDraw
from sanma_friend_discard_experiment import friend_visible_row_with_north_overlap

ROOT=Path('/home/yama1/.codex/sanma-run-d0ff500-20261031')
SLOTS=[{'status':'empty_candidate'}, {'status':'empty_candidate'}, {'status':'unresolved'}]
@unittest.skipUnless((ROOT/'manual-03-before.png').exists(), 'independent friend image missing')
class PartialRowTests(unittest.TestCase):
    def test_north_overlap_visible_blank(self):
        self.assertTrue(friend_visible_row_with_north_overlap((ROOT/'manual-03-before.png').read_bytes(),SLOTS))
    def test_actual_skip_prompt_is_not_blank(self):
        for frame in ('manual-01-before.png','manual-02-before.png','manual-09-before.png'):
            with self.subTest(frame=frame):
                self.assertFalse(friend_visible_row_with_north_overlap((ROOT/frame).read_bytes(),SLOTS))
    def test_blank_without_north_and_unknown_other_slot_rejected(self):
        frame=(ROOT/'manual-03-before.png').read_bytes()
        self.assertFalse(friend_visible_row_with_north_overlap(frame,[{'status':'unresolved'},*SLOTS[1:]]))
        image=Image.open(io.BytesIO(frame)).convert('RGB');image.paste((0,0,0),(1322,765,1390,850))
        out=io.BytesIO();image.save(out,format='PNG')
        self.assertFalse(friend_visible_row_with_north_overlap(out.getvalue(),SLOTS))

    def test_action_marks_on_any_visible_area_rejected(self):
        frame=(ROOT/'manual-03-before.png').read_bytes()
        for box in ((1315,855,1321,864), (1391,855,1424,864), (1405,785,1424,800)):
            with self.subTest(box=box):
                image=Image.open(io.BytesIO(frame)).convert('RGB')
                ImageDraw.Draw(image).rectangle(box,fill=(220,20,20))
                out=io.BytesIO();image.save(out,format='PNG')
                self.assertFalse(friend_visible_row_with_north_overlap(out.getvalue(),SLOTS))

    def test_stale_empty_report_cannot_hide_tsumo_prompt(self):
        frame=(ROOT/'manual-03-before.png').read_bytes();image=Image.open(io.BytesIO(frame)).convert('RGB')
        button=Image.open('test/fixtures/sanma-buttons/tsumo.png').convert('RGB').resize((245,90))
        image.paste(button,(890,785));out=io.BytesIO();image.save(out,format='PNG')
        self.assertFalse(friend_visible_row_with_north_overlap(out.getvalue(),SLOTS))

    def test_low_contrast_visible_mark_is_rejected(self):
        frame=(ROOT/'manual-03-before.png').read_bytes()
        image=Image.open(io.BytesIO(frame)).convert('RGB')
        for y in range(801,817):
            for x in range(1196,1212):
                image.putpixel((x,y),tuple(min(255,c+20) for c in image.getpixel((x,y))))
        out=io.BytesIO();image.save(out,format='PNG')
        self.assertFalse(friend_visible_row_with_north_overlap(out.getvalue(),SLOTS))

    def test_bridge_uses_experimental_candidate_and_logs_risk(self):
        import hashlib, tempfile
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        from sanma_friend_discard_experiment import execute_friend_draw_candidate
        frame=(ROOT/'manual-03-before.png').read_bytes();digest=hashlib.sha256(frame).hexdigest()
        point={'x':1532,'y':996};tiles=['1m']*13+['E']
        op=Mock();op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
        op.verified_friend_300_active=True
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'frame.png';path.write_bytes(frame)
            report={'digest':digest,'hand':{'status':'candidate','value':{'safe':True,'turnReady':True,'tiles':tiles}},
                    'handGeometry':{'status':'candidate','value':{'clickPoints':[point]*14}},
                    'buttonRow':{'status':'candidate','value':{'slots':SLOTS}}}
            receipt={'scope':'sanma_self_turn_observation','digest':digest,'screenshot':str(path),
                     'sourceObservation':{'digest':digest,'report':report},'freshness':{'status':'identical_pixels_candidate'},
                     'drawCandidate':{'status':'candidate','digest':digest,'index':13,'tile':'E','point':point}}
            with patch('sanma_friend_discard_experiment.execute_friend_discard') as execute:
                execute_friend_draw_candidate(op,Mock(),receipt)
                execute.assert_called_once()
            self.assertTrue(any('hidden action' in call.kwargs.get('risk','') for call in op.log.call_args_list))
            op.args.ranked_loop=True
            with self.assertRaises(ValueError):execute_friend_draw_candidate(op,Mock(),receipt)
