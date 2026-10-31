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


def friend_frame_changes(before: bytes, after: bytes) -> dict[str, bool]:
    with Image.open(io.BytesIO(before)) as a, Image.open(io.BytesIO(after)) as b:
        if a.size != (1920, 1080) or b.size != a.size:
            raise ValueError('unreviewed screenshot dimensions')
        delta = ImageChops.difference(a.convert('RGB'), b.convert('RGB'))
        clock_changed = delta.crop(CLOCK_RECT).getbbox() is not None
        delta.paste((0, 0, 0), CLOCK_RECT)
        regions = {'hand':(180,865,1650,1080),'actions':(600,785,1425,875),
                   'fullFrame':(0,0,1920,1080)}
        changes = {name: delta.crop(box).getbbox() is not None for name,box in regions.items()}
        return {**changes, 'clock':clock_changed}


def friend_frame_stable(before: bytes, after: bytes) -> bool:
    return not friend_frame_changes(before, after)['fullFrame']


def latch_friend_action_target(operator, frame: bytes, action: str) -> str:
    """Suppress repeated input on the same visible target, without claiming success."""
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
    attempted = getattr(operator, "_sanma_friend_attempted_targets", None)
    if not isinstance(attempted, set):
        attempted = set()
        operator._sanma_friend_attempted_targets = attempted
    if key in attempted:
        raise RuntimeError("sanma action target already attempted; outcome unknown")
    attempted.add(key)
    return key


def friend_action_started_at(operator):
    """Prefer first observation; older standalone callers use session anchor."""
    observed = getattr(operator, "sanma_friend_action_observed_at", None)
    return observed if type(observed) in (int, float) else getattr(operator, "verified_friend_300_started_at", None)
