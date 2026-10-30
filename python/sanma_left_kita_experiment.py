"""Experimental visual candidate for the first left-opponent north.

The location and glyph crop come from one 1920x1080 friend match. This does
not establish game type, screen state, player, actual count, or extraction.
"""
from hashlib import sha256
from pathlib import Path


def left_north_candidate(image_path: Path, template_path: Path) -> dict:
    import cv2
    base = {'scope': 'sanma_offline_left_north_visual_candidate',
            'status': 'unknown', 'verified': False, 'complete': False}
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
    if image is None or image.shape != (1080, 1920):
        return {**base, 'reason': 'uncalibrated_or_unreadable_image'}
    if template is None or template.shape != (48, 85) or template.std() < 5:
        return {**base, 'reason': 'uncalibrated_or_unreadable_template'}
    # The calibrated first candidate touches the avatar at x=394. Other
    # placements, overlap, glow and multiple extracts are not established.
    roi = image[680:800, 270:410]
    scores = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
    _, value, _, (x, y) = cv2.minMaxLoc(scores)
    x, y = x + 270, y + 680
    candidate = {'x': x, 'y': y, 'similarity': float(value)} if (
        value >= .97 and abs(x - 305) <= 4 and abs(y - 712) <= 4) else None
    return {**base, 'candidate': candidate,
            'frame_sha256': sha256(Path(image_path).read_bytes()).hexdigest()}
