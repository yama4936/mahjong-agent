"""Compare experimental friend frames, ignoring only the on-screen clock.

A match is only visual stability of the visible areas, never proof of turn,
room or action. The fixed rectangle can hide other information underneath it.
"""
import io
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
