"""Positive-only, unverified physical right-side north glyph candidates."""
from hashlib import sha256
from pathlib import Path


def right_north_candidate(image_path: Path, templates: list[Path]) -> dict:
    import cv2
    base = {'scope': 'sanma_offline_right_north_visual_candidates',
            'status': 'unknown', 'verified': False, 'complete': False}
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None or image.shape != (1080, 1920):
        return {**base, 'reason': 'uncalibrated_or_unreadable_image'}
    boxes = ((1410, 214, 1455, 239), (1418, 247, 1463, 272))
    if len(templates) != len(boxes):
        return {**base, 'reason': 'uncalibrated_templates'}
    candidates = []
    for slot, (path, (x0, y0, x1, y1)) in enumerate(zip(templates, boxes)):
        reference = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if reference is None or reference.shape != (25, 45) or reference.std() < 5:
            return {**base, 'reason': 'uncalibrated_templates'}
        search = image[y0-2:y1+2, x0-2:x1+2]
        score = float(cv2.matchTemplate(search, reference, cv2.TM_CCOEFF_NORMED).max())
        if score >= .99:
            candidates.append({'slot': slot, 'x': x0, 'y': y0, 'similarity': score, 'verified': False})
    return {**base, 'candidates': candidates,
            'frame_sha256': sha256(Path(image_path).read_bytes()).hexdigest(),
            'reason': 'fixed visual candidates only; missing or obscured tiles remain unknown'}
