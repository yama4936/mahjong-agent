"""Replay observed 200 frame pairs through byte and shared-image guard paths."""
import io
import builtins
from unittest.mock import patch
import json
import unittest
from pathlib import Path
from PIL import Image
from auto_operator import experimental_kita_glyph_stability, experimental_draw_glyph_stability

ROOT=Path('/home/yama1/server/data/dev-work/jantama/evidence200')

@unittest.skipUnless((ROOT/'operator.log').exists(),'evidence200 unavailable')
class SharedDecode200Tests(unittest.TestCase):
    def test_saved_turn_observations_preserve_both_results_and_diagnostics(self):
        rows=[json.loads(s) for s in (ROOT/'operator.log').read_text().splitlines() if s.startswith('{')]
        rows=[r for r in rows if r['timestamp']>='2026-11-12T19:07:59' and r.get('event')=='sanma_self_turn_observed']
        self.assertEqual(len(rows),53)
        for i,row in enumerate(rows):
            with self.subTest(pair=i):
                receipt=json.loads(Path(row['receiptPath']).read_text());report=receipt['sourceObservation']['report']
                before=Path(row['screenshot']).read_bytes();after=Path(row['freshness']['screenshot']).read_bytes()
                old=[];new=[]
                for guard in (experimental_kita_glyph_stability,experimental_draw_glyph_stability):
                    diagnostic={};errors=[]
                    value=guard(before,after,report,diagnostic=diagnostic,on_wall_error=errors.append)
                    old.append((value,diagnostic,errors))
                with Image.open(io.BytesIO(before)) as a,Image.open(io.BytesIO(after)) as b:
                    a.load();b.load();original=(a.tobytes(),b.tobytes())
                    for guard in (experimental_kita_glyph_stability,experimental_draw_glyph_stability):
                        diagnostic={};errors=[]
                        value=guard(a,b,report,diagnostic=diagnostic,on_wall_error=errors.append)
                        new.append((value,diagnostic,errors))
                        self.assertEqual((a.tobytes(),b.tobytes()),original)
                self.assertEqual(old,new)

    def test_positive_north_prompt_byte_and_image_paths_match(self):
        folder=Path('/home/yama1/server/data/dev-work/jantama/evidence155/artifacts/frames')
        if not folder.exists(): self.skipTest('evidence155 unavailable')
        before=next(folder.glob('*19-36-15*sanma-self-turn.png'))
        after=next(folder.glob('*19-36-18*sanma-freshness.png'))
        receipt=json.loads(before.with_suffix('.receipt.json').read_text())
        report=receipt['sourceObservation']['report']
        byte_result=experimental_kita_glyph_stability(before.read_bytes(),after.read_bytes(),report)
        with Image.open(before) as a,Image.open(after) as b:
            a.load();b.load();image_result=experimental_kita_glyph_stability(a,b,report)
        self.assertTrue(byte_result);self.assertEqual(byte_result,image_result)

    def test_wall_error_is_equivalent_for_both_input_paths(self):
        rows=[json.loads(s) for s in (ROOT/'operator.log').read_text().splitlines() if s.startswith('{')]
        row=next(x for x in rows if x['timestamp']>='2026-11-12T19:07:59' and x.get('event')=='sanma_self_turn_observed')
        receipt=json.loads(Path(row['receiptPath']).read_text());report=receipt['sourceObservation']['report']
        before=Path(row['screenshot']).read_bytes();after=Path(row['freshness']['screenshot']).read_bytes()
        original_import=builtins.__import__
        def missing(name,*args,**kwargs):
            if name=='numpy':raise ImportError('forced wall error')
            return original_import(name,*args,**kwargs)
        outcomes=[]
        with Image.open(io.BytesIO(before)) as a,Image.open(io.BytesIO(after)) as b:
            a.load();b.load()
            for first,second in ((before,after),(a,b)):
                current=[]
                for guard in (experimental_kita_glyph_stability,experimental_draw_glyph_stability):
                    diagnostic={};errors=[]
                    with patch('builtins.__import__',side_effect=missing):
                        result=guard(first,second,report,diagnostic=diagnostic,on_wall_error=errors.append)
                    current.append((result,diagnostic,errors))
                outcomes.append(current)
        self.assertEqual(outcomes[0],outcomes[1])
        self.assertTrue(any(errors for _,_,errors in outcomes[0]))

    def test_guard_exception_is_equivalent_for_both_input_paths(self):
        rows=[json.loads(s) for s in (ROOT/'operator.log').read_text().splitlines() if s.startswith('{')]
        row=next(x for x in rows if x['timestamp']>='2026-11-12T19:07:59' and x.get('event')=='sanma_self_turn_observed')
        receipt=json.loads(Path(row['receiptPath']).read_text());report=receipt['sourceObservation']['report']
        before=Path(row['screenshot']).read_bytes();after=Path(row['freshness']['screenshot']).read_bytes()
        outcomes=[]
        with Image.open(io.BytesIO(before)) as a,Image.open(io.BytesIO(after)) as b:
            a.load();b.load()
            for first,second in ((before,after),(a,b)):
                diagnostic={}
                with patch('auto_operator.experimental_kita_wall_color_stable',side_effect=KeyError('forced')):
                    result=experimental_kita_glyph_stability(first,second,report,diagnostic=diagnostic)
                outcomes.append((result,diagnostic))
        self.assertEqual(outcomes[0],outcomes[1]);self.assertFalse(outcomes[0][0])
        self.assertEqual(outcomes[0][1]['outcome'],'exception')
