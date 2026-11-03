"""Offline evaluation of anonymized frames; no gameplay state is certified.

The fixtures' candidate lists and selected rectangles are hand annotated. This
measures the existing heuristic given those annotations, not recognition recall.
"""
import hashlib
import json
import tempfile
from pathlib import Path

from sanma_discard_glyph_diagnostic import compare

FIXTURES = Path(__file__).resolve().parents[1] / 'test/fixtures/sanma-discard-trajectory-122'
SOUTH = {'tile': 'S', 'x': 768, 'y': 544, 'width': 62, 'height': 70, 'verified': False}
PON_RIVER = [{'tile': tile, 'x': x, 'y': 544, 'width': 62, 'height': 70, 'verified': False}
             for tile, x in [('9m', 768), ('W', 830), ('S', 892), ('9s', 954)]]
DRAW = {'x': 1486, 'y': 921, 'width': 92, 'height': 151}
FIRST = {'x': 223, 'y': 921, 'width': 92, 'height': 151}


def evaluate():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        serial = 0
        def receipt(image, candidates, selected=DRAW):
            nonlocal serial
            serial += 1
            frame = FIXTURES / (image + '.png')
            digest = hashlib.sha256(frame.read_bytes()).hexdigest()
            river = {'scope': 'offline_untrusted_sanma_own_river', 'frameSha256': digest,
                     'verified': False, 'complete': False, 'operationAuthorized': False,
                     'candidates': candidates}
            source = {'digest': digest, 'ownRiver': river, 'report': {'handGeometry': {
                'status': 'candidate', 'value': {'handSlots': [], 'drawSlot': selected}}}}
            path = root / f'{serial}.json'
            path.write_text(json.dumps({'screenshot': str(frame), 'digest': digest,
                                        'sourceObservation': source}))
            return path
        def scenario(before, old, selected, after, new):
            return compare(receipt(before, old, selected), receipt(after, new), 0)
        return {'scope': 'offline_untrusted_sanma_discard_trajectory_evaluation',
                'operationAuthorized': False, 'confirmed': False,
                'annotation': 'manually annotated candidates; no detector evaluated',
                'cases': {
                    'recorded_south': scenario('before', [], DRAW, 'after', [SOUTH]),
                    'recorded_south_next_turn': scenario('before', [], DRAW, 'next_turn', [SOUTH]),
                    'different_selected_tile': scenario('before', [], FIRST, 'after', [SOUTH]),
                    'pon_without_self_discard': scenario('pon_before', PON_RIVER, DRAW, 'pon_after', PON_RIVER),
                    'pon_with_simulated_omitted_river': scenario('pon_before', [], DRAW, 'pon_after', [PON_RIVER[0]]),
                    'same_frame_reinterpreted': scenario('before', [], DRAW, 'before', [SOUTH]),
                }}


if __name__ == '__main__':
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
