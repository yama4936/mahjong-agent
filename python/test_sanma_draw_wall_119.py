"""Portable anonymized frame evidence; no browser or gameplay input."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from auto_operator import experimental_draw_glyph_stability

ROOT = Path(__file__).parent / 'fixtures' / 'sanma-draw-119'


class Wall119(unittest.TestCase):
    def report(self, name):
        return json.loads((ROOT / f'{name}-report.json').read_text())

    def test_wall_edge_lighting_on_recorded_frames(self):
        for name, expected in (('119-0', True), ('119-2', False), ('41', False)):
            with self.subTest(name=name):
                before = (ROOT / f'{name}-before.png').read_bytes()
                after = (ROOT / f'{name}-after.png').read_bytes()
                self.assertEqual(experimental_draw_glyph_stability(before, after, self.report(name)), expected)

    def test_real_board_changes_rejected_individually_and_together(self):
        before = (ROOT / '116-before.png').read_bytes()
        original = Image.open(io.BytesIO(before)).convert('RGB')
        after = Image.open(ROOT / '116-after.png').convert('RGB')
        wall = Image.open(ROOT / '116-late-wall.png').convert('RGB')
        # These regions come from actual later play: own and other rivers,
        # remaining tiles / score panel, and a later depleted right wall.
        regions = {
            'own_river': [(740, 520, 1160, 760)],
            'top_river': [(950, 235, 1130, 315)],
            'right_river': [(1130, 385, 1245, 550)],
            'center': [(800, 315, 1130, 530)],
            'multiple_rivers': [(740, 520, 1160, 760), (950, 235, 1130, 315)],
            'wall_and_center': [(800, 315, 1130, 530), 'late_wall'],
            'late_wall': ['late_wall'],
        }
        for name, boxes in regions.items():
            changed = original.copy()
            for box in boxes:
                if box == 'late_wall':
                    changed.paste(wall, (1570, 210))
                else:
                    changed.paste(after.crop(box), box[:2])
            output = io.BytesIO(); changed.save(output, format='PNG')
            with self.subTest(name=name):
                self.assertFalse(experimental_draw_glyph_stability(before, output.getvalue(), self.report('116')))

    def test_partial_row_reference_is_independent_of_working_directory(self):
        # Child runs outside the checkout; no process-wide chdir affects tests.
        program = """import json, sys
from pathlib import Path
from auto_operator import experimental_draw_glyph_stability
root = Path(sys.argv[1])
before = (root / '119-0-before.png').read_bytes()
after = (root / '119-0-after.png').read_bytes()
report = json.loads((root / '119-0-report.json').read_text())
assert experimental_draw_glyph_stability(before, after, report) is True
"""
        env = os.environ.copy()
        env['PYTHONPATH'] = str(Path(__file__).resolve().parent)
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run([sys.executable, '-c', program, str(ROOT.resolve())],
                                       cwd=directory, env=env, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_actual_left_wall_depletion_rejected_without_other_changes(self):
        base = Image.open(ROOT / '119-0-before.png').convert('RGB')
        before = base.copy(); after = base.copy()
        before.paste(Image.open(ROOT / 'left-wall-26.png'), (190,80))
        after.paste(Image.open(ROOT / 'left-wall-28.png'), (190,80))
        def encode(image):
            result = io.BytesIO(); image.save(result, format='PNG'); return result.getvalue()
        detail = {}
        self.assertFalse(experimental_draw_glyph_stability(encode(before), encode(after),
                                                          self.report('119-0'), diagnostic=detail))
        self.assertEqual(detail['stage'], 'wall_color')

    def test_wall_lighting_plus_real_board_change_is_rejected(self):
        # Add real subsequent river change to each accepted lighting pair.
        later = Image.open(ROOT / '116-after.png').convert('RGB')
        for name in ('119-0',):
            before = (ROOT / f'{name}-before.png').read_bytes()
            after = Image.open(ROOT / f'{name}-after.png').convert('RGB')
            box = (740, 520, 1160, 760)
            after.paste(later.crop(box), box[:2])
            output = io.BytesIO(); after.save(output, format='PNG')
            with self.subTest(name=name):
                self.assertFalse(experimental_draw_glyph_stability(before, output.getvalue(), self.report(name)))


if __name__ == '__main__':
    unittest.main()
