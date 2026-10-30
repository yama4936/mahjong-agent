"""Untrusted screenshot candidates for the opposite player's first north.

One 1920x1080 game, one screen position and one glyph template only. A glyph
match is not a verified count, seat, game phase, extraction or game mode.
"""
from hashlib import sha256
from pathlib import Path


def opposite_north_candidate(image_path: Path, template_path: Path) -> dict:
    import cv2
    scope = {'scope': 'sanma_offline_opposite_north_visual_candidate',
             'verified': False, 'complete': False, 'status': 'unknown'}
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
    if image is None or image.shape != (1080, 1920):
        return {**scope, 'reason': 'uncalibrated_or_unreadable_image'}
    if template is None or template.shape != (29, 40) or template.std() < 5:
        return {**scope, 'reason': 'uncalibrated_or_unreadable_template'}
    roi = image[88:150, 510:610]
    scores = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
    _, value, _, (x, y) = cv2.minMaxLoc(scores)
    x, y = x + 510, y + 88
    # Narrowly calibrated from one observed visible north; a match elsewhere
    # cannot be confidently attributed to the opponent's extracted row.
    candidate = {'x': x, 'y': y, 'similarity': float(value)} if (
        value >= 0.97 and abs(x - 535) <= 4 and abs(y - 101) <= 4) else None
    return {**scope, 'candidate': candidate,
            'frame_sha256': sha256(Path(image_path).read_bytes()).hexdigest()}
