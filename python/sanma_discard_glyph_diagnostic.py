"""Offline, untrusted pixel evidence for comparing a selected tile and own river.

This deliberately does not certify a discard or authorize any operation. Even a
close match does not establish the turn, the completeness of the river, or the
cause of an observed tile appearing. The score is not a probability.
"""
import hashlib
import io
import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


def _read_receipt(path):
    receipt = json.loads(Path(path).read_text())
    screenshot = Path(receipt['screenshot'])
    if not screenshot.is_absolute():
        screenshot = Path(path).parent / screenshot
    frame = screenshot.read_bytes()
    digest = hashlib.sha256(frame).hexdigest()
    source = receipt['sourceObservation']
    river = source['ownRiver']
    if (receipt.get('digest') != digest or source.get('digest') != digest
            or river.get('frameSha256') != digest
            or river.get('scope') != 'offline_untrusted_sanma_own_river'
            or river.get('verified') is not False or river.get('complete') is not False
            or river.get('operationAuthorized') is not False
            or not isinstance(river.get('candidates'), list)):
        raise ValueError('unbound or invalid untrusted observation')
    image = Image.open(io.BytesIO(frame)).convert('RGB')
    if image.size != (1920, 1080):
        raise ValueError('unsupported image size')
    return receipt, river['candidates'], image


def _rect(item, image):
    if not isinstance(item, dict):
        raise ValueError('missing rectangle')
    values = [item.get(k) for k in ('x', 'y', 'width', 'height')]
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in values):
        raise ValueError('invalid rectangle')
    x, y, w, h = values
    if w < 20 or h < 20 or x < 0 or y < 0 or x + w > image.width or y + h > image.height:
        raise ValueError('rectangle outside image')
    return x, y, w, h


def _glyph(image, rect, hand):
    x, y, w, h = _rect(rect, image)
    # Fixed inward margins remove tile borders. This has not been calibrated
    # across tile skins, lighting, orientation, or empty/white faces.
    if hand:
        margins = (.065, .152, .087, .133)
    else:
        margins = (.08, .075, .08, .075)
    l, t, r, b = margins
    crop = image.crop((round(x+w*l), round(y+h*t), round(x+w*(1-r)), round(y+h*(1-b))))
    mask = crop.convert('L').point(lambda pixel: 255 if pixel < 145 else 0)
    bounds = mask.getbbox()
    if bounds is None:
        return None
    mask = mask.crop(bounds)
    # A nearly empty/solid mask is not a usable glyph.
    occupancy = ImageStat.Stat(mask).mean[0] / 255
    if not .03 <= occupancy <= .90:
        return None
    return mask.resize((64, 64), Image.Resampling.NEAREST)


def compare(before_path, after_path, index):
    before, old, before_image = _read_receipt(before_path)
    after, new, after_image = _read_receipt(after_path)
    geometry = before['sourceObservation']['report']['handGeometry']
    if geometry.get('status') != 'candidate' or type(index) is not int:
        raise ValueError('unavailable hand geometry or selected index')
    value = geometry['value']
    slots = [*value['handSlots'], value['drawSlot']]
    if not 0 <= index < len(slots):
        raise ValueError('selected index out of range')
    # Candidate order and completeness are not verified, so even exact prefix
    # and single append are only observations, never proof of a discard.
    def descriptor(item):
        if not isinstance(item, dict) or item.get('verified') is not False or not isinstance(item.get('tile'), str):
            raise ValueError('invalid river candidate')
        _rect(item, after_image)
        return (item['tile'], item['x'], item['y'], item['width'], item['height'])
    previous = [descriptor(item) for item in old]
    current = [descriptor(item) for item in new]
    appended = (before['digest'] != after['digest']
                and len(current) == len(previous) + 1 and current[:-1] == previous)
    selected = _glyph(before_image, slots[index], True)
    added = _glyph(after_image, new[-1], False) if appended else None
    distance = (ImageStat.Stat(ImageChops.difference(selected, added)).mean[0] / 255
                if selected is not None and added is not None else None)
    return {'scope': 'offline_untrusted_sanma_discard_glyph_diagnostic',
            'operationAuthorized': False, 'confirmed': False,
            'beforeDigest': before['digest'], 'afterDigest': after['digest'],
            'selectedIndex': index, 'oldCandidateCount': len(old), 'newCandidateCount': len(new),
            'exactSingleAppendCandidate': appended,
            'appendedTileCandidate': new[-1]['tile'] if appended else None,
            'glyphDistance': distance,
            'limitations': ['candidate lists may omit or mislabel tiles',
                            'same glyph does not establish timing, turn, or input causality',
                            'mask and geometry require independent calibration; blank faces unresolved']}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before_receipt')
    parser.add_argument('after_receipt')
    parser.add_argument('--index', type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(compare(args.before_receipt, args.after_receipt, args.index), ensure_ascii=False))


if __name__ == '__main__':
    main()
