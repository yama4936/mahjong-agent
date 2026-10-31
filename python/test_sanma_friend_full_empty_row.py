import hashlib
import io
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw
from sanma_friend_discard_experiment import friend_visible_full_empty_row_candidate, execute_friend_draw_candidate

ROOT=Path('/home/yama1/.codex/sanma-run-cd82c23-20261101')
REPORT=Path('/home/yama1/projects/jantama-test-tmp/shape-cd82-1.json')
SLOTS=[{'status':'empty_candidate'},{'status':'empty_candidate'},{'status':'unresolved'}]

class PortableFullVisibleEmptyRowTest(unittest.TestCase):
    def test_blank_full_row_and_action_prompts(self):
        base=Image.new('RGB',(1920,1080),(20,30,50))
        base.paste(Image.open('test/fixtures/sanma-button-rows/empty.png').convert('RGB'),(600,785))
        base.paste(Image.open('python/fixtures/sanma-friend-empty-slot-6c.png').convert('RGB'),(1180,785))
        out=io.BytesIO();base.save(out,format='PNG')
        self.assertTrue(friend_visible_full_empty_row_candidate(out.getvalue(),SLOTS))
        for path in [*Path('test/fixtures/sanma-button-rows').glob('*.png'), *Path('test/fixtures/ron-button-rows').glob('*.png')]:
            if path.name.startswith('empty'):continue
            row=Image.open(path).convert('RGB')
            image=base.copy();image.paste(row,(600,785))
            out=io.BytesIO();image.save(out,format='PNG')
            with self.subTest(prompt=path.name):
                self.assertFalse(friend_visible_full_empty_row_candidate(out.getvalue(),SLOTS))
            # A visible right-only action must also veto a false empty report.
            image=base.copy();image.paste(row.crop((580,0,825,90)),(1180,785))
            out=io.BytesIO();image.save(out,format='PNG')
            with self.subTest(right_only=path.name):
                self.assertFalse(friend_visible_full_empty_row_candidate(out.getvalue(),SLOTS))

    def test_redacted_fixture_produces_hand_discard_candidate_and_binds_hash(self):
        fixture=Path('python/fixtures/sanma-full-empty-row')
        image_path=fixture/'redacted-hand-row.png'
        data=json.loads((fixture/'receipt.json').read_text())
        digest=hashlib.sha256(image_path.read_bytes()).hexdigest()
        self.assertEqual(data['digest'],digest)
        self.assertEqual(data['report']['digest'],digest)
        self.assertEqual(data['structuralPositions']['digest'],digest)
        hand=data['report']['hand']['value'];geo=data['report']['handGeometry']['value']
        receipt={'scope':'sanma_self_turn_observation','digest':digest,'screenshot':str(image_path),
                 'sourceObservation':data,'structuralPositions':data['structuralPositions'],
                 'drawCandidate':{'status':'candidate','digest':digest,'index':13,'tile':hand['tiles'][13],'point':geo['clickPoints'][13]},
                 'freshness':{'status':'identical_pixels_candidate'}}
        args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
        layout=json.loads(Path('config/layout-runtime.json').read_text())
        op=SimpleNamespace(args=args,verified_friend_300_active=True,layout=layout,sanma_friend_riichi_attempted=False,frames=fixture,log=Mock())
        with patch('sanma_friend_discard_experiment.friend_opponent_riichi_candidates',return_value=[]), \
             patch('sanma_friend_discard_experiment.execute_friend_discard',return_value={'confirmation':'unknown'}) as execute:
            execute_friend_draw_candidate(op,Mock(),receipt)
            plan=execute.call_args.kwargs['plan']
            self.assertEqual((plan['tile'],plan['clickIndex']),('1s',7))
            self.assertNotEqual(plan['clickIndex'],receipt['drawCandidate']['index'])
            self.assertFalse(plan['operationAuthorized'])
            receipt['sourceObservation']={**data,'digest':'0'*64}
            with self.assertRaisesRegex(ValueError,'unavailable'):
                execute_friend_draw_candidate(op,Mock(),receipt)
            self.assertEqual(execute.call_count,1)
            receipt['sourceObservation']=data
            receipt['structuralPositions']={**data['structuralPositions'],'digest':'0'*64}
            execute_friend_draw_candidate(op,Mock(),receipt)
            # A mismatched structural receipt must never produce a shape hand-discard.
            self.assertEqual(execute.call_args.kwargs['plan']['clickIndex'],13)

    def test_redacted_fixture_obscured_buttons_rejected(self):
        path=Path('python/fixtures/sanma-full-empty-row/redacted-hand-row.png')
        for button in ('kita','riichi','pon-kan','tsumo'):
            image=Image.open(path).convert('RGB');row=Image.open(f'test/fixtures/sanma-button-rows/{button}.png').convert('RGB')
            image.paste(row,(600,785));out=io.BytesIO();image.save(out,format='PNG')
            with self.subTest(button=button):self.assertFalse(friend_visible_full_empty_row_candidate(out.getvalue(),SLOTS))
        image=Image.open(path).convert('RGB');ImageDraw.Draw(image).rectangle((1320,785,1424,874),fill='black')
        out=io.BytesIO();image.save(out,format='PNG')
        self.assertFalse(friend_visible_full_empty_row_candidate(out.getvalue(),SLOTS))

    def test_uncertain_left_slots_and_wrong_size_rejected(self):
        out=io.BytesIO();Image.new('RGB',(16,16)).save(out,format='PNG')
        self.assertFalse(friend_visible_full_empty_row_candidate(out.getvalue(),SLOTS))
        self.assertFalse(friend_visible_full_empty_row_candidate(b'bad',[{'status':'unresolved'},*SLOTS[1:]]))

@unittest.skipUnless((ROOT/'manual-1-before.png').exists(), 'saved friend screenshot unavailable')
class FullVisibleEmptyRowTest(unittest.TestCase):
    def setUp(self):
        self.frame=(ROOT/'manual-1-before.png').read_bytes()

    def test_real_empty_and_north_occlusion(self):
        self.assertTrue(friend_visible_full_empty_row_candidate(self.frame,SLOTS))
        for i in (13,20,24,31,35):
            with self.subTest(i=i):
                self.assertFalse(friend_visible_full_empty_row_candidate((ROOT/f'manual-{i}-before.png').read_bytes(),SLOTS))

    def test_real_action_rows_and_synthetic_partial_cover_rejected(self):
        for row in [*Path('test/fixtures/sanma-button-rows').glob('*.png'), *Path('test/fixtures/ron-button-rows').glob('*.png')]:
            if row.name.startswith('empty'):continue
            image=Image.open(io.BytesIO(self.frame)).convert('RGB')
            image.paste(Image.open(row).convert('RGB'),(600,785))
            out=io.BytesIO();image.save(out,format='PNG')
            with self.subTest(row=row.name):
                self.assertFalse(friend_visible_full_empty_row_candidate(out.getvalue(),SLOTS))
        for box in ((1180,785,1200,875),(1320,785,1424,874),(600,785,650,875),(890,785,940,875)):
            image=Image.open(io.BytesIO(self.frame)).convert('RGB');ImageDraw.Draw(image).rectangle(box,fill='black')
            out=io.BytesIO();image.save(out,format='PNG')
            with self.subTest(box=box):self.assertFalse(friend_visible_full_empty_row_candidate(out.getvalue(),SLOTS))

    @unittest.skipUnless(REPORT.exists(), 'resident recognition replay unavailable')
    def test_real_shape_reaches_mock_discard_plan(self):
        data=json.loads(REPORT.read_text())['result'];report=data['report'];geo=report['handGeometry']['value'];hand=report['hand']['value'];digest=hashlib.sha256(self.frame).hexdigest()
        self.assertEqual(digest,data['digest'])
        receipt={'scope':'sanma_self_turn_observation','digest':digest,'screenshot':str(ROOT/'manual-1-before.png'),
                 'sourceObservation':data,'structuralPositions':data['structuralPositions'],
                 'drawCandidate':{'status':'candidate','digest':digest,'index':13,'tile':hand['tiles'][13],'point':geo['clickPoints'][13]},
                 'freshness':{'status':'identical_pixels_candidate'}}
        args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
        layout=json.loads(Path('config/layout-runtime.json').read_text());op=SimpleNamespace(args=args,verified_friend_300_active=True,layout=layout,sanma_friend_riichi_attempted=False,frames=ROOT,log=Mock())
        with patch('sanma_friend_discard_experiment.friend_opponent_riichi_candidates',return_value=[]), \
             patch('sanma_friend_discard_experiment.execute_friend_discard',return_value={'confirmation':'unknown'}) as execute:
            execute_friend_draw_candidate(op,Mock(),receipt)
        plan=execute.call_args.kwargs['plan']
        self.assertEqual((plan['tile'],plan['clickIndex']),('1s',7))
        self.assertNotEqual(plan['clickIndex'],receipt['drawCandidate']['index'])
        self.assertFalse(plan['operationAuthorized'])
