"""Anonymous real-image evaluation; no operation may use these observations.

Candidate rectangles and labels below are manually annotated, not recognition
output.  They evaluate the existing glyph metric independently of detection.
"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from sanma_discard_glyph_diagnostic import compare

FIXTURES = Path(__file__).resolve().parents[1] / 'test/fixtures/sanma-discard-trajectory-122'
RIVER_SOUTH = {'tile': 'S', 'x': 768, 'y': 544, 'width': 62, 'height': 70, 'verified': False}
PON_RIVER = [
    {'tile': tile, 'x': x, 'y': 544, 'width': 62, 'height': 70, 'verified': False}
    for tile, x in [('9m', 768), ('W', 830), ('S', 892), ('9s', 954)]
]
DRAW = {'x': 1486, 'y': 921, 'width': 92, 'height': 151}


class DiscardTrajectoryFixtureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.seq = 0

    def receipt(self, image, candidates, selected=DRAW):
        self.seq += 1
        frame = FIXTURES / (image + '.png')
        digest = hashlib.sha256(frame.read_bytes()).hexdigest()
        river = {'scope': 'offline_untrusted_sanma_own_river', 'frameSha256': digest,
                 'verified': False, 'complete': False, 'operationAuthorized': False,
                 'candidates': candidates}
        source = {'digest': digest, 'ownRiver': river, 'report': {'handGeometry': {
            'status': 'candidate', 'value': {'handSlots': [], 'drawSlot': selected}}}}
        path = self.root / f'{self.seq}.json'
        path.write_text(json.dumps({'screenshot': str(frame), 'digest': digest,
                                    'sourceObservation': source}))
        return path

    def assert_untrusted(self, result):
        self.assertFalse(result['confirmed'])
        self.assertFalse(result['operationAuthorized'])

    def test_recorded_south_discard_with_manually_labelled_river(self):
        before = self.receipt('before', [])
        for image in ('after', 'next_turn'):
            result = compare(before, self.receipt(image, [RIVER_SOUTH]), 0)
            self.assertTrue(result['exactSingleAppendCandidate'])
            self.assertIsNotNone(result['glyphDistance'])
            self.assert_untrusted(result)

    def test_actual_pon_does_not_append_to_self_river(self):
        # A pon visibly changes the hand and other player's river, without a
        # self-discard.  Manually annotated own-river list stays unchanged.
        result = compare(self.receipt('pon_before', PON_RIVER),
                         self.receipt('pon_after', PON_RIVER), 0)
        self.assertFalse(result['exactSingleAppendCandidate'])
        self.assertIsNone(result['glyphDistance'])
        self.assert_untrusted(result)

    def test_wrong_recognition_does_not_become_confirmation(self):
        # Simulate a recognizer omitting all prior self-river tiles in an
        # actual pon frame: a fabricated append may still score.  This is a
        # deliberate counterexample to treating append or score as proof.
        result = compare(self.receipt('pon_before', []),
                         self.receipt('pon_after', [PON_RIVER[0]]), 0)
        self.assertTrue(result['exactSingleAppendCandidate'])
        self.assert_untrusted(result)

    def test_identical_frame_with_reinterpreted_candidates_is_not_append(self):
        result = compare(self.receipt('before', []),
                         self.receipt('before', [RIVER_SOUTH]), 0)
        self.assertFalse(result['exactSingleAppendCandidate'])
        self.assert_untrusted(result)

    def test_real_wrong_selected_tile_remains_unconfirmed(self):
        # The hand's first tile is 1m, while the visible newly discarded tile
        # is south.  Retain the numeric diagnostic, not an identity verdict.
        first = {'x': 223, 'y': 921, 'width': 92, 'height': 151}
        result = compare(self.receipt('before', [], selected=first),
                         self.receipt('after', [RIVER_SOUTH]), 0)
        self.assertIsNotNone(result['glyphDistance'])
        self.assert_untrusted(result)

    def test_evaluation_report_is_reproducible_and_untrusted(self):
        from sanma_discard_trajectory_evaluation import evaluate
        report = evaluate()
        self.assert_untrusted(report)
        cases = report['cases']
        self.assertLess(cases['recorded_south']['glyphDistance'],
                        cases['different_selected_tile']['glyphDistance'])
        self.assertFalse(cases['pon_without_self_discard']['exactSingleAppendCandidate'])
        self.assertTrue(cases['pon_with_simulated_omitted_river']['exactSingleAppendCandidate'])
        for result in cases.values():
            self.assert_untrusted(result)


if __name__ == '__main__':
    unittest.main()
