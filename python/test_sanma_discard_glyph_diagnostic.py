import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw
from sanma_discard_glyph_diagnostic import compare


class DiagnosticTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)

    def receipt(self, name, candidates, *, selected=True, appended=True):
        image = Image.new('RGB', (1920, 1080), '#3870a0')
        draw = ImageDraw.Draw(image)
        draw.rectangle((1486, 921, 1577, 1071), fill='white')
        if selected:
            draw.rectangle((1510, 965, 1520, 1025), fill='black')
            draw.rectangle((1510, 1015, 1555, 1025), fill='black')
        if appended:
            draw.rectangle((768, 544, 829, 597), fill='white')
            draw.rectangle((785, 553, 790, 581), fill='black')
            draw.rectangle((785, 576, 811, 581), fill='black')
        frame = self.root / (name + '.png')
        image.save(frame)
        digest = hashlib.sha256(frame.read_bytes()).hexdigest()
        river = {'scope': 'offline_untrusted_sanma_own_river', 'frameSha256': digest,
                 'verified': False, 'complete': False, 'operationAuthorized': False, 'candidates': candidates}
        source = {'digest': digest, 'ownRiver': river, 'report': {'handGeometry': {
            'status': 'candidate', 'value': {'handSlots': [], 'drawSlot': {'x': 1486, 'y': 921, 'width': 92, 'height': 151}}}}}
        path = self.root / (name + '.json')
        path.write_text(json.dumps({'screenshot': str(frame), 'digest': digest, 'sourceObservation': source}))
        return path

    def test_append_and_blank_glyph_are_never_authority(self):
        item = {'tile': 'W', 'x': 768, 'y': 544, 'width': 62, 'height': 54, 'verified': False}
        before = self.receipt('before', [], appended=False)
        after = self.receipt('after', [item])
        result = compare(before, after, 0)
        self.assertTrue(result['exactSingleAppendCandidate'])
        self.assertIsNotNone(result['glyphDistance'])
        self.assertFalse(result['confirmed'])
        self.assertFalse(result['operationAuthorized'])
        blank = self.receipt('blank', [], selected=False, appended=False)
        self.assertIsNone(compare(blank, after, 0)['glyphDistance'])

    def test_missing_multiple_and_changed_candidates_do_not_count_as_append(self):
        item = {'tile': 'W', 'x': 768, 'y': 544, 'width': 62, 'height': 54, 'verified': False}
        other = {**item, 'tile': '1p', 'x': 831}
        one = self.receipt('one', [item])
        none = self.receipt('none', [], appended=False)
        two = self.receipt('two', [item, other])
        wrong = self.receipt('wrong', [other])
        for before, after in ((one, none), (none, two), (one, wrong), (one, one)):
            result = compare(before, after, 0)
            self.assertFalse(result['exactSingleAppendCandidate'])
            self.assertIsNone(result['glyphDistance'])

    def test_same_frame_candidate_change_never_confirms_causality(self):
        item = {'tile': 'W', 'x': 768, 'y': 544, 'width': 62, 'height': 54, 'verified': False}
        before = self.receipt('same', [])
        revised = json.loads(before.read_text())
        revised['sourceObservation']['ownRiver']['candidates'] = [item]
        after = self.root / 'same-reinterpreted.json'
        after.write_text(json.dumps(revised))
        result = compare(before, after, 0)
        self.assertEqual(result['beforeDigest'], result['afterDigest'])
        self.assertFalse(result['exactSingleAppendCandidate'])
        self.assertIsNone(result['glyphDistance'])
        self.assertFalse(result['confirmed'])
        self.assertFalse(result['operationAuthorized'])

    def test_digest_and_candidate_integrity(self):
        item = {'tile': 'W', 'x': 768, 'y': 544, 'width': 62, 'height': 54, 'verified': False}
        before = self.receipt('before', [], appended=False)
        after = self.receipt('after', [item])
        altered = json.loads(after.read_text())
        altered['sourceObservation']['ownRiver']['frameSha256'] = '0' * 64
        after.write_text(json.dumps(altered))
        with self.assertRaisesRegex(ValueError, 'unbound'):
            compare(before, after, 0)
        with self.assertRaisesRegex(ValueError, 'index'):
            compare(before, before, 5)


if __name__ == '__main__':
    unittest.main()
