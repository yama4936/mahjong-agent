"""Compare experimental friend frames, ignoring only the on-screen clock.

A match is only visual stability of the visible areas, never proof of turn,
room or action. The fixed rectangle can hide other information underneath it.
"""
import io
import hashlib
from PIL import Image, ImageChops

# Native 1920x1080 countdown, outside the action row and hand tile rectangles.
# Its underlying pixels are unobserved; never infer their content.
CLOCK_RECT = (1425, 755, 1650, 870)


# Reviewed neutral closed-hand geometry from evidence187. Unknown/melded/raised
# layouts retain the broad legacy diagnostic. These rectangles never authorize input.
HAND_ENVELOPE = (180, 865, 1650, 1080)
REVIEWED_HAND_SLOTS = tuple(
    (x, 921, width, 151) for x, width in
    ((223,92),(317,93),(412,93),(507,93),(602,92),(697,92),(792,92),
     (887,92),(981,93),(1076,93),(1171,93),(1266,93),(1361,92),(1486,92))
)


def _reviewed_hand_boxes(before, report):
    """Bind diagnostic geometry to the exact original image; fail conservatively."""
    try:
        if report['digest'] != hashlib.sha256(before).hexdigest():
            return None
        geometry = report['handGeometry']
        value = geometry['value']
        if (geometry['status'] != 'candidate'
                or value['viewport'] != {'width':1920, 'height':1080}
                or len(value['handSlots']) != 13):
            return None
        slots = value['handSlots'] + [value['drawSlot']]
        coordinates = tuple(tuple(slot[k] for k in ('x','y','width','height')) for slot in slots)
        if (any(type(v) is not int for slot in coordinates for v in slot)
                or coordinates != REVIEWED_HAND_SLOTS):
            return None
        return [(x,y,x+w,y+h) for x,y,w,h in coordinates]
    except (KeyError, TypeError):
        return None


def friend_frame_changes(before: bytes, after: bytes, *, report=None, diagnostic=None) -> dict[str, bool]:
    """Exact RGB changes; only reviewed, image-bound geometry refines hand attribution.

    fullFrame remains the original strict guard. A false hand flag cannot establish
    unchanged tiles in an unknown layout, nor permit background changes or input.
    """
    with Image.open(io.BytesIO(before)) as a, Image.open(io.BytesIO(after)) as b:
        if a.size != (1920, 1080) or b.size != a.size:
            raise ValueError('unreviewed screenshot dimensions')
        delta = ImageChops.difference(a.convert('RGB'), b.convert('RGB'))
        clock_changed = delta.crop(CLOCK_RECT).getbbox() is not None
        delta.paste((0, 0, 0), CLOCK_RECT)
        regions = {'hand':HAND_ENVELOPE,'actions':(600,785,1425,875),
                   'fullFrame':(0,0,1920,1080)}
        changes = {name: delta.crop(box).getbbox() is not None for name,box in regions.items()}
        boxes = _reviewed_hand_boxes(before, report)
        envelope_changed = changes['hand']
        if boxes is not None:
            changes['hand'] = any(delta.crop(box).getbbox() is not None for box in boxes)
        if diagnostic is not None:
            outside = delta.crop(HAND_ENVELOPE)
            if boxes is not None:
                for x,y,right,bottom in boxes:
                    outside.paste((0,0,0), (x-180,y-865,right-180,bottom-865))
            diagnostic.update(
                geometryStatus='reviewed_image_bound' if boxes is not None else 'unreviewed_fallback',
                handEnvelopeChanged=envelope_changed,
                handTilesChanged=changes['hand'] if boxes is not None else None,
                handOutsideTilesChanged=outside.getbbox() is not None if boxes is not None else None,
                handRectangles=[list(box) for box in boxes] if boxes is not None else [],
                comparison='exact_rgb', operationAuthorized=False,
            )
        return {**changes, 'clock':clock_changed}


def friend_frame_stable(before: bytes, after: bytes) -> bool:
    return not friend_frame_changes(before, after)['fullFrame']


def friend_action_target_key(frame: bytes, action: str) -> str:
    """Return the fingerprint of the visible action target."""
    if action not in ("kita", "tsumo", "ron", "discard", "pass"):
        raise ValueError("unknown friend action")
    with Image.open(io.BytesIO(frame)) as image:
        if image.size != (1920, 1080):
            raise ValueError("unreviewed screenshot dimensions")
        image = image.convert("RGB")
        digest = hashlib.sha256(action.encode("ascii"))
        digest.update(image.crop((600, 785, 1425, 875)).tobytes())
        if action == "discard":
            digest.update(image.crop((180, 870, 1650, 1080)).tobytes())
        key = digest.hexdigest()
    return key


def latch_friend_action_target(operator, frame: bytes, action: str) -> str:
    """Suppress repeated input on the same visible target, without claiming success."""
    check_friend_recovery_guard(operator)
    key = friend_action_target_key(frame, action)
    attempted = getattr(operator, "_sanma_friend_attempted_targets", None)
    if not isinstance(attempted, set):
        attempted = set()
        operator._sanma_friend_attempted_targets = attempted
    if key in attempted:
        raise RuntimeError("sanma action target already attempted; outcome unknown")
    attempted.add(key)
    return key


def check_friend_recovery_guard(operator):
    """Preserve the previous input's bounds until the first resumed click."""
    guard = getattr(operator, '_sanma_friend_resume_guard', None)
    if guard is None:
        return
    import time
    watch, started, deadline = guard
    if (getattr(operator, 'verified_friend_300_active', False) is not True
            or not watch.alive() or not 0 <= (time.monotonic() - started) * 1000 < deadline):
        raise RuntimeError('discard recovery continuity or original deadline lost')


def friend_action_started_at(operator):
    """Prefer first observation; older standalone callers use session anchor."""
    observed = getattr(operator, "sanma_friend_action_observed_at", None)
    return observed if type(observed) in (int, float) else getattr(operator, "verified_friend_300_started_at", None)
