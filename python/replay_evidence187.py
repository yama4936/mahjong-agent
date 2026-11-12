"""Read-only replay of SHA-bound saved images; never connects to a browser.

Run from any cwd: python python/replay_evidence187.py [--source-root PATH].
The PNG originals remain in SSD evidence storage, not the Git repository.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageChops
from sanma_friend_freshness import friend_frame_changes, friend_frame_stable


FIXTURES = Path(__file__).parent / 'fixtures' / 'evidence187'


def checked_bytes(path, expected):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise AssertionError(f'evidence SHA256 mismatch: {path}')
    return data


def changed_pixels(before, after, box, mask_clock=False):
    a = Image.open(io.BytesIO(before)).convert('RGB')
    b = Image.open(io.BytesIO(after)).convert('RGB')
    delta = ImageChops.difference(a, b)
    if mask_clock:
        delta.paste((0, 0, 0), (1425, 755, 1650, 870))
    return sum(p != (0, 0, 0) for p in delta.crop(box).getdata())


def png(image):
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


def guard_results(before, after, report):
    from auto_operator import experimental_kita_glyph_stability, experimental_draw_glyph_stability
    from sanma_friend_pon_stability import pon_pass_stability
    results = {}
    for name, guard in [('kita', experimental_kita_glyph_stability),
                        ('draw', experimental_draw_glyph_stability), ('pon', pon_pass_stability)]:
        diagnostic = {}
        wall_errors = []
        accepted = guard(before, after, report, diagnostic=diagnostic, on_wall_error=wall_errors.append)
        results[name] = {'accepted': accepted, 'diagnostic': diagnostic, 'wallErrors': wall_errors}
    results['refreshInitialEligibility'] = results['draw']['diagnostic'].get('stage') == 'binary_frame' and not results['draw']['wallErrors']
    return results


def replay(source_root=None):
    manifest = json.loads((FIXTURES / 'manifest.json').read_text())
    root = Path(source_root or manifest['sourceRootDefault'])
    checked_bytes(root / manifest['sourceLog'], manifest['sourceLogSha256'])
    frames, reports = {}, {}
    for key, item in manifest['frames'].items():
        frames[key] = checked_bytes(root / item['path'], item['sha256'])
        if 'report' in item:
            reports[key] = json.loads(checked_bytes(FIXTURES / item['report'], item['reportSha256']))
    results = []
    for case in manifest['cases']:
        before, after = frames[case['before']], frames[case['after']]
        diagnostic = {}
        changes = friend_frame_changes(before, after, report=reports[case['before']], diagnostic=diagnostic)
        assert changes['hand'] is case['expectedHand'], (case['name'], changes, diagnostic)
        if 'expectedActions' in case:
            assert changes['actions'] is case['expectedActions'], (case['name'], changes)
        assert changes['fullFrame'] and not friend_frame_stable(before, after)
        guards = guard_results(before, after, reports[case['before']])
        if case['expectedHand']:
            assert not any(guards[k]['accepted'] for k in ('kita', 'draw', 'pon')), guards
            assert not guards['refreshInitialEligibility'], guards
        results.append({'guards': guards, 'name': case['name'], 'kind': case['kind'], 'changes': changes, 'diagnostic': diagnostic, 'fullFrameRejected': True})
    before, after = frames['line28-source'], frames['line28-freshness']
    assert changed_pixels(before, after, (223, 921, 1578, 1072)) == 0
    assert changed_pixels(before, after, (180, 865, 1650, 1080), mask_clock=True) == 539
    results[0]['actualHandEnvelopeChangedPixels'] = 0
    results[0]['legacyHandEnvelopeClockMaskedChangedPixels'] = 539
    base = Image.open(io.BytesIO(before)).convert('RGB')
    donor = Image.open(io.BytesIO(frames['line23-source'])).convert('RGB')
    action_only = base.copy()
    action_only.paste(donor.crop((600, 785, 1425, 875)), (600, 785))
    synthetic = [('isolated-real-button-crop-transplant', action_only, False, True)]
    tile_only = base.copy()
    tile_only.paste(donor.crop((1485, 921, 1578, 1072)), (1485, 921))
    synthetic.append(('isolated-real-north-tile-crop-transplant', tile_only, True, False))
    one_pixel = base.copy()
    r, g, b = one_pixel.getpixel((260, 980))
    one_pixel.putpixel((260, 980), (r ^ 1, g, b))
    synthetic.append(('one-rgb-bit-on-tile', one_pixel, True, False))
    for name, image, hand, actions in synthetic:
        after = png(image)
        diagnostic = {}
        changes = friend_frame_changes(before, after, report=reports['line28-source'], diagnostic=diagnostic)
        assert changes['hand'] is hand and changes['actions'] is actions, (name, changes)
        assert not friend_frame_stable(before, after)
        guards = guard_results(before, after, reports['line28-source'])
        if name != 'one-rgb-bit-on-tile':
            assert not any(guards[k]['accepted'] for k in ('kita', 'draw', 'pon')), guards
            assert not guards['refreshInitialEligibility'], guards
        results.append({'guards': guards, 'name': name, 'kind': 'synthetic-negative-from-saved-image', 'changes': changes, 'diagnostic': diagnostic, 'fullFrameRejected': True})
    return {'offlineOnly': True, 'sourceSettings': manifest['sourceSettings'], 'cases': results,
            'limitations': ['No live match or ranked evaluation performed.',
                            'Real button disappearance coincides with tile replacement; isolated button case is synthetic.',
                            'Full-frame rejection remains even when hand background attribution is corrected.',
                            'Finite saved fixtures do not prove all future tile/button changes are detected.',
                            'Historical refresh baseline and confirmation bytes cannot be reconstructed from their hashes.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path)
    args = parser.parse_args()
    print(json.dumps(replay(args.source_root), ensure_ascii=False, indent=2))
