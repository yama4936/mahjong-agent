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
    # The room-ID glyphs occupy y=65..112. The strip above them contains
    # free-floating animated particles, including in the reviewed preflight;
    # comparing that unrelated strip can reject every subsequent frame.
    # Bind the five room-ID digits, not their decorative label/colon. A
    # particle over the colon in the reviewed 6efe75c frame remained a
    # permanent mismatch after the particle disappeared in all 8 captures.
    (968, 65, 1094, 113), (1610, 175, 1870, 900),
    (80, 650, 440, 910), (470, 650, 830, 910),
    (850, 650, 1210, 910), (1230, 650, 1590, 910),
    (1000, 955, 1280, 1040),
)

# Native 300+0 time label from the independently reviewed friend-room
# preflight. The 5+20 label must not match this template.
_LONG_FRIEND_CLOCK = "FypLFypLFipMFipLJTlZJDdYEydKFipMKjxbGSxMFihJJjhYIjNUFylKFypLEydJFilLFCdJKDpaHC5PGy5POkxrQ1RzEidJP1FwFipMFypLGCtMFSlMFSlMEyhLIjZYXG2LcoGeMUVmTl9+cYCbU2OALj9ecX+abXyXIzVVGCtMJTlZDiNFPlBvcYCbY3KOIzZWbn6ZTmB+N0pqZ3eTQlRzGCtMGCtMFClMFClMFClMFClNHjFVZ3eURVd3bH2ZGi5PbXyXZXSQO0tqUmJ/SFh2MUNiZnaSGi5PbHyXIzZWZXSQPE5sgY+qeomjYXKOWmqIWmuIMkNiFShJFSpQFCpPFSpPECZMMUVoeommQVR0a3uYEydKbHuWcH+ZMkRkSVl4WGeEXG2KiJewQVNybn6aGy9RYHCMO01tf46oeYmkO05uZ3eUU2SDJThZFypMFi5XFi5XFC1VJz5kK0FnT2OEXG+PZniXO09xa3yZUmSEVGaFZHWTOU1vHjRZSF1+CyRLYHOSQ1Z3a3yZP1R2ZHeWPFF0HDNZYXOSVGeIFStRGjBVGDRjGDRjFjJhJ0JuY3mcZHmcITxnMkx1bIGiOlJ4HzljY3iaWG6RHDZgGjRgGDRgFTFdJkFran6gSmGGEi1aQVl/RVyCY3eZVGuPGTRhGjVgGzZh"


def reviewed_friend_clock_is_300_plus_zero(frame: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(frame)) as source:
            image = source.convert("RGB")
        if image.size != (1920, 1080):
            return False
        template = Image.frombytes("RGB", (28, 6), base64.b64decode(_LONG_FRIEND_CLOCK))
        observed = image.crop((1670, 260, 1810, 290)).resize((28, 6))
        return sum(ImageStat.Stat(ImageChops.difference(observed, template)).mean) / 3 <= 3
    except (OSError, ValueError):
        return False


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
                    error = sum(ImageStat.Stat(delta).mean) / 3
                    if error > 3:
                        # A faint particle in the *reviewed* frame caused a
                        # persistent 3.1 delta in the settings panel. Allow
                        # only this small brightness deviation, and only if
                        # the bright glyph bitmap is exactly unchanged.
                        if box != (1610, 175, 1870, 900) or error > 4:
                            return False
                        mask = lambda image: image.crop(tile).convert("L").point(
                            lambda value: 255 if value > 140 else 0,
                        )
                        if ImageChops.difference(mask(left), mask(right)).getbbox() is not None:
                            return False
        return True
    except (OSError, ValueError):
        return False


def await_reviewed_friend_room(page, reviewed_preflight: bytes, *, attempts: int = 8,
                               on_capture=None) -> int:
    """Require two consecutive fresh matches; retry transient visual overlays.

    Each capture independently passes all existing strict checks. A mismatch
    clears the streak; no accumulated or majority evidence authorizes a click.
    """
    streak = 0
    for index in range(attempts):
        frame = page.screenshot(animations="disabled")
        matched = verified_friend_room(frame, reviewed_preflight)
        if on_capture is not None:
            on_capture(index + 1, frame, matched)
        streak = streak + 1 if matched else 0
        if streak == 2:
            return index + 1
        if index + 1 < attempts:
            page.wait_for_timeout(100)
    raise RuntimeError("friend room did not match reviewed preflight in consecutive captures")
