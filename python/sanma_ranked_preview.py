"""Offline-only ranked room candidate inspection; never authorize a click.

The references are crops from one 1920x1080 Bronze room capture. This is an
experimental screen aid, not a general room/rank recognizer or a live safety
gate. In particular it does not detect overlays, current account rank or
whether an input would be accepted.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from PIL import Image, ImageChops, ImageStat

_ROOT = Path(__file__).resolve().parent.parent / 'templates' / 'screens'
_REGIONS = {
    'bronze': ((1320, 245, 1490, 295), 'sanma-rank-bronze-label.png'),
    'yonma_east': ((1270, 360, 1530, 440), 'sanma-rank-yonma-east-label.png'),
    'sanma_east': ((1270, 690, 1530, 770), 'sanma-rank-sanma-east-label.png'),
    'sanma_frame': ((1130, 660, 1250, 815), 'sanma-rank-sanma-east-frame.png'),
}

@dataclass(frozen=True)
class RankedPreview:
    candidate: bool
    distances: dict[str, float]
    # Explicit invariant: this module cannot grant permission for live clicks.
    click_permitted: bool = False


def inspect_bronze_sanma_east(image: Image.Image) -> RankedPreview:
    """Compare the labels at their reviewed positions in a native frame.

    Caller must not use this as a live control decision. Missing templates and
    wrong sizes raise or return no candidate rather than inventing a target.
    """
    if image.size != (1920, 1080):
        return RankedPreview(False, {})
    image = image.convert('RGB')
    distances = {}
    for name, (box, filename) in _REGIONS.items():
        with Image.open(_ROOT / filename) as reference:
            mean = ImageStat.Stat(ImageChops.difference(image.crop(box), reference.convert('RGB'))).mean
        distances[name] = sum(mean) / (3 * 255)
    return RankedPreview(all(distance < .025 for distance in distances.values()), distances)
