"""Offline, narrow visual cue for the recorded three-player East friend result.

Unknown layouts deliberately remain unknown; this is not player-count OCR.
"""
from pathlib import Path
from PIL import Image, ImageChops, ImageStat, UnidentifiedImageError

REFERENCE = Path(__file__).resolve().parents[1] / 'test/fixtures/sanma-result'
REGIONS = {'end': (886, 60, 992, 120), 'third': (960, 606, 1025, 715),
           'mode': (52, 190, 290, 225), 'no_fourth': (1050, 790, 1130, 915)}


def detect_sanma_friend_result(image_path: str | Path) -> dict:
    try:
        with Image.open(image_path) as source:
            image = source.convert('RGB')
        if image.size != (1920, 1080):
            return {'status': 'unknown', 'reason': 'unsupported_dimensions'}
        differences = {}
        for name, box in REGIONS.items():
            with Image.open(REFERENCE / f'{name}.png') as reference:
                delta = ImageChops.difference(image.crop(box), reference.convert('RGB'))
                differences[name] = sum(ImageStat.Stat(delta).mean) / 3
        if all(value <= 2 for value in differences.values()):
            return {'status': 'sanma_friend_east_result_candidate', 'differences': differences}
        return {'status': 'unknown', 'reason': 'unmatched_visual_evidence', 'differences': differences}
    except (OSError, ValueError, UnidentifiedImageError):
        return {'status': 'unknown', 'reason': 'invalid_image_or_reference'}
