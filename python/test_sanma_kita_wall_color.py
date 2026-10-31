"""Additional wall-color check; saved live images never authorize input."""
import io
import json
import unittest
from pathlib import Path
from PIL import Image
from auto_operator import experimental_kita_glyph_stability, experimental_kita_wall_color_stable

ROOT = Path('/home/yama1/.codex/sanma-run-7e79853-20261101')
OPPONENT = Path('/home/yama1/.codex/sanma-run-cd82c23-20261101')
REPORT = Path('/home/yama1/projects/jantama-test-tmp/monitor-receipt-3.json')

@unittest.skipUnless((ROOT/'monitor-5.png').exists() and REPORT.exists(), 'saved friend frames unavailable')
class WallColorTest(unittest.TestCase):
    def test_lighting_pairs_pass_additional_guard(self):
        for i in range(5):
            a=(ROOT/f'monitor-{i}.png').read_bytes()
            b=(ROOT/f'monitor-{i+1}.png').read_bytes()
            with self.subTest(pair=i): self.assertTrue(experimental_kita_wall_color_stable(a,b))

    def test_same_luminance_gray_change_rejected_in_full_path(self):
        before=(ROOT/'monitor-3.png').read_bytes()
        image=Image.open(io.BytesIO(before)).convert('RGB')
        rect=(150,80,390,700)
        image.paste(image.crop(rect).convert('L').convert('RGB'),rect)
        stream=io.BytesIO();image.save(stream,format='PNG')
        report=json.loads(REPORT.read_text())['result']['report']
        self.assertFalse(experimental_kita_glyph_stability(before,stream.getvalue(),report))

    def test_real_opponent_change_rejected(self):
        a=OPPONENT/'manual-4-before.png';b=OPPONENT/'manual-4-after.png'
        if not a.exists() or not b.exists():self.skipTest('opponent frames unavailable')
        self.assertFalse(experimental_kita_wall_color_stable(a.read_bytes(),b.read_bytes()))

    def test_malformed_and_unreviewed_dimensions_rejected(self):
        self.assertFalse(experimental_kita_wall_color_stable(b'bad',b'bad'))
        out=io.BytesIO();Image.new('RGB',(16,16)).save(out,format='PNG')
        self.assertFalse(experimental_kita_wall_color_stable(out.getvalue(),out.getvalue()))
