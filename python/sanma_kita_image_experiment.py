"""Offline positive-only image evidence for the self-player's extracted north.

A match merely identifies a visually similar glyph in a position seen in one
friend game; it is neither complete counts nor game-mode/screen recognition.
This module is not connected to live play.
"""
from pathlib import Path
from hashlib import sha256
import math


def detect_own_north_candidates(image_path: Path, template_path: Path) -> dict:
    import cv2
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
    base = {'verified': False, 'scope': 'sanma_offline_own_north_visual_candidates'}
    if image is None or image.shape != (1080, 1920):
        return {**base, 'reason': 'uncalibrated_or_unreadable_image'}
    if template is None or template.shape != (54, 53) or template.std() < 5:
        return {**base, 'reason': 'uncalibrated_or_unreadable_template'}
    # A matched glyph is not proof of ownership, completeness, game phase or
    # game mode. In particular a countdown may occlude part of the row.
    roi = image[750:860, 1180:1490]
    scores = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
    matches = []
    for _ in range(4):
        _, value, _, (x, y) = cv2.minMaxLoc(scores)
        if value < 0.97:
            break
        matches.append({'x': x + 1180, 'y': y + 750, 'similarity': float(value)})
        cv2.rectangle(scores, (x - 40, y - 30), (x + 40, y + 30), -1, -1)
    return {**base, 'matches': matches, 'complete': False,
            'frame_sha256': sha256(Path(image_path).read_bytes()).hexdigest()}


def detect_own_partial_north_candidate(image_path: Path, template_path: Path) -> dict:
    """Unverified visible left part of the north/clock overlap, not a count."""
    from PIL import Image, ImageChops, ImageStat
    base = {'scope': 'sanma_offline_own_partial_north_visual_candidate',
            'status': 'unknown', 'verified': False, 'complete': False}
    try:
        with Image.open(image_path) as image, Image.open(template_path) as reference:
            if image.size != (1920, 1080) or reference.size != (35, 85):
                return {**base, 'reason': 'uncalibrated_dimensions'}
            visible = image.convert('RGB').crop((1390, 765, 1425, 850))
            delta = ImageChops.difference(visible, reference.convert('RGB'))
            score = 1 - sum(ImageStat.Stat(delta).mean) / 765
        candidate = {'x': 1390, 'y': 765, 'similarity': score, 'verified': False} if score >= .995 else None
        return {**base, 'candidate': candidate, 'frame_sha256': sha256(Path(image_path).read_bytes()).hexdigest(),
                'reason': 'partially occluded visual candidate; hidden contents and count unknown'}
    except (OSError, ValueError):
        return {**base, 'reason': 'uncalibrated_or_unreadable_image'}


def compare_own_north_candidate_frames(previous: dict, current: dict, *,
                                       previous_hand_id: str | None, current_hand_id: str | None,
                                       previous_index: int, current_index: int) -> dict:
    """Compare two untrusted candidate sets from a single externally identified hand.

    These are repeated glyph matches, not independently verified extracted
    tiles. Missing candidates may be occluded; stable candidates may be false.
    Never use these data to authorize an action or populate a verified count.
    """
    unknown = {'verified': False, 'complete': False,
               'scope': 'sanma_offline_paired_north_visual_candidates'}
    if (not isinstance(previous_hand_id, str) or not previous_hand_id.strip()
            or current_hand_id != previous_hand_id
            or type(previous_index) is not int or type(current_index) is not int
            or previous_index < 0 or current_index <= previous_index):
        return {**unknown, 'reason': 'hand_identity_or_frame_order_unknown'}

    def slots(observation):
        if (not isinstance(observation, dict)
                or observation.get('scope') != 'sanma_offline_own_north_visual_candidates'
                or observation.get('verified') is not False or observation.get('complete') is not False
                or not isinstance(observation.get('matches'), list) or len(observation['matches']) > 4
                or not isinstance(observation.get('frame_sha256'), str)
                or len(observation['frame_sha256']) != 64):
            return None
        result = set()
        for match in observation['matches']:
            if not isinstance(match, dict) or set(match) != {'x', 'y', 'similarity'}:
                return None
            x, y, score = match['x'], match['y'], match['similarity']
            if (type(x) is not int or type(y) is not int or type(score) is not float
                    or not math.isfinite(score) or not 0.97 <= score <= 1.0):
                return None
            # Measured fixed 1920x1080 self extraction row. Similarity alone
            # anywhere in the ROI is insufficient evidence of a row slot.
            slot = round((1395 - x) / 67)
            if not 0 <= slot <= 3 or abs(x - (1395 - slot * 67)) > 4 or abs(y - 775) > 4 or slot in result:
                return None
            result.add(slot)
        return result

    before, after = slots(previous), slots(current)
    if before is None or after is None:
        return {**unknown, 'reason': 'invalid_or_uncalibrated_candidate'}
    if previous['frame_sha256'] == current['frame_sha256']:
        return {**unknown, 'reason': 'duplicate_frame'}
    return {**unknown, 'hand_id': previous_hand_id,
            'previous_frame_index': previous_index, 'current_frame_index': current_index,
            'stable_candidate_slots': sorted(before & after),
            'previous_only_candidate_slots': sorted(before - after),
            'current_only_candidate_slots': sorted(after - before)}
