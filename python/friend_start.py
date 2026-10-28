"""Fail-closed verification of a manually reviewed friend-room preflight."""

import base64
import io

from PIL import Image, ImageChops, ImageStat

# Fixed, low-resolution static UI signatures from a verified native 1920x1080
# friend-room frame: Japanese heading and orange start control. The independent
# preflight additionally binds the room ID, settings and all player slots.
_CONTROLS = (
    ((190, 45, 360, 115), "NycyOCg0NSUyMSIyNCQ0Nyg3OSk4Oio5NCU2OSg4OSk4NiY2MyU1NCQ2MiQ0MSMzFREkDAohUkNDVkZHSjxCLSQ0GRMqIxsvc11UJRwyGxUvMCY3RzlAW0lIWUhIU0RGIBoqf2dWyqR6v5x1oIJoU0NEFRApOS05wJx2KiEzGRMtYU5MvJl0t5VyrY1umHxjGxYoUkND0Kp9p4hqemNWGRIqGBIrbVlRvpt1HRYtGRMsgmlazad8w593x6J5dmBUFBAlVUVEx6J5wZ12dl9TGhQqIhovqIhrwJx2Z1NNFRApW0lIyKN5qoptmXxlim9dHxkrlnpib1pQ16+Ab1lRGBIpXUtJkXVhOy46vZp1QjQ+Tz9EtpVxdl9WtJNxnH5lKSIuSjw+Y1BLTj5DnX9mOi46WUdHMiY1IBgvX0xMc11WIhozZlJPZVFPWUdJjXNgGhUlFhIkGBMnHBYrJx0xKB4wIhguJBovJhwwJBswKh81LSI2Kh80KiA1JBsxKB4y"),
    ((1000, 955, 1280, 1040), "sYhj/Mxi+8lg+8lg+8lg+8lg+8lg+8lg+8lg+8lg+8lg+8lg+8lg+8lg/cxhw5tm77hY/LtF+7pG+7pG+7pG/bxG/75G/rxG/LtG/bxG/LtG+7pG+7pG+7pG+7pF+b5T7a1O+LBC97BD97BD+bFD3p5DrXtCuIJC5aND0ZRD6qZD+bFD97BD97BD969C9rJK6J9H9KQ+86M+86Q++Kc/uHw8dk84lGM6rXU6h1w5voE796Y/86Q+86M+86M+8aRE45I/75g57pc57pc585o6vHg0ZkMrmWIxiVgvbEYsomgy8po67pc57pc57pc57Jc93oU36ow06Ys06Ys07o01uG4tgk4mkFcop2QrbkIjoWAr74416Ys06os06os054o22Xkw54Ew5YAw5YAw5oEw4X4v4H0v2Hku5YAw3Hsv4H4v5oAw5YEw5YAw5oEw4n4wn1Mq4Xgs33cs33cs33cs4Hgs4Hgs4Xgs4Hcs4Xgt4Hgs33cs33cs33cs4ngss10p"),
)
_BOUND_REGIONS = (
    (700, 40, 1100, 120), (1610, 175, 1870, 900),
    (80, 650, 440, 910), (470, 650, 830, 910),
    (850, 650, 1210, 910), (1230, 650, 1590, 910),
    (1000, 955, 1280, 1040),
)


def verified_friend_room(frame: bytes, reviewed_preflight: bytes) -> bool:
    """Bind current room to a separately reviewed image; fail closed.

    The preflight must be supplied explicitly by the caller after inspecting
    its settings. Matching the static heading and button prevents a generic
    matchmaking or game screen from authorizing the start click.
    """
    try:
        with Image.open(io.BytesIO(frame)) as source:
            current = source.convert("RGB")
        with Image.open(io.BytesIO(reviewed_preflight)) as source:
            reviewed = source.convert("RGB")
        if current.size != (1920, 1080) or reviewed.size != current.size:
            return False
        for box, encoded in _CONTROLS:
            reference = Image.frombytes("RGB", (16, 8), base64.b64decode(encoded))
            for image in (current, reviewed):
                observed = image.crop(box).resize((16, 8))
                if sum(ImageStat.Stat(ImageChops.difference(observed, reference)).mean) / 3 > 5:
                    return False
        for box in _BOUND_REGIONS:
            left = current.crop(box)
            right = reviewed.crop(box)
            # Text changes occupy only a small portion of a panel. Compare
            # tightly tiled patches so a changed digit cannot be averaged out
            # across the surrounding dark background.
            for y in range(0, left.height, 16):
                for x in range(0, left.width, 16):
                    tile = (x, y, min(x + 16, left.width), min(y + 16, left.height))
                    delta = ImageChops.difference(left.crop(tile), right.crop(tile))
                    if sum(ImageStat.Stat(delta).mean) / 3 > 3:
                        return False
        return True
    except (OSError, ValueError):
        return False


def await_reviewed_friend_room(page, reviewed_preflight: bytes, *, attempts: int = 8) -> int:
    """Require two consecutive fresh matches; retry transient visual overlays.

    Each capture independently passes all existing strict checks. A mismatch
    clears the streak; no accumulated or majority evidence authorizes a click.
    """
    streak = 0
    for index in range(attempts):
        frame = page.screenshot(animations="disabled")
        streak = streak + 1 if verified_friend_room(frame, reviewed_preflight) else 0
        if streak == 2:
            return index + 1
        if index + 1 < attempts:
            page.wait_for_timeout(100)
    raise RuntimeError("friend room did not match reviewed preflight in consecutive captures")
