"""Offline pixel-only physical self-river trajectory diagnostic.

The fixed layout and thresholds are experimental, not calibrated for gameplay.
A detected change does not identify a tile, establish a turn, or authorize input.
"""
import hashlib
import io
import json
from pathlib import Path
from PIL import Image, ImageChops, ImageStat

WIDTH, HEIGHT = 1920, 1080
# Six physical slots on each of three rows, for the documented 1920x1080 view.
SLOTS = tuple((768 + x * 62, 544 + y * 70, 830 + x * 62, 614 + y * 70)
              for y in range(3) for x in range(6))


def _load(path):
    data = Path(path).read_bytes()
    with Image.open(io.BytesIO(data)) as original:
        if original.size != (WIDTH, HEIGHT):
            raise ValueError('unsupported image dimensions')
        image = original.convert('RGB')
    return image, hashlib.sha256(data).hexdigest()


def _cell(image, box):
    crop = image.crop(box)
    pixels = list(crop.getdata())
    bright = sum(min(p) > 150 for p in pixels) / len(pixels)
    blue = sum(p[2] > p[0] * 1.3 and p[2] > p[1] * 1.2 and p[2] > 65 for p in pixels) / len(pixels)
    # Reject uncertain/occluded/cropped cells instead of guessing. These
    # thresholds merely describe two observed client backgrounds.
    state = 'tile' if bright >= .45 and blue < .2 else 'empty' if blue >= .7 and bright < .02 else 'unknown'
    return {'state': state, 'brightFraction': round(bright, 5), 'blueFraction': round(blue, 5)}


def compare(before_path, after_path):
    before, before_digest = _load(before_path)
    after, after_digest = _load(after_path)
    old = [_cell(before, box) for box in SLOTS]
    new = [_cell(after, box) for box in SLOTS]
    differences = [round(sum(ImageStat.Stat(ImageChops.difference(before.crop(box), after.crop(box))).mean) / 3, 5)
                   for box in SLOTS]
    old_states = [c['state'] for c in old]
    new_states = [c['state'] for c in new]
    appended = [i for i, (a, b) in enumerate(zip(old_states, new_states)) if a == 'empty' and b == 'tile']
    existing_unchanged = all(differences[i] <= 5 for i, a in enumerate(old_states) if a == 'tile')
    exact = (before_digest != after_digest and len(appended) == 1
             and 'unknown' not in old_states and 'unknown' not in new_states
             and all(a == b for i, (a, b) in enumerate(zip(old_states, new_states)) if i != appended[0])
             and existing_unchanged)
    return {'scope': 'offline_untrusted_physical_river_cells', 'confirmed': False,
            'operationAuthorized': False, 'beforeSha256': before_digest, 'afterSha256': after_digest,
            'beforeCells': old, 'afterCells': new, 'cellMeanPixelDelta': differences,
            'emptyToTileIndices': appended, 'existingTilesUnchangedCandidate': existing_unchanged,
            'singlePhysicalAppendCandidate': exact,
            'limitations': ['fixed geometry and experimental color thresholds', 'no tile identity or selection matching',
                            'same round, timing, calls and action causality not established',
                            'not calibrated across layouts, skins, lighting, animation or occlusion']}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before'); parser.add_argument('after')
    args = parser.parse_args()
    print(json.dumps(compare(args.before, args.after), indent=2))


if __name__ == '__main__':
    main()
