#!/usr/bin/env python3
"""Fail-closed Mahjong Soul browser operator.

Python owns the browser and all mouse input. The TypeScript process is a pure
frame evaluator: it receives a screenshot and returns structured JSON without
touching the page.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from typing import Any, Callable

from playwright.sync_api import Browser, CDPSession, Page, sync_playwright
from PIL import Image, ImageChops, ImageStat
from screen_state import _rgb_fraction, classify_screen, load_references
from operator_lock import OperatorAlreadyRunning, endpoint_key, operator_lease
from analysis_recorder import AnalysisRecorder
from startup_turn_guard import StartupTurnGuard
from friend_start import await_reviewed_friend_room, reviewed_friend_clock_is_300_plus_zero
from screencast_diagnostic import ScreencastDiagnostic


class RetryableSafetyAbort(RuntimeError):
    """A stale pre-click observation that is safe to reevaluate."""


class SelectionStateUncertainAbort(RetryableSafetyAbort):
    """The first discard click may have selected a tile, but not provably.

    Retrying the same click could deselect that tile rather than selecting it.
    The caller must therefore disarm this hand until an independently observed
    state transition, instead of treating this like an ordinary stale frame.
    """


def utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace(":", "-")


BOARD_STATE_REGIONS = (
    # Round, then own/right/opposite/left score glyphs, then counters.
    # Keep each full score inside its plaque, excluding the illuminated rim
    # that changes on every turn even when the numbers remain unchanged.
    (900, 385, 1020, 425), (905, 464, 1015, 495),
    (1035, 370, 1060, 471), (905, 350, 1015, 377),
    (865, 373, 888, 470), (80, 120, 310, 190),
)

# A 2600ms ranked click budget includes the physical pre-click validation and
# mouse dispatch, not merely recognition.  Live measurements show that the
# resident hand worker plus the final evaluator normally complete within about
# 1.8s once the matching board-metadata cache is available.  In ranked play,
# CDP screencast receipts arrived 420--547ms after their capture; demanding
# 2200ms *after* receipt (only 400ms age) rejected every one of those usable
# frames and eventually caused an away/rejoin cycle.  Admit the observed
# delivery range, while keeping the final fail-closed click guard as the
# authority when recognition or pre-click validation takes longer than usual.
# This is deliberately a *start* admission rule, separate from that guard.
FORCE_AUTO_MIN_RECOGNITION_WINDOW_MS = 1800
# This keeps the ranked fast path distinct from 300+0 friend-match regression
# runs, whose 8000ms budget may safely wait for synchronous metadata work.
FORCE_AUTO_SHORT_CLICK_BUDGET_MAX_MS = 2600
# A verified unchanged draw may continue into the game's additional time.
# We do not read the remaining 20-second bank, so never assume it is full:
# bound the observed turn to ten seconds and retain the 2600ms image limit.
FORCE_AUTO_SAME_DRAW_ACTION_BUDGET_MS = 10000
FORCE_AUTO_NORMAL_TURN_BUDGET_MS = 5000
# A discard is a two-input gesture: the first click only raises the selected
# physical tile and a later, observed raised hitbox receives the confirmation
# click.  Do not start that gesture with so little of the short-clock budget
# left that its second input can race the client auto-tsumogiri.
FORCE_AUTO_DISCARD_SELECTION_RESERVE_MS = 650
# Once a possible selected tile has survived into a later observed draw, wait
# briefly for the public worker to corroborate the own river.  If it cannot,
# stop rather than treating draw-slot animation as permission to click again.
SELECTION_UNCERTAINTY_PUBLIC_CONFIRMATION_GRACE_SECONDS = 3.0


def board_state_signature(frame: bytes) -> tuple[Image.Image, ...]:
    """Capture stable score/round HUD regions, excluding the draw counter."""
    with Image.open(io.BytesIO(frame)) as source:
        image = source.convert("RGB")
        return tuple(image.crop(box) for box in BOARD_STATE_REGIONS)


def wall_counter_signature(frame: bytes) -> bytes:
    """Bind cached remainingTiles to the exact observed counter pixels."""
    with Image.open(io.BytesIO(frame)) as source:
        return source.convert("RGB").crop((923, 429, 995, 455)).tobytes()


def board_state_signature_matches(left: tuple[Image.Image, ...],
                                  right: tuple[Image.Image, ...]) -> bool:
    return len(left) == len(right) == len(BOARD_STATE_REGIONS) and all(
        sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3 <= 3.0
        for a, b in zip(left, right)
    )


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_secret_environment(project: Path, env_file: str | None) -> dict[str, str]:
    """Load only Jev settings from a private local env file.

    The values are passed directly to evaluator subprocesses and are never
    included in operator logs or command-line arguments.
    """
    environment = os.environ.copy()
    if not env_file:
        return environment
    path = Path(env_file)
    if not path.is_absolute():
        path = project / path
    if not path.exists():
        return environment
    if not path.is_file():
        raise RuntimeError(f"secret env path is not a regular file: {path}")
    # Windows does not expose POSIX owner/group/other permission semantics.
    # Its synthesized mode bits commonly look group/world-accessible even when
    # the file is protected by an ACL, so this check would reject every normal
    # .env.local file on Windows.
    if sys.platform != "win32" and path.stat().st_mode & 0o077:
        raise RuntimeError(f"secret env file must not be group/world accessible: {path}")
    allowed = {
        "TYPESAFE_API_KEY", "JEV_MODEL", "JEV_FORCE_AUTO_DEADLINE_MS",
        "FORCE_AUTO_CLICK_BUDGET_MS",
    }
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key not in allowed:
            continue
        environment[key] = value.strip().strip("\"'")
    return environment


def with_match_length(state: dict[str, Any], match_length: str | None) -> dict[str, Any]:
    if match_length not in (None, "east", "south"):
        raise ValueError("match length must be east or south")
    return {**state, **({"matchLength": match_length} if match_length is not None else {})}


def configure_evaluator_click_budget(environment: dict[str, str], budget_ms: int | None,
                                     action_deadline_ms: int) -> dict[str, str]:
    if budget_ms is None:
        return environment
    if budget_ms <= 0 or budget_ms > action_deadline_ms:
        raise ValueError("force-auto click budget must be positive and within the action deadline")
    return {**environment, "FORCE_AUTO_CLICK_BUDGET_MS": str(budget_ms)}


def clip_for_hand(layout: dict[str, Any]) -> dict[str, float]:
    slots = [*layout["handSlots"]]
    if layout.get("drawSlot"):
        slots.append(layout["drawSlot"])
    left = min(slot["x"] for slot in slots)
    top = min(slot["y"] for slot in slots)
    right = max(slot["x"] + slot["width"] for slot in slots)
    bottom = max(slot["y"] + slot["height"] for slot in slots)
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def mean_pixel_delta(first: bytes, second: bytes) -> float:
    with Image.open(io.BytesIO(first)) as first_image, Image.open(io.BytesIO(second)) as second_image:
        difference = ImageChops.difference(first_image.convert("RGB"), second_image.convert("RGB"))
        return sum(ImageStat.Stat(difference).mean) / 3


def tile_face_structure_delta(first: bytes, second: bytes, threshold: int = 120) -> float:
    """Percent of dark/light tile-face pixels that changed.

    Three-meld call effects can relight every remaining concealed tile for
    several seconds.  Comparing a dark/light glyph mask ignores that moving
    illumination while still making a changed tile face a large difference.
    """
    with Image.open(io.BytesIO(first)) as first_image, Image.open(io.BytesIO(second)) as second_image:
        first_mask = first_image.convert("L").point(lambda value: 255 if value < threshold else 0)
        second_mask = second_image.convert("L").point(lambda value: 255 if value < threshold else 0)
        difference = ImageChops.difference(first_mask, second_mask)
        return ImageStat.Stat(difference).mean[0] / 255 * 100


def stable_hand_delta(first: bytes, second: bytes, open_melds: int) -> float:
    """Compare equivalent tile faces while ignoring non-semantic relighting.

    Mahjong Soul can relight an otherwise unchanged closed row while an
    opponent's discard/reaction animation completes.  That changed the RGB
    average enough to make the force-auto pre-click guard repeatedly abort a
    still-current draw.  The dark/light glyph structure is stable across that
    effect and still changes materially when a tile face changes.  It is also
    the comparison already used for compact post-call rows.
    """
    return tile_face_structure_delta(first, second)


def closed_hand_face_mismatches(
    evaluated_full: bytes, current_full: bytes, layout: dict[str, Any], threshold: float,
) -> list[dict[str, float | int | None]]:
    """Return changed physical faces for a closed 14-tile row.

    This is deliberately an image identity check, not a second tile-label
    recognition.  A later screencast JPEG may be encoded differently, but its
    per-slot dark/light glyph mask remains stable.  Checking every slot also
    prevents an average over the whole hand from hiding one replaced tile.
    """
    slots = [*layout.get("handSlots", [])]
    draw_slot = layout.get("drawSlot")
    if draw_slot is None:
        return [{"index": -1, "faceStructureDelta": None}]
    slots.append(draw_slot)
    if len(slots) != 14:
        return [{"index": -1, "faceStructureDelta": None}]
    mismatches: list[dict[str, float | int | None]] = []
    try:
        for index, slot in enumerate(slots):
            # Match stable_hand_comparison_region: omit border/shadow and the
            # bottom interaction effect, retaining only the tile glyph.
            face = {
                "x": float(slot["x"]) + 10,
                "y": float(slot["y"]) + 10,
                "width": float(slot["width"]) - 20,
                "height": float(slot["height"]) - 38,
            }
            if face["width"] <= 0 or face["height"] <= 0:
                return [{"index": -1, "faceStructureDelta": None}]
            delta = tile_face_structure_delta(
                crop_screenshot(evaluated_full, face), crop_screenshot(current_full, face),
            )
            if delta > threshold:
                mismatches.append({"index": index, "faceStructureDelta": round(delta, 3)})
    except Exception:
        # An unreadable or incorrectly sized frame cannot prove identity.
        return [{"index": -1, "faceStructureDelta": None}]
    return mismatches


def crop_screenshot(screenshot: bytes, clip: dict[str, float]) -> bytes:
    """Crop a PNG in memory so one CDP capture can serve several checks."""
    with Image.open(io.BytesIO(screenshot)) as image:
        cropped = image.crop((
            int(clip["x"]), int(clip["y"]),
            int(clip["x"] + clip["width"]), int(clip["y"] + clip["height"]),
        ))
        output = io.BytesIO()
        cropped.save(output, format="PNG")
        return output.getvalue()


def crop_screenshot_regions(
    screenshot: bytes, clips: dict[str, dict[str, float]],
) -> dict[str, bytes]:
    """Crop several regions from one decoded screenshot.

    The force-auto pre-click guard needs the hand, stable tile faces and own
    river from the exact same screencast receipt.  Decoding that JPEG once per
    region delays a short-clock click without adding any independent evidence.
    Keeping the crops in this helper preserves the existing pixel checks while
    binding every result to the one immutable source frame.
    """
    result: dict[str, bytes] = {}
    with Image.open(io.BytesIO(screenshot)) as image:
        for name, clip in clips.items():
            cropped = image.crop((
                int(clip["x"]), int(clip["y"]),
                int(clip["x"] + clip["width"]), int(clip["y"] + clip["height"]),
            ))
            output = io.BytesIO()
            # These lossless crops stay in memory for immediate pixel checks.
            # Deflate compression consumes most of the pre-click crop time
            # without changing the evidence; store the same pixels directly.
            cropped.save(output, format="PNG", compress_level=0)
            result[name] = output.getvalue()
    return result


def riichi_selection_is_visible(hand: bytes) -> bool:
    """Recognize the dimmed concealed row shown after pressing Riichi.

    Pressing the orange Riichi affordance does not discard a tile.  It changes
    the row into a selection UI: unavailable faces are neutral grey while the
    ordinary self-turn row is predominantly bright, near-neutral tile faces.
    This is deliberately a *state* signature, rather than accepting any hand
    pixel movement (which could be the next player's animation).
    """
    with Image.open(io.BytesIO(hand)) as image:
        row = image.convert("RGB")
        pixels = list(row.getdata())
    if not pixels:
        return False
    total = len(pixels)
    muted = sum(
        1 for red, green, blue in pixels
        if 60 <= min(red, green, blue) <= 160 and max(red, green, blue) - min(red, green, blue) < 25
    ) / total
    bright_tile_faces = sum(
        1 for red, green, blue in pixels
        if min(red, green, blue) > 180 and max(red, green, blue) - min(red, green, blue) < 60
    ) / total
    # Multiple legal discards remain bright in this UI.  A fixed bright-face
    # ceiling rejects real selections with two candidates; require the muted
    # unavailable faces to dominate the bright selectable faces instead.
    if muted >= 0.45 and muted > bright_tile_faces:
        return True
    # A hand can have many legal declaration discards: in that case the
    # selectable tiles dominate the row and the global muted ratio is small.
    # Require two adjacent, predominantly dim tile-sized bands instead of
    # admitting an arbitrary dark patch.  Ignore the upper/lower margins,
    # which include borders and may vary with the selected tile animation.
    width, height = row.size
    if width < 280 or height < 60:
        return False
    dim_bands = []
    bright_bands = 0
    for index in range(14):
        band = row.crop((round(index * width / 14), round(height * 0.10),
                         round((index + 1) * width / 14), round(height * 0.89)))
        band_pixels = list(band.getdata())
        band_muted = sum(1 for red, green, blue in band_pixels
                         if 60 <= min(red, green, blue) <= 160
                         and max(red, green, blue) - min(red, green, blue) < 25) / len(band_pixels)
        band_bright = sum(1 for red, green, blue in band_pixels
                          if min(red, green, blue) > 180
                          and max(red, green, blue) - min(red, green, blue) < 60) / len(band_pixels)
        # Actual tiles retain glyphs and borders when dimmed. A uniformly grey
        # overlay or rectangle is not sufficient evidence of tile selection.
        textured = ImageStat.Stat(band.convert("L")).stddev[0] >= 15
        dim_bands.append(band_muted >= 0.48 and band_bright < 0.05 and textured)
        bright_bands += band_bright >= 0.40
    return bright_bands >= 3 and any(left and right for left, right in zip(dim_bands, dim_bands[1:]))


def perceptual_hash(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as image:
        pixels = image.convert("L").resize((32, 8)).getdata()
        quantized = bytes(min(15, value // 16) for value in pixels)
    return hashlib.sha256(quantized).hexdigest()


def away_resume_geometry(viewport: dict[str, int]) -> tuple[dict[str, float], dict[str, float]]:
    width, height = viewport["width"], viewport["height"]
    button = {"x": width * 0.422, "y": height * 0.609, "width": width * 0.159, "height": height * 0.073}
    popup = {"x": width * 0.289, "y": height * 0.278, "width": width * 0.425, "height": height * 0.445}
    return button, popup


def fraction_matching(image: Image.Image, predicate: Any) -> float:
    pixels = list(image.convert("RGB").getdata())
    return sum(1 for pixel in pixels if predicate(*pixel)) / max(1, len(pixels))


def is_away_resume_dialog(screenshot: bytes, viewport: dict[str, int]) -> bool:
    button, popup = away_resume_geometry(viewport)
    with Image.open(io.BytesIO(screenshot)) as image:
        button_image = image.crop((button["x"], button["y"], button["x"] + button["width"], button["y"] + button["height"]))
        popup_image = image.crop((popup["x"], popup["y"], popup["x"] + popup["width"], popup["y"] + popup["height"]))
        gold = _rgb_fraction(button_image.convert("RGB"), ((">", 180), (">", 110), ("<", 130)))
        dark = _rgb_fraction(popup_image.convert("RGB"), (("<", 70), ("<", 90), ("<", 120)))
    return gold >= 0.65 and dark >= 0.75


def pass_button_color_fractions(button: Image.Image, *, contextual: bool = False) -> tuple[float, float, float]:
    """Count the existing skip-button predicates with native Pillow masks."""
    pixels = button.convert("RGB")
    dark = _rgb_fraction(pixels, (("<", 80), ("<", 90), ("<", 100)))
    warm = _rgb_fraction(pixels, ((">", 120), (">", 95), ("<", 100)))
    red, green, blue = pixels.split()
    tolerance, blue_limit = (30, 125) if contextual else (25, 120)
    neutral = ImageChops.multiply(
        ImageChops.multiply(
            red.point([255 if value > 110 else 0 for value in range(256)]),
            blue.point([255 if value < blue_limit else 0 for value in range(256)]),
        ),
        ImageChops.difference(red, green).point([
            255 if value < tolerance else 0 for value in range(256)
        ]),
    )
    return dark, warm, neutral.histogram()[255] / max(1, pixels.width * pixels.height)


def is_force_auto_pass_prompt(screenshot: bytes, region: dict[str, float]) -> bool:
    """Recognize the fixed Mahjong Soul skip button without a template set.

    This fallback is restricted to force-auto and is combined with an
    independently recognized 13-tile concealed hand before it can click.
    """
    with Image.open(io.BytesIO(screenshot)) as image:
        button = image.crop((
            region["x"], region["y"],
            region["x"] + region["width"], region["y"] + region["height"],
        ))
        dark, warm, neutral = pass_button_color_fractions(button)
    return dark >= 0.25 and warm >= 0.005 and neutral >= 0.02


def is_force_auto_pass_clip(screenshot: bytes) -> bool:
    with Image.open(io.BytesIO(screenshot)) as image:
        dark, warm, neutral = pass_button_color_fractions(image)
    return dark >= 0.25 and warm >= 0.005 and neutral >= 0.02


def is_contextual_reaction_pass(
    screenshot: bytes, region: dict[str, float], action_button_count: int,
) -> bool:
    """Accept the stylized skip button only beside an independently found action."""
    if action_button_count <= 0:
        return False
    with Image.open(io.BytesIO(screenshot)) as image:
        button = image.crop((
            region["x"], region["y"],
            region["x"] + region["width"], region["y"] + region["height"],
        ))
        dark, _, neutral = pass_button_color_fractions(button, contextual=True)
    return dark >= 0.25 and neutral >= 0.02


def force_auto_call_buttons(screenshot: bytes, viewport: dict[str, int]) -> list[dict[str, Any]]:
    """Locate green/cyan chi/pon/kan buttons without confusing the hand row."""
    left = round(viewport["width"] * 0.30)
    top = round(viewport["height"] * 0.68)
    right = round(viewport["width"] * 0.75)
    # Reaction buttons end above the concealed hand. Keeping this ROI out of
    # the hand row prevents a cyan pon button from joining bamboo tile ink
    # into one oversized component.
    bottom = round(viewport["height"] * 0.85)
    with Image.open(io.BytesIO(screenshot)) as image:
        pixels = image.convert("RGB")
        red, green, blue = pixels.crop((left, top, right, bottom)).split()
        def above(band, threshold):
            return band.point([255 if value > threshold else 0 for value in range(256)])
        def all_masks(*masks):
            result = masks[0]
            for mask in masks[1:]:
                result = ImageChops.multiply(result, mask)
            return result
        # Saturating subtraction preserves every positive threshold exactly.
        # Keep green/cyan separate so touching glows cannot fuse two calls.
        masks = {
            "green": all_masks(above(green, 80), above(ImageChops.subtract(green, red), 15),
                               above(ImageChops.subtract(green, blue), 10)),
            "cyan": all_masks(above(blue, 140), above(green, 120),
                              above(ImageChops.subtract(ImageChops.darker(green, blue), red), 35),
                              above(ImageChops.subtract(blue, green), 0)),
        }
        groups: list[tuple[str, list[tuple[int, int, int]]]] = []
        for palette, mask in masks.items():
            active_columns: list[tuple[int, int, int]] = []
            for x in range(mask.width):
                column = mask.crop((x, 0, x + 1, mask.height))
                if column.histogram()[255] >= 5:
                    bounds = column.getbbox()
                    active_columns.append((left + x, top + bounds[1], top + bounds[3] - 1))
            palette_groups: list[list[tuple[int, int, int]]] = []
            for column in active_columns:
                if not palette_groups or column[0] - palette_groups[-1][-1][0] > 10:
                    palette_groups.append([column])
                else:
                    palette_groups[-1].append(column)
            groups.extend((palette, group) for group in palette_groups)

    buttons = []
    for palette, group in groups:
        x1, x2 = group[0][0], group[-1][0]
        y1 = min(column[1] for column in group)
        y2 = max(column[2] for column in group)
        width = x2 - x1
        if not viewport["width"] * 0.07 <= width <= viewport["width"] * 0.18 \
                or y2 - y1 < viewport["height"] * 0.04:
            continue
        buttons.append({
            "action": "chi" if palette == "green" else "pon",
            "x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1,
            "center": {"x": (x1 + x2) / 2, "y": (y1 + y2) / 2},
        })
    buttons.sort(key=lambda button: button["x"])
    # A cyan glow may include highlights from the neighboring green button.
    # Preserve both candidates by trimming the later box instead of merging
    # them into the dangerous single-call path.
    for previous, current in zip(buttons, buttons[1:]):
        previous_right = previous["x"] + previous["width"]
        if current["x"] <= previous_right:
            current_right = current["x"] + current["width"]
            current["x"] = previous_right + 10
            current["width"] = max(0, current_right - current["x"])
            current["center"]["x"] = current["x"] + current["width"] / 2
    with Image.open(io.BytesIO(screenshot)) as image:
        pixels = image.convert("RGB")
        filtered = []
        for button in buttons:
            crop = pixels.crop((button["x"], button["y"], button["x"] + button["width"], button["y"] + button["height"]))
            magenta = fraction_matching(crop, lambda red, green, blue: red > 100 and blue > 70 and red - green > 25 and blue - green > 10)
            if button["width"] >= viewport["width"] * 0.07 and magenta < 0.015:
                filtered.append(button)
    return filtered


def post_call_transition(call_action: str, prior_open_melds: int) -> dict[str, Any]:
    """Describe the state expected after a verified open call."""
    if call_action not in {"chi", "pon", "minkan"}:
        raise ValueError(f"unsupported open call: {call_action}")
    return {
        "openMelds": min(4, prior_open_melds + 1),
        "dynamicLayoutRequired": True,
        # Chi/pon immediately require a discard. Minkan first produces a
        # replacement draw, which the normal draw-slot gate must observe.
        "pendingPostCallDiscard": call_action in {"chi", "pon"},
    }


def confirmed_call_meld(selected_action: dict[str, Any] | None) -> dict[str, Any] | None:
    """Build typed meld evidence from a call that the UI visibly completed."""
    if not selected_action:
        return None
    # A structural pon/chi can consume either a red or a normal five.
    # Hand/meld pixel changes prove the call, not that physical choice.
    if "consumedTileChoices" in selected_action:
        return None
    action = selected_action.get("action")
    called_tile = selected_action.get("tile")
    consumed = selected_action.get("consumedTiles")
    if action not in {"chi", "pon", "minkan"} or not isinstance(called_tile, str) \
            or not isinstance(consumed, list) or not all(isinstance(tile, str) for tile in consumed):
        return None
    expected_consumed = 3 if action == "minkan" else 2
    if len(consumed) != expected_consumed:
        return None
    return {"type": action, "tiles": [*consumed, called_tile], "confidence": 1.0}


def selected_chi_choice_point(
    points: list[dict[str, float]], selected_action: dict[str, Any] | None,
    legal_actions: list[dict[str, Any]] | None,
) -> dict[str, float] | None:
    """Map Mahjong Soul's left-to-right chi variants to the legal action order."""
    if not points:
        return None
    chi_actions = [action for action in legal_actions or [] if action.get("action") == "chi"]
    selected_id = selected_action.get("id") if selected_action else None
    selected_index = next(
        (index for index, action in enumerate(chi_actions) if action.get("id") == selected_id), None,
    )
    if selected_index is None:
        return points[0] if len(points) == 1 else None
    if len(points) != len(chi_actions) or selected_index >= len(points):
        return None
    return points[selected_index]


def should_retry_call_policy(error: Exception, elapsed_ms: int) -> bool:
    """Retry transient call conflicts briefly, then prefer a safe pass."""
    return str(error) != "reaction_tile_count_conflict" or elapsed_ms < 20000


def force_auto_chi_choice_points(screenshot: bytes, viewport: dict[str, int]) -> list[dict[str, float]]:
    """Locate complete two-tile choices in Mahjong Soul's post-chi selector."""
    left, right = round(viewport["width"] * 0.25), round(viewport["width"] * 0.75)
    top, bottom = round(viewport["height"] * 0.65), round(viewport["height"] * 0.82)
    with Image.open(io.BytesIO(screenshot)) as image:
        pixels = image.convert("RGB")
        active = []
        for x in range(left, right):
            count = 0
            for y in range(top, bottom):
                red, green, blue = pixels.getpixel((x, y))
                if min(red, green, blue) >= 145 and max(red, green, blue) - min(red, green, blue) <= 85:
                    count += 1
            if count >= (bottom - top) * 0.35:
                active.append(x)
    groups: list[list[int]] = []
    for x in active:
        if not groups or x - groups[-1][-1] > 16:
            groups.append([x])
        else:
            groups[-1].append(x)
    points = []
    for group in groups:
        width = group[-1] - group[0]
        if viewport["width"] * 0.07 <= width <= viewport["width"] * 0.13:
            points.append({"x": (group[0] + group[-1]) / 2, "y": (top + bottom) / 2})
    return points


def should_process_reaction_prompt(pending_post_call_discard: bool) -> bool:
    """A verified chi/pon must discard before any new reaction is considered."""
    return not pending_post_call_discard


ACTION_DEADLINE_MS = 5_000


def action_deadline_timing(
    evidence_started_at: float | None, decision_started_at: float | None, clicked_at: float,
    deadline_ms: int = ACTION_DEADLINE_MS,
) -> dict[str, Any]:
    """Return one comparable detect/decide/click clock for every action path."""
    detected = evidence_started_at if evidence_started_at is not None else decision_started_at
    decided = decision_started_at if decision_started_at is not None else clicked_at
    detected = min(detected if detected is not None else clicked_at, clicked_at)
    decided = min(max(decided, detected), clicked_at)
    detection_to_decision_ms = round((decided - detected) * 1000)
    decision_to_click_ms = round((clicked_at - decided) * 1000)
    total_ms = round((clicked_at - detected) * 1000)
    return {
        "deadlineMs": deadline_ms,
        "detectionToDecisionMs": detection_to_decision_ms,
        "decisionToClickMs": decision_to_click_ms,
        "evidenceToClickMs": total_ms,
        "remainingMsAtClick": deadline_ms - total_ms,
        "deadlineMet": total_ms <= deadline_ms,
    }


def should_guard_tenpai_reaction(last_shanten: int | None, call_buttons: list[dict[str, Any]]) -> bool:
    """Keep a possible win prompt untouched, but do not confuse a visible call with ron.

    The green chi/pon/kan buttons are detected independently from the fixed
    pass button.  When at least one of them is present, a pass-only fallback
    is safe even after the previous turn reached tenpai: Mahjong Soul shows
    ron as a separate orange action, not as one of these green call buttons.
    """
    return last_shanten == 0 and not call_buttons


def force_auto_self_action_buttons(screenshot: bytes, viewport: dict[str, int]) -> list[dict[str, Any]]:
    """Locate orange self-turn action buttons (riichi/tsumo/kan/kyuushu)."""
    left = round(viewport["width"] * 0.35)
    top = round(viewport["height"] * 0.68)
    right = round(viewport["width"] * 0.75)
    # The concealed hand starts at roughly 85% of the viewport height. Its
    # orange tile borders otherwise look like a huge riichi/ron button.
    bottom = round(viewport["height"] * 0.85)
    with Image.open(io.BytesIO(screenshot)) as image:
        red, green, blue = image.convert("RGB").crop((left, top, right, bottom)).split()
        def above(band, threshold):
            return band.point([255 if value > threshold else 0 for value in range(256)])
        def all_masks(*masks):
            result = masks[0]
            for mask in masks[1:]:
                result = ImageChops.multiply(result, mask)
            return result
        orange = all_masks(above(red, 120), above(ImageChops.subtract(red, green), 25),
                           above(green, 55), above(ImageChops.subtract(green, blue), 15))
        # For integer green, green >= blue * 0.8 is exactly green >= ceil(...).
        # Saturating subtraction is zero iff that inclusive comparison holds.
        minimum_green = blue.point([ceil(value * 0.8) for value in range(256)])
        green_ratio = ImageChops.subtract(minimum_green, green).point([255] + [0] * 255)
        ron_red = all_masks(above(red, 120), above(ImageChops.subtract(red, green), 60),
                            above(ImageChops.subtract(red, blue), 60), green_ratio)
        mask = ImageChops.lighter(orange, ron_red)
        active_columns: list[tuple[int, int, int]] = []
        for x in range(mask.width):
            column = mask.crop((x, 0, x + 1, mask.height))
            if column.histogram()[255] >= 5:
                bounds = column.getbbox()
                active_columns.append((left + x, top + bounds[1], top + bounds[3] - 1))

    groups: list[list[tuple[int, int, int]]] = []
    for column in active_columns:
        if not groups or column[0] - groups[-1][-1][0] > 10:
            groups.append([column])
        else:
            groups[-1].append(column)
    return [{
        "x": group[0][0], "y": min(column[1] for column in group),
        "width": group[-1][0] - group[0][0],
        "height": max(column[2] for column in group) - min(column[1] for column in group),
        "center": {
            "x": (group[0][0] + group[-1][0]) / 2,
            "y": (min(column[1] for column in group) + max(column[2] for column in group)) / 2,
        },
    } for group in groups
        if group[-1][0] - group[0][0] >= viewport["width"] * 0.07
        and group[-1][0] - group[0][0] <= viewport["width"] * 0.20
        and max(column[2] for column in group) - min(column[1] for column in group) >= viewport["height"] * 0.04
        and max(column[2] for column in group) - min(column[1] for column in group) <= viewport["height"] * 0.16]


def force_auto_reaction_win_button(
    screenshot: bytes, viewport: dict[str, int], pass_region: dict[str, float] | None,
) -> dict[str, Any] | None:
    """Return one orange/red ron button only while a reaction prompt is visible."""
    if not pass_region or not (
        is_force_auto_pass_prompt(screenshot, pass_region)
        or is_contextual_reaction_pass(screenshot, pass_region, 1)
    ):
        return None
    buttons = force_auto_self_action_buttons(screenshot, viewport)
    # Magenta is the kan palette, not independent evidence of ron. Never
    # promote it to a terminal action merely because a skip button is nearby.
    return buttons[0] if len(buttons) == 1 else None


def force_auto_riichi_kan_prompt(screenshot: bytes, viewport: dict[str, int],
                                 pass_region: dict[str, float] | None) -> dict[str, Any] | None:
    """Identify magenta kan plus contextual skip, never an orange win button."""
    if not pass_region or force_auto_self_action_buttons(screenshot, viewport):
        return None
    left, top = round(viewport["width"] * 0.40), round(viewport["height"] * 0.68)
    right, bottom = round(viewport["width"] * 0.62), round(viewport["height"] * 0.85)
    with Image.open(io.BytesIO(screenshot)) as image:
        red, green, blue = image.convert("RGB").crop((left, top, right, bottom)).split()
        masks = [red.point([255 if value > 120 else 0 for value in range(256)]),
                 blue.point([255 if value > 80 else 0 for value in range(256)]),
                 ImageChops.subtract(red, green).point([255 if value > 45 else 0 for value in range(256)]),
                 ImageChops.subtract(blue, green).point([255 if value > 25 else 0 for value in range(256)])]
        mask = masks[0]
        for other in masks[1:]:
            mask = ImageChops.multiply(mask, other)
        bounds = mask.getbbox()
        fraction = mask.histogram()[255] / max(1, mask.width * mask.height)
    if not bounds or fraction < 0.03:
        return None
    width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    if not (viewport["width"] * 0.07 <= width <= viewport["width"] * 0.20
            and viewport["height"] * 0.04 <= height <= viewport["height"] * 0.16):
        return None
    if not is_contextual_reaction_pass(screenshot, pass_region, 1):
        return None
    return {"kan": {"x": left + bounds[0], "y": top + bounds[1], "width": width, "height": height},
            "pass": {**pass_region, "center": {"x": pass_region["x"] + pass_region["width"] / 2,
                                                  "y": pass_region["y"] + pass_region["height"] / 2}}}


def is_draw_slot_occupied(screenshot: bytes, region: dict[str, float]) -> bool:
    """Cheaply distinguish our 14-tile turn from an opponent's turn.

    The calibrated draw slot is blue felt while empty and mostly ivory when a
    tile is present.  This guard runs before the expensive tile recognizer.
    """
    return draw_slots_occupied(screenshot, [region])[0]


def draw_slots_occupied(screenshot: bytes, regions: list[dict[str, float]]) -> list[bool]:
    """Apply the same ivory predicate to several ROIs from one decoded frame."""
    with Image.open(io.BytesIO(screenshot)) as image:
        pixels = image.convert("RGB")
        return [
            _rgb_fraction(pixels.crop((
                region["x"], region["y"],
                region["x"] + region["width"], region["y"] + region["height"],
            )), ((">", 145), (">", 145), (">", 135))) >= 0.20
            for region in regions
        ]


def is_draw_slot_clip_occupied(screenshot: bytes) -> bool:
    with Image.open(io.BytesIO(screenshot)) as image:
        light = _rgb_fraction(image.convert("RGB"), ((">", 145), (">", 145), (">", 135)))
    return light >= 0.20


def closed_concealed_row_visible(screenshot: bytes, layout: dict[str, Any]) -> bool:
    """Require the complete calibrated 13-tile row before leaving a win latch."""
    slots = layout.get("handSlots", [])
    return len(slots) == 13 and all(draw_slots_occupied(screenshot, slots))


def initial_dealing_frame_visible(screenshot: bytes, layout: dict[str, Any]) -> bool:
    """Recognize only a narrow, unmistakable initial dealing animation.

    Both our incomplete 4/8-tile prefix and the opposite player's incomplete
    tile-back row must be visible, with unobscured felt in the missing slots.
    Anything ambiguous stays on the original conservative start-click clock.
    """
    slots = layout.get("handSlots", [])
    draw = layout.get("drawSlot")
    if len(slots) != 13 or not draw or layout.get("viewport") != {"width": 1920, "height": 1080}:
        return False
    try:
        import numpy as np
        with Image.open(io.BytesIO(screenshot)) as source:
            if source.size != (1920, 1080):
                return False
            pixels = np.asarray(source.convert("RGB"))
            def felt(box):
                x1, y1, x2, y2 = map(int, box)
                region = pixels[y1:y2, x1:x2]
                return bool(((region[:, :, 0] < 100) & (region[:, :, 1] < 135)
                             & (region[:, :, 2] > 70)).mean() >= 0.85)
            def slot_box(slot):
                return (slot["x"], slot["y"], slot["x"] + slot["width"], slot["y"] + slot["height"])
            def ivory(slot):
                x1, y1, x2, y2 = map(int, slot_box(slot))
                region = pixels[y1:y2, x1:x2]
                return bool(((region[:, :, 0] > 145) & (region[:, :, 1] > 145)
                             & (region[:, :, 2] > 135)).mean() >= 0.20)
            occupied = [ivory(slot) for slot in [*slots, draw]]
            count = next((n for n in (4, 8) if occupied[:n] == [True] * n
                          and not any(occupied[n:])), None)
            if count is None or not all(felt(slot_box(slot)) for slot in [*slots[count:], draw]):
                return False
            # Opposite player's leftmost backs have not appeared yet, while
            # rightmost backs are present; a normal table has a full row.
            if not felt((735, 5, 770, 50)):
                return False
            back = pixels[5:50, 1275:1310]
            if ((back[:, :, 0] > 150) & (back[:, :, 1] > 100) & (back[:, :, 2] < 130)).mean() < 0.35:
                return False
            meld = pixels[907:1080, 1536:1882]
            if ((meld[:, :, 0] > 145) & (meld[:, :, 1] > 145) & (meld[:, :, 2] > 135)).mean() >= 0.12:
                return False
    except Exception:
        return False
    return True


def open_hand_draw_slot(layout: dict[str, Any], open_melds: int) -> dict[str, float] | None:
    """Return the compact-row draw tile, which replaces the closed-row gap."""
    draw_slot = layout.get("drawSlot")
    hand_slots = layout.get("handSlots", [])
    if not draw_slot or open_melds <= 0 or len(hand_slots) < 2:
        return None
    concealed_before_draw = 13 - open_melds * 3
    if concealed_before_draw < 0 or concealed_before_draw >= len(hand_slots):
        return None
    # Calls remove three ordinary slots and the closed-hand draw gap.  The
    # draw tile lands in the first remaining calibrated slot, not at the old
    # draw coordinate merely translated by three pitches.
    source = hand_slots[concealed_before_draw]
    shifted = {key: float(source[key]) for key in ("x", "y", "width", "height")}
    viewport_width = float(layout.get("viewport", {}).get("width", 0))
    if shifted["x"] < 0 or shifted["x"] + shifted["width"] > viewport_width:
        return None
    return shifted


def self_turn_draw_visible(screenshot: bytes, layout: dict[str, Any], open_melds: int) -> bool:
    slot = open_hand_draw_slot(layout, open_melds) if open_melds > 0 else layout.get("drawSlot")
    return bool(slot and is_draw_slot_occupied(screenshot, slot))


def own_meld_surface_visible(screenshot: bytes, layout: dict[str, Any]) -> bool:
    viewport = layout.get("viewport", {})
    if not viewport:
        return False
    # Own exposed melds occupy a dedicated lower-right strip, separated from
    # the concealed row. Require a substantial ivory tile surface there.
    meld_region = {
        "x": float(viewport["width"]) * 0.80,
        "y": float(viewport["height"]) * 0.84,
        "width": float(viewport["width"]) * 0.18,
        "height": float(viewport["height"]) * 0.16,
    }
    with Image.open(io.BytesIO(screenshot)) as image:
        meld_image = image.convert("RGB").crop((
            meld_region["x"], meld_region["y"],
            meld_region["x"] + meld_region["width"],
            meld_region["y"] + meld_region["height"],
        ))
        meld_light = _rgb_fraction(meld_image, ((">", 145), (">", 145), (">", 135)))
    return meld_light >= 0.12


def compact_hand_occupancy(
    screenshot: bytes, layout: dict[str, Any],
) -> tuple[list[bool], dict[int, bool]]:
    slots = layout.get("handSlots", [])
    draws = {melds: slot for melds in range(1, 5)
             if (slot := open_hand_draw_slot(layout, melds)) is not None}
    occupied = draw_slots_occupied(screenshot, [*slots, *draws.values()])
    return occupied[:len(slots)], dict(zip(draws, occupied[len(slots):]))


def geometric_open_meld_count(screenshot: bytes, layout: dict[str, Any]) -> int | None:
    """Infer compact open-hand geometry without trusting tile classifications."""
    hand_slots = layout.get("handSlots", [])
    viewport = layout.get("viewport", {})
    if len(hand_slots) < 13 or not viewport:
        return None
    if not own_meld_surface_visible(screenshot, layout):
        return None
    occupied, draw_occupied = compact_hand_occupancy(screenshot, layout)
    # Prefer the smallest count: a longer one-meld row is also a prefix of
    # shorter multi-meld layouts. Closed 13-tile rows are rejected by the
    # required empty final calibrated slot.
    for open_melds in range(1, 5):
        concealed_before_draw = 13 - open_melds * 3
        if concealed_before_draw < 1 or open_melds not in draw_occupied:
            continue
        # Exposed tiles can overlap every slot after the compact draw slot.
        # In particular a one-meld self draw fills slots 0..10 while the
        # right-side pon can make the immediately following felt gap look
        # ivory.  The compact prefix plus its calibrated draw slot are the
        # stable evidence; the slots to their right must not veto it.
        if all(occupied[:concealed_before_draw]) \
                and draw_occupied[open_melds]:
            return open_melds
    return None


def geometric_reaction_open_meld_count(screenshot: bytes, layout: dict[str, Any]) -> int | None:
    """Verify a compact opponent-turn row, never a self draw or closed row."""
    slots = layout.get("handSlots", [])
    if len(slots) < 13 or not own_meld_surface_visible(screenshot, layout):
        return None
    occupied, draw_occupied = compact_hand_occupancy(screenshot, layout)
    for melds in range(1, 5):
        count = 13 - 3 * melds
        if melds in draw_occupied and all(occupied[:count]) and not occupied[count] \
                and not draw_occupied[melds]:
            return melds
    return None


def round_result_conflicts_with_live_table(screenshot: bytes, layout: dict[str, Any]) -> dict[str, Any] | None:
    """Return direct live-table evidence which vetoes a round-result guess.

    Result overlays dim and hide the hand enough that neither calibrated hand
    geometry should be visible.  In contrast, a closed 13-tile row or a
    compact row plus own exposed meld is positive evidence that play is still
    live.  This deliberately does not use a mere cached hand: stale cache
    state must never hide a genuine result screen.
    """
    if closed_concealed_row_visible(screenshot, layout):
        return {"kind": "closed_concealed_row"}
    open_melds = geometric_open_meld_count(screenshot, layout)
    if open_melds is not None:
        return {"kind": "open_hand_geometry", "openMelds": open_melds,
                "selfDrawVisible": self_turn_draw_visible(screenshot, layout, open_melds)}
    return None


def discard_point_in_hand_geometry(
    point: dict[str, float], layout: dict[str, Any], open_melds: int,
) -> bool:
    slots = layout.get("handSlots", [])
    if not slots:
        return False
    draw_slot = open_hand_draw_slot(layout, open_melds) if open_melds > 0 else layout.get("drawSlot")
    if not draw_slot:
        return False
    left = float(slots[0]["x"])
    right = float(draw_slot["x"] + draw_slot["width"])
    top = min(float(slot["y"]) for slot in slots)
    bottom = max(float(slot["y"] + slot["height"]) for slot in slots)
    return left <= float(point["x"]) <= right and top <= float(point["y"]) <= bottom


def stable_hand_comparison_region(
    layout: dict[str, Any], open_melds: int,
) -> dict[str, float] | None:
    """Tile-face-only ROI, excluding meld/call animation and bottom effects."""
    slots = layout.get("handSlots", [])
    if not slots:
        return None
    draw_slot = open_hand_draw_slot(layout, open_melds) if open_melds > 0 else layout.get("drawSlot")
    if not draw_slot:
        return None
    left = float(slots[0]["x"]) + 10
    top = float(slots[0]["y"]) + 10
    right = float(draw_slot["x"] + draw_slot["width"]) - 8
    bottom = min(float(slot["y"] + slot["height"]) for slot in slots) - 28
    if right <= left or bottom <= top:
        return None
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def selected_tile_comparison_region(
    layout: dict[str, Any], point: dict[str, float], open_melds: int,
) -> dict[str, float] | None:
    """Tile-face ROI at a verified discard point during compact-row settling."""
    if not discard_point_in_hand_geometry(point, layout, open_melds):
        return None
    slots = layout.get("handSlots", [])
    if not slots:
        return None
    width = min(float(slot["width"]) for slot in slots) - 20
    top = min(float(slot["y"]) for slot in slots) + 10
    bottom = min(float(slot["y"] + slot["height"]) for slot in slots) - 28
    if width <= 0 or bottom <= top:
        return None
    return {"x": float(point["x"]) - width / 2, "y": top, "width": width, "height": bottom - top}


def blank_tile_raised_confirmation(
    before: bytes, after: bytes, slots: list[dict[str, Any]], click_index: int,
    point: dict[str, float],
) -> dict[str, float] | None:
    """Prove a blank tile's top edge moved while its neighbour stayed put."""
    slot = slots[click_index]
    if click_index == 0:
        return None
    neighbour = slots[click_index - 1]
    try:
        with Image.open(io.BytesIO(before)) as a, Image.open(io.BytesIO(after)) as b:
            first, second = a.convert("RGB"), b.convert("RGB")

        def tops(image: Image.Image, tile: dict[str, Any], require_rim: bool = False) -> list[int | None]:
            center = float(tile["x"]) + float(tile["width"]) / 2
            top = int(tile["y"])
            offsets = (-28, -14, 0, 14)
            result = []
            for offset in offsets:
                x = int(center + offset)
                found = None
                for y in range(max(0, top - 80), min(image.height - 2, top + 8)):
                    # Require three consecutive neutral light pixels to avoid
                    # isolated sparkle noise, then compare several columns.
                    if (all(min(rgb := image.getpixel((x, y + dy))) > (130 if require_rim else 70)
                            and max(rgb) - min(rgb) < 50 for dy in range(3))
                            and (not require_rim or any(
                                (rgb := image.getpixel((x, rim_y)))[0] > 150
                                and rgb[0] - rgb[1] > 35 and rgb[1] - rgb[2] > 30
                                for rim_y in range(max(0, y - 8), y)))):
                        found = y
                        break
                result.append(found)
            return result

        # Search for a rim-backed edge, not the first light pixels: the large
        # countdown can overlap the search strip above a white draw tile.
        old, new = tops(first, slot, True), tops(second, slot, True)
        neighbour_old, neighbour_new = tops(first, neighbour), tops(second, neighbour)
        if any(value is None for value in (*old, *neighbour_old, *neighbour_new)):
            return None
        # Calibration captures can include a few pixels of felt above the
        # tile's orange rim.  The live 300+0 layout has a six-pixel offset;
        # retain a tight eight-pixel physical range rather than rejecting a
        # perfectly evidenced border/lift because of that crop convention.
        expected_top = int(slot["y"])
        if any(abs(y - expected_top) > 8 for y in old):
            return None
        # The countdown icon can cover part of the raised tile and contribute
        # unrelated rim-like pixels. Require two independent columns agreeing
        # on the same upward motion; treat other columns as obstructed.
        lifts = [a - b for a, b in zip(old, new) if b is not None and 12 <= a - b <= 80]
        matching = [candidate for candidate in lifts
                    if sum(abs(candidate - other) <= 2 for other in lifts) >= 2]
        if len(matching) < 2 or max(matching) - min(matching) > 2:
            return None
        if any(abs(a - b) > 2 for a, b in zip(neighbour_old, neighbour_new)):
            return None
        lift = round(sum(matching) / len(matching))
        return {"x": float(point["x"]), "y": float(point["y"]) - lift,
                "lift": float(lift), "faceStructureDelta": 0.0,
                "verification": "blank_tile_edge_and_stable_neighbour"}
    except Exception:
        return None


def raised_rim_and_glyph_confirmation(
    before: bytes, after: bytes, slots: list[dict[str, Any]], click_index: int,
    point: dict[str, float], face: dict[str, float],
) -> dict[str, float] | None:
    """Combine a translated physical rim, stable neighbour and visible glyph.

    Selection lighting can wash out the glyph, but cannot substitute for a
    uniquely translated rim.  Both observations must describe the same lift.
    """
    edge = blank_tile_raised_confirmation(before, after, slots, click_index, point)
    if edge is None:
        return None
    try:
        with Image.open(io.BytesIO(before)) as image:
            first = image.convert("RGB")
        with Image.open(io.BytesIO(after)) as image:
            second = image.convert("RGB")
        slot = slots[click_index]
        left, right = int(slot["x"]) + 5, int(slot["x"] + slot["width"]) - 5
        top = int(slot["y"]) - 5
        if left >= right or top < 80:
            return None
        rim = first.crop((left, top, right, top + 13))
        def rim_delta(lift: int) -> float:
            shifted = second.crop((left, top - lift, right, top + 13 - lift))
            return sum(ImageStat.Stat(ImageChops.difference(rim, shifted)).mean) / 3
        lift = int(edge["lift"])
        delta = rim_delta(lift)
        if delta > 5 or min(rim_delta(offset) for offset in range(8, 81)
                            if abs(offset - lift) > 2) - delta < 10:
            return None
        lookup = [255 if value < 120 else 0 for value in range(256)]
        first_mask = first.convert("L").point(lookup)
        second_mask = second.convert("L").point(lookup)
        x, y, w, h = (int(face[key]) for key in ("x", "y", "width", "height"))
        baseline = first_mask.crop((x, y, x + w, y + h))
        shifted = second_mask.crop((x, y - lift, x + w, y + h - lift))
        count = lambda mask: ImageStat.Stat(mask).sum[0] / 255
        glyph, observed = count(baseline), count(shifted)
        if glyph < 100 or not 0.7 <= observed / glyph <= 1.4:
            return None
        if count(ImageChops.multiply(baseline, shifted)) / glyph < 0.5:
            return None
        neighbour = slots[click_index - 1]
        nx, ny, nw, nh = (int(neighbour[key]) for key in ("x", "y", "width", "height"))
        neighbour_rect = (nx + 10, ny + 10, nx + nw - 10, ny + nh - 28)
        neighbour_before = first_mask.crop(neighbour_rect)
        neighbour_after = second_mask.crop(neighbour_rect)
        neighbour_glyph = count(neighbour_before)
        if (neighbour_glyph < 100
                or not 0.7 <= count(neighbour_after) / neighbour_glyph <= 1.4
                or count(ImageChops.multiply(neighbour_before, neighbour_after)) / neighbour_glyph < 0.5):
            return None
        return {**edge, "verification": "translated_rim_glyph_and_stable_neighbour"}
    except Exception:
        return None


def raised_glyph_overlap_confirmation(
    baseline: Image.Image, after_mask: Image.Image, face: dict[str, float],
    point: dict[str, float],
) -> dict[str, float] | None:
    """Confirm a lifted glyph despite a client selection-light animation.

    The selection animation can wash out part of a tile face, making a raw
    pixel-difference comparison reject a real selection.  It must not make a
    static or neighbouring tile acceptable: require that nearly all of the
    target's *dark glyph* moves by one unique vertical offset.
    """
    baseline_pixels = list(baseline.getdata())
    glyph_pixels = sum(value > 0 for value in baseline_pixels)
    if glyph_pixels == 0:
        return None
    left, top = int(face["x"]), int(face["y"])
    right, bottom = int(face["x"] + face["width"]), int(face["y"] + face["height"])
    candidates: list[tuple[float, float, int]] = []
    for lift in range(8, 81):
        shifted = after_mask.crop((left, top - lift, right, bottom - lift))
        shifted_pixels = list(shifted.getdata())
        overlap = sum(a > 0 and b > 0 for a, b in zip(baseline_pixels, shifted_pixels))
        shifted_count = sum(value > 0 for value in shifted_pixels)
        candidates.append((overlap / glyph_pixels, shifted_count / glyph_pixels, lift))
    overlap, density, lift = max(candidates)
    runner_up = max(score for score, _density, offset in candidates if offset != lift)
    # Empirical F/E receipts retain 94%+ of the dark glyph at 48px; unchanged
    # tiles peak below 57%.  The density bound excludes a broad dark overlay.
    if overlap < 0.90 or overlap - runner_up < 0.07 or not 0.70 <= density <= 1.35:
        return None
    return {"x": float(point["x"]), "y": float(point["y"]) - lift,
            "lift": float(lift), "faceStructureDelta": 0.0,
            "verification": "dark_glyph_overlap"}


def sparkle_masked_lift_confirmation(
    before: bytes, after: bytes, slots: list[dict[str, Any]], click_index: int,
    face: dict[str, float], point: dict[str, float], lift: int, threshold: float,
) -> dict[str, float] | None:
    """Verify the unoccluded glyph around a small pink click animation."""
    if click_index == 0:
        return None
    try:
        with Image.open(io.BytesIO(before)) as source, Image.open(io.BytesIO(after)) as receipt:
            first = source.convert("L").point([255 if v < 120 else 0 for v in range(256)])
            rgb = receipt.convert("RGB")
            second = rgb.convert("L").point([255 if v < 120 else 0 for v in range(256)])
        x, y, w, h = (int(face[k]) for k in ("x", "y", "width", "height"))
        baseline = first.crop((x, y, x + w, y + h))
        selected = rgb.crop((x, y - lift, x + w, y + h - lift))
        pink = Image.new("L", selected.size)
        pink.putdata([255 if r > 140 and b > 100 and r > g * 1.15 and b > g * 1.1 else 0
                      for r, g, b in selected.getdata()])
        bounds = pink.getbbox()
        if bounds is None or ImageStat.Stat(pink).sum[0] / 255 < 20:
            return None
        left, top, right, bottom = bounds
        left, top, right, bottom = max(0, left - 5), max(0, top - 5), min(w, right + 5), min(h, bottom + 5)
        if (right - left) * (bottom - top) > w * h * 0.2:
            return None
        valid = Image.new("L", (w, h), 255)
        valid.paste(0, (left, top, right, bottom))
        count = lambda image: ImageStat.Stat(image).sum[0] / 255
        glyph = count(baseline)
        retained = count(ImageChops.multiply(baseline, valid))
        if glyph < 100 or retained < glyph * 0.7:
            return None
        valid_count = count(valid)
        def difference(offset: int) -> float:
            shifted = second.crop((x, y - offset, x + w, y + h - offset))
            return count(ImageChops.multiply(ImageChops.difference(baseline, shifted), valid)) / valid_count * 100
        delta = difference(lift)
        # Adjacent one- or two-pixel offsets describe the same physical lift,
        # not competing tiles. Demand separation from distinct offsets while
        # still requiring the selected slot and its neighbour to match.
        if delta > threshold or min(difference(offset) for offset in range(8, 81)
                                    if abs(offset - lift) > 2) - delta < 4.5:
            return None
        neighbour = slots[click_index - 1]
        nx, ny = int(neighbour["x"]) + 10, int(neighbour["y"]) + 10
        nw, nh = int(neighbour["width"]) - 20, int(neighbour["height"]) - 38
        old = first.crop((nx, ny, nx + nw, ny + nh))
        new = second.crop((nx, ny, nx + nw, ny + nh))
        if ImageStat.Stat(ImageChops.difference(old, new)).mean[0] / 255 * 100 > threshold:
            return None
        return {"x": float(point["x"]), "y": float(point["y"]) - lift,
                "lift": float(lift), "faceStructureDelta": round(delta, 3),
                "verification": "sparkle_masked_unique_glyph_and_stable_neighbour"}
    except Exception:
        return None


def raised_tile_confirmation_point(
    before: bytes, after: bytes, layout: dict[str, Any], click_index: int,
    point: dict[str, float], threshold: float,
) -> dict[str, float] | None:
    """Locate the selected tile's *observed* raised face for click two.

    A fixed vertical offset is not a physical guarantee: the client can use a
    different lift for a compact hand, and a late second click can otherwise
    be consumed as a draw discard.  Match the exact pre-click glyph face over
    a vertical search strip in the selection receipt.  A match must move up
    by a material amount; an unchanged tile or an adjacent tile animation is
    not evidence that this physical slot was selected.
    """
    slots = [*layout.get("handSlots", [])]
    draw_slot = layout.get("drawSlot")
    if draw_slot:
        slots.append(draw_slot)
    if not isinstance(click_index, int) or not 0 <= click_index < len(slots):
        return None
    slot = slots[click_index]
    if not all(isinstance(point.get(key), (int, float)) for key in ("x", "y")):
        return None
    if not (float(slot["x"]) <= float(point["x"]) < float(slot["x"] + slot["width"])
            and float(slot["y"]) <= float(point["y"]) < float(slot["y"] + slot["height"])):
        return None
    face = {
        "x": float(slot["x"]) + 10,
        "y": float(slot["y"]) + 10,
        "width": float(slot["width"]) - 20,
        "height": float(slot["height"]) - 38,
    }
    if face["width"] <= 0 or face["height"] <= 0:
        return None
    try:
        # Decode each viewport once. Re-decoding the full JPEG and encoding a
        # PNG for every vertical offset took longer than the ranked click
        # budget after the tile was already selected. The same threshold and
        # full 8..80 search are retained; only image transport is removed.
        with Image.open(io.BytesIO(before)) as before_image, Image.open(io.BytesIO(after)) as after_image:
            lookup = [255 if value < 120 else 0 for value in range(256)]
            before_mask = before_image.convert("L").point(lookup)
            after_mask = after_image.convert("L").point(lookup)
        left, top = int(face["x"]), int(face["y"])
        right, bottom = int(face["x"] + face["width"]), int(face["y"] + face["height"])
        baseline = before_mask.crop((left, top, right, bottom))
        # An entirely blank face matches every vertical offset; it cannot
        # establish movement by its glyph. Require independent edge movement.
        if ImageStat.Stat(baseline).sum[0] == 0:
            return blank_tile_raised_confirmation(before, after, slots, click_index, point)
        # Mahjong Soul lifts toward the table centre.  Search a deliberately
        # broad but bounded strip; the lower bound avoids accepting an
        # unchanged face as a selection receipt.
        candidates: list[tuple[float, int]] = []
        for lift in range(8, 81):
            shifted = after_mask.crop((left, int(face["y"] - lift), right,
                                       int(face["y"] - lift + face["height"])))
            delta = ImageStat.Stat(ImageChops.difference(baseline, shifted)).mean[0] / 255 * 100
            candidates.append((delta, lift))
    except Exception:
        return None
    delta, lift = min(candidates)
    if delta > threshold:
        rim_confirmation = raised_rim_and_glyph_confirmation(
            before, after, slots, click_index, point, face,
        )
        if rim_confirmation is not None:
            return rim_confirmation
        sparkle_confirmation = sparkle_masked_lift_confirmation(
            before, after, slots, click_index, face, point, lift, threshold,
        )
        if sparkle_confirmation is not None:
            return sparkle_confirmation
        # Some calibrated layouts include five pixels of felt above each
        # physical tile (while retaining the same bottom edge). Retry only
        # the independent rim + glyph + stationary-neighbour proof with that
        # inset; do not relax the ordinary face-difference thresholds.
        inset_slots = [{**tile, "y": tile["y"] + 5, "height": tile["height"] - 5}
                       for tile in slots]
        inset_face = {**face, "y": face["y"] + 5, "height": face["height"] - 5}
        if inset_face["height"] > 0:
            rim_confirmation = raised_rim_and_glyph_confirmation(
                before, after, inset_slots, click_index, point, inset_face,
            )
            if rim_confirmation is not None:
                return {**rim_confirmation, "verification": "inset_translated_rim_glyph_and_stable_neighbour"}
        # A click sparkle can change a small part of the selected glyph. In
        # the recorded 9p receipt the true 48px lift differed by 1.685%,
        # while the nearest alternative differed by 17.091%. Admit only this
        # narrow excess when the matching offset is decisively isolated;
        # ambiguous or substantially changed faces remain fail-closed.
        alternatives = [other for other, offset in candidates if offset != lift]
        if delta > threshold + 0.5 or min(alternatives) - delta < 10.0:
            # Ignore only a small pink click sparkle in the receipt. This
            # does not apply to arbitrary occlusion: most of the target face
            # and at least 85% of its dark glyph must remain comparable.
            if min(alternatives) - delta < 4.5:
                # Keep the narrow 9p sparkle path unchanged.  The F receipt
                # begins just above this band (1.915%), where the glyph
                # overlap proof is needed to survive the selection light.
                if delta <= 1.8:
                    return None
                return raised_glyph_overlap_confirmation(baseline, after_mask, face, point)
            try:
                with Image.open(io.BytesIO(after)) as image:
                    rgb = image.convert("RGB").crop((left, int(face["y"] - lift), right,
                                                     int(face["y"] - lift + face["height"])))
                valid = Image.new("L", rgb.size)
                valid.putdata([0 if r > 140 and b > 100 and r > g * 1.15 and b > g * 1.1 else 255
                               for r, g, b in rgb.getdata()])
                total = rgb.width * rgb.height
                valid_count = ImageStat.Stat(valid).sum[0] / 255
                if valid_count < total * 0.95 or valid_count == total:
                    return raised_glyph_overlap_confirmation(baseline, after_mask, face, point)
                glyph_pixels = ImageStat.Stat(baseline).sum[0] / 255
                retained_glyph = ImageStat.Stat(ImageChops.multiply(baseline, valid)).sum[0] / 255
                if glyph_pixels == 0 or retained_glyph < glyph_pixels * 0.85:
                    return raised_glyph_overlap_confirmation(baseline, after_mask, face, point)
                shifted = after_mask.crop((left, int(face["y"] - lift), right,
                                           int(face["y"] - lift + face["height"])))
                difference = ImageChops.multiply(ImageChops.difference(baseline, shifted), valid)
                delta = ImageStat.Stat(difference).sum[0] / 255 / valid_count * 100
                if delta > threshold:
                    return raised_glyph_overlap_confirmation(baseline, after_mask, face, point)
            except Exception:
                return raised_glyph_overlap_confirmation(baseline, after_mask, face, point)
        overlap_confirmation = raised_glyph_overlap_confirmation(
            baseline, after_mask, face, point,
        )
        if overlap_confirmation is not None:
            return overlap_confirmation
    return {"x": float(point["x"]), "y": float(point["y"]) - lift,
            "lift": float(lift), "faceStructureDelta": round(delta, 3)}


def riichi_selection_target_region(
    layout: dict[str, Any], click_index: Any, point: Any,
) -> dict[str, float] | None:
    """Return the face ROI for the physical tile chosen after Riichi.

    The declaration changes the hand into a dimmed selection UI.  Its tile
    positions must be proved from that *new* UI, rather than trusting the
    evaluator's pre-declaration coordinate.  Restrict the comparison to the
    selected physical slot so unrelated table animation cannot mask a moved
    or replaced target.
    """
    slots = [*layout.get("handSlots", [])]
    draw_slot = layout.get("drawSlot")
    if draw_slot is None:
        return None
    slots.append(draw_slot)
    if not isinstance(click_index, int) or not 0 <= click_index < len(slots):
        return None
    if not isinstance(point, dict) or not all(isinstance(point.get(key), (int, float)) for key in ("x", "y")):
        return None
    slot = slots[click_index]
    x, y = float(point["x"]), float(point["y"])
    if not (slot["x"] <= x < slot["x"] + slot["width"]
            and slot["y"] <= y < slot["y"] + slot["height"]):
        return None
    # Match the glyph-only portions used by the ordinary stale-hand guard.
    # This excludes the bottom click/hover effect and tile borders.
    width = float(slot["width"]) - 20
    height = float(slot["height"]) - 38
    if width <= 0 or height <= 0:
        return None
    return {"x": float(slot["x"]) + 10, "y": float(slot["y"]) + 10,
            "width": width, "height": height}


def local_discard_allowed(args: argparse.Namespace, evaluation: dict[str, Any]) -> bool:
    decision = evaluation.get("decision", {})
    return bool(
        args.allow_local_discard
        and args.mode == "advisor"
        and decision.get("recommendedAction") == "discard"
        and decision.get("safety", {}).get("allowed") is True
        and decision.get("confidence", 0) >= 0.55
    )


def require_post_riichi_draw_click(
    evaluation: dict[str, Any], selected: dict[str, Any], layout: dict[str, Any],
    click_index: Any, point: Any, established_riichi: bool = False,
) -> None:
    """Reject a locked-hand discard before any mouse action, including duplicate draws."""
    state = evaluation.get("state", {})
    if selected.get("action") not in {"discard", "riichi"}:
        return
    if not (state.get("riichiDeclared") or established_riichi):
        return
    tiles = evaluation.get("recognition", {}).get("tiles", [])
    draw = state.get("draw")
    open_melds = state.get("openMelds", 0)
    expected_count = 14 - 3 * open_melds
    slot = open_hand_draw_slot(layout, open_melds) if open_melds > 0 else layout.get("drawSlot")
    if (selected.get("action") != "discard" or not state.get("riichiDeclared")
            or state.get("phase") != "self_turn" or not draw
            or selected.get("tile") != draw
            or len(tiles) != expected_count
            or tiles != [*state.get("hand", []), draw]
            or click_index != expected_count - 1
            or not slot or not isinstance(point, dict)
            or not isinstance(point.get("x"), (int, float))
            or not isinstance(point.get("y"), (int, float))
            or not (slot["x"] <= point["x"] < slot["x"] + slot["width"]
                    and slot["y"] <= point["y"] < slot["y"] + slot["height"])):
        raise RetryableSafetyAbort("post-riichi discard must target the verified physical draw slot")


def verified_post_call_white_discard(
    evaluation: dict[str, Any], screenshot: bytes | None, layout: dict[str, Any],
    open_melds: int, pending_post_call_discard: bool,
) -> bool:
    """Certify a physical blank white tile in a complete post-chi/pon row.

    The last tile after a call is not a newly classified independent draw.
    Blank P has no glyph for template confidence; require the actual ivory
    face and its felt boundary, not just the evaluator's P label. The normal
    pre-click generation, hand stability and time guards still apply.
    """
    if not pending_post_call_discard or screenshot is None or not 1 <= open_melds <= 4:
        return False
    state = evaluation.get("state", {})
    tiles = evaluation.get("recognition", {}).get("tiles", [])
    selected = evaluation.get("decision", {}).get("selectedAction", {})
    count = 14 - 3 * open_melds
    if (evaluation.get("openMelds") != open_melds or state.get("openMelds") != open_melds
            or len(state.get("melds", [])) != open_melds or len(tiles) != count
            or tiles != [*state.get("hand", []), state.get("draw")]
            or selected.get("action") != "discard" or selected.get("tile") != "P"
            or tiles[-1] != "P" or evaluation.get("clickIndex") != count - 1):
        return False
    slot = open_hand_draw_slot(layout, open_melds)
    point = evaluation.get("clickPoint", {})
    if not slot or not (slot["x"] <= point.get("x", -1) <= slot["x"] + slot["width"]
                        and slot["y"] <= point.get("y", -1) <= slot["y"] + slot["height"]):
        return False
    if geometric_open_meld_count(screenshot, layout) != open_melds:
        return False
    with Image.open(io.BytesIO(screenshot)) as image:
        viewport = layout.get("viewport", {})
        if image.size != (viewport.get("width"), viewport.get("height")):
            return False
        pixels = image.convert("RGB")
        top, bottom = slot["y"] + 12, slot["y"] + slot["height"] - 22
        face = pixels.crop((slot["x"] + 10, top, slot["x"] + slot["width"] - 10, bottom))
        gap = pixels.crop((slot["x"] + slot["width"] + 4, top,
                           slot["x"] + slot["width"] + 24, bottom))
        ivory = lambda red, green, blue: min(red, green, blue) > 145 and max(red, green, blue) - min(red, green, blue) < 30
        return fraction_matching(face, ivory) >= 0.995 and fraction_matching(gap, ivory) < 0.05


def selected_open_draw_is_ambiguous(evaluation: dict[str, Any]) -> bool:
    """Whether force-auto selected an unreliable independent draw-slot tile."""
    open_melds = evaluation.get("openMelds", 0)
    tiles = evaluation.get("recognition", {}).get("tiles", [])
    click_index = evaluation.get("clickIndex")
    recognition = evaluation.get("recognition", {})
    selected = evaluation.get("selectedTileRecognition", {})
    if isinstance(click_index, int) and 0 <= click_index < len(tiles) \
            and selected.get("index") == click_index and selected.get("tile") == tiles[click_index]:
        confidence = selected.get("confidence", 0)
        margin = confidence - selected.get("runnerUpConfidence", confidence)
        confirmation = selected.get("normalizedConsensus", {})
        if confidence >= 0.7 and margin >= 0.1 \
                and confirmation.get("tile") == selected.get("tile") \
                and confirmation.get("confidence", 0) >= 0.95 \
                and confirmation.get("confidence", 0) - confirmation.get("runnerUpConfidence", 1) >= 0.15:
            return False
    else:
        # Older evaluators do not provide tile-specific evidence.
        confidence = recognition.get("confidence", 0)
        margin = recognition.get("ambiguityMargin", 1)
    return bool(
        open_melds > 0
        and isinstance(click_index, int)
        and click_index == len(tiles) - 1
        and (
            confidence < 0.80
            or margin < 0.05
        )
    )


def ambiguous_open_draw_fallback(evaluation: dict[str, Any]) -> tuple[str, int] | None:
    """Choose the best evaluated tile known to be in the compact row."""
    tiles = evaluation.get("recognition", {}).get("tiles", [])
    if not isinstance(tiles, list) or len(tiles) < 2:
        return None
    concealed = tiles[:-1]
    for candidate in evaluation.get("decision", {}).get("candidates", []):
        tile = candidate.get("tile")
        if candidate.get("action") == "discard" and tile in concealed:
            return tile, max(index for index, observed in enumerate(concealed) if observed == tile)
    return None


def send_discard_click(
    mouse: Any,
    point: dict[str, float],
    viewport: dict[str, int],
    wait_for_selection: Callable[[float], None],
    selection_before: bytes,
    selection_receipt: Callable[[float], bytes | None],
    layout: dict[str, Any],
    click_index: int,
    stability_threshold: float,
    before_confirmation_click: Callable[[], None] | None = None,
    on_unverified_selection: Callable[[bytes, bytes | None], None] | None = None,
) -> dict[str, float]:
    """Select a tile, then confirm it inside its raised hitbox.

    Mahjong Soul lifts the selected tile between the two input events.  Do
    not guess its raised coordinate: prove the selected physical face moved
    in a post-first-click receipt, then click its measured position.

    The wait must be *between* the two click events.  ``mouse.click(delay=…)``
    only holds the second press down; it does not let the client apply the
    first click's raised-tile transform.  The ranked 1f18f5d evidence showed
    the selected C still raised after confirmation while unrelated automatic
    discards reached the river.  Wait for that transform before targeting its
    raised hitbox.
    """
    mouse.click(point["x"], point["y"])
    first_click_at = time.monotonic()
    # A single fixed 120ms receipt was observed to precede the client's lift
    # animation.  Poll only briefly and always compare every receipt with the
    # pre-click frame: a later receipt may prove this exact tile moved, but an
    # unproven receipt must never be used for the second click.
    confirmation = None
    last_receipt = None
    for wait_ms in (40, 40, 60, 80, 100, 120):
        wait_for_selection(wait_ms)
        receipt = selection_receipt(first_click_at)
        # A receipt from before the first click cannot prove the selected
        # tile's animation, even if it happens to contain a raised glyph.
        # In force-auto this is a fresh CDP screencast frame, deliberately
        # not a synchronous Page.screenshot() call: synchronous captures can
        # block for seconds while an open hand is waiting to settle.
        if receipt is not None:
            last_receipt = receipt
            confirmation = raised_tile_confirmation_point(
                selection_before, receipt, layout, click_index, point,
                stability_threshold,
            )
        if confirmation is not None:
            break
    if confirmation is None:
        mouse.move(viewport["width"] / 2, viewport["height"] * 0.72)
        if on_unverified_selection is not None:
            try:
                on_unverified_selection(selection_before, last_receipt)
            except Exception:
                # Evidence capture must never turn an unsafe first click into
                # an ordinary retry against an uncertain selection.
                pass
        # The first click might have selected a tile even though no screenshot
        # could prove it.  Do not let the normal retry path issue a possible
        # deselect click against that unresolved state.
        raise SelectionStateUncertainAbort(
            "selected tile lift or identity could not be verified before discard confirmation"
        )
    # The receipt proves the requested physical tile is still raised.  The
    # second activation must target that observed raised hitbox, not the
    # now-vacated calibrated centre: in the 5+20 445541f regression, clicking
    # the original centre left 5s selected and Mahjong Soul later tsumogiri'd
    # 7s.  A measured raised coordinate is therefore both the identity proof
    # and the only admissible confirmation target.
    if before_confirmation_click is not None:
        try:
            before_confirmation_click()
        except Exception as error:
            # The first click may have left the requested tile raised.  A
            # normal retry could therefore deselect it; disarm this hand just
            # as for an unproven receipt, while preserving the actual guard
            # failure in the error text.
            mouse.move(viewport["width"] / 2, viewport["height"] * 0.72)
            raise SelectionStateUncertainAbort(
                f"discard confirmation withheld after tile selection: {error}"
            ) from error
    mouse.click(confirmation["x"], confirmation["y"], delay=80)
    # Once the row closes, the next tile can slide under the pointer and stay
    # raised. Move to inert table felt before post-action recognition.
    mouse.move(viewport["width"] / 2, viewport["height"] * 0.72)
    return confirmation


def same_physical_tile(left: str, right: str) -> bool:
    """Compare river identities while treating a red five as its base five."""
    canonical = lambda tile: f"5{tile[1]}" if len(tile) == 2 and tile[0] == "0" else tile
    return canonical(left) == canonical(right)


def retreat_pointer_from_hand(mouse: Any, viewport: dict[str, int]) -> None:
    """Move startup/result-screen pointer positions off the concealed hand."""
    mouse.move(viewport["width"] / 2, viewport["height"] * 0.72)


def screencast_frame_follows_pointer_retreat(
    gate_sequence: int | None, pointer_retreat_sequence: int | None,
) -> bool:
    """Whether a gate frame was observed after this operator cleared hover.

    A reused frame is safe only when its screencast receipt is newer than the
    input event that moved the pointer to table felt.  Otherwise a lifted tile
    can enter the recognition crop, so retain the conservative fresh capture.
    """
    return isinstance(gate_sequence, int) and isinstance(pointer_retreat_sequence, int) \
        and gate_sequence > pointer_retreat_sequence


def public_capture_seconds(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.timestamp() if stamp.tzinfo is not None else None
    except ValueError:
        return None


def corroborate_own_river_withdrawal(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Withdraw one called own tile, never infer a call from a vanished crop alone."""
    before = previous.get("ownDiscards", [])
    latest = current.get("ownDiscards", [])
    now = public_capture_seconds(current.get("capturedAt"))
    old_time = public_capture_seconds(previous.get("capturedAt"))
    result = {"witnesses": [], "candidate": None, "repairs": []}
    if not before or now is None or old_time is None or now <= old_time:
        return result

    def signature(meld):
        return (meld.get("type"), tuple(sorted(meld.get("tiles", []))))

    seats = ("east", "south", "west", "north")
    rows = current.get("opponentDiscards", [])
    missing = set(seats) - {row.get("seat") for row in rows}
    if len(rows) != 3 or len(missing) != 1:
        return result
    next_seat = seats[(seats.index(next(iter(missing))) + 1) % 4]

    def legal_call(meld, seat):
        tiles = meld.get("tiles", [])
        kind = meld.get("type")
        if any(not (t in {"E", "S", "W", "N", "P", "F", "C"}
                    or len(t) == 2 and t[0] in "0123456789" and t[1] in "mps") for t in tiles):
            return False
        if kind == "chi":
            if seat != next_seat or len(tiles) != 3:
                return False
            if any(len(t) != 2 or t[1] not in "mps" or t[0] not in "0123456789" for t in tiles):
                return False
            ranks = sorted(5 if t[0] == "0" else int(t[0]) for t in tiles)
            return len({t[1] for t in tiles}) == 1 and ranks == list(range(ranks[0], ranks[0] + 3))
        return (kind in {"pon", "minkan"} and len(tiles) == (4 if kind == "minkan" else 3)
                and bool(tiles) and all(same_physical_tile(tiles[0], t) for t in tiles))

    witnesses = []
    for row in rows:
        seat = row.get("seat")
        prior = next((r for r in previous.get("opponentDiscards", []) if r.get("seat") == seat), {})
        old, new = prior.get("melds", []), row.get("melds", [])
        if row.get("meldsObserved") is not True:
            continue
        for witness in previous.get("_ownRiverCallWitnesses", []):
            captured = public_capture_seconds(witness.get("capturedAt"))
            if (witness.get("before") == before and witness.get("seat") == seat
                    and captured is not None and 0 <= now - captured <= 120
                    and any(signature(m) == signature(witness["meld"]) for m in new)):
                witnesses.append(witness)
        if (prior.get("meldsObserved") is True and len(new) > len(old)
                and [signature(m) for m in new[:len(old)]] == [signature(m) for m in old]):
            for meld in new[len(old):]:
                if legal_call(meld, seat) and any(t in meld.get("tiles", []) for t in before):
                    witness = {"before": list(before), "seat": seat, "meld": meld,
                               "capturedAt": current["capturedAt"]}
                    if not any(w["seat"] == seat and signature(w["meld"]) == signature(meld)
                               for w in witnesses):
                        witnesses.append(witness)
    result["witnesses"] = witnesses
    aligned = (current.get("doraIndicators", [])[:len(previous.get("doraIndicators", []))]
               == previous.get("doraIndicators", [])
               and current.get("ownMeldsObserved") is True
               and current.get("ownMeldTiles", []) == previous.get("ownMeldTiles", []))
    if not aligned or current.get("ownDiscardsObserved") is not True or not latest:
        return result
    if latest[:len(before)] == before:
        return result
    # Exactly one deletion must explain the retained prefix. Physical red-five
    # identity must occur in the new meld; base-five equivalence is insufficient.
    choices = []
    for index, tile in enumerate(before):
        retained = before[:index] + before[index + 1:]
        if latest[:len(retained)] == retained:
            for witness in witnesses:
                if tile in witness["meld"].get("tiles", []):
                    choices.append((index, retained, witness))
    if len(choices) != 1:
        return result
    # A newly called discard was the last own river tile before that call.
    # An older missing tile cannot be explained by a newly introduced meld.
    if choices[0][0] != len(before) - 1:
        return result
    known = [*current.get("doraIndicators", []), *latest, *current.get("ownMeldTiles", []),
             *[t for row in rows for t in [*row.get("discards", []),
                *[t for m in row.get("melds", []) for t in m.get("tiles", [])]]]]
    counts = Counter("5" + t[1:] if t.startswith("0") else t for t in known)
    if any(count > 4 for count in counts.values()):
        return result
    index, retained, witness = choices[0]
    candidate = previous.get("_ownRiverWithdrawalCandidate") or {}
    first_time = public_capture_seconds(candidate.get("capturedAt"))
    gap = now - first_time if first_time is not None else None
    agrees = (candidate.get("before") == before and candidate.get("index") == index
              and candidate.get("seat") == witness["seat"]
              and signature(candidate.get("meld", {})) == signature(witness["meld"])
              and bool(candidate.get("discards"))
              and latest[:len(candidate["discards"])] == candidate["discards"])
    if agrees and gap is not None and 0.5 <= gap <= 30:
        result["repairs"] = [{"before": list(before), "retained": retained, "after": list(latest),
            "index": index, "tile": before[index], "seat": witness["seat"], "meld": witness["meld"],
            "firstCapturedAt": candidate["capturedAt"], "confirmedCapturedAt": current["capturedAt"]}]
        result["witnesses"] = []
    elif agrees and gap is not None and 0 <= gap < 0.5:
        result["candidate"] = candidate
    else:
        result["candidate"] = {"before": list(before), "index": index, "seat": witness["seat"],
            "meld": witness["meld"], "discards": list(latest), "capturedAt": current["capturedAt"]}
    return result


def merge_public_observations(
    previous: dict[str, Any] | None, current: dict[str, Any],
    confirmed_open_melds: int | None = None,
) -> dict[str, Any]:
    """Grow public history; corroborate corrections to stale opponent tiles."""
    if previous is None:
        return current

    def growing(prior: list[Any], latest: list[Any]) -> list[Any]:
        return latest if len(latest) >= len(prior) and latest[:len(prior)] == prior else prior

    own_discards = growing(previous.get("ownDiscards", []), current.get("ownDiscards", []))
    withdrawal = corroborate_own_river_withdrawal(previous, current)
    if withdrawal["repairs"]:
        own_discards = withdrawal["repairs"][0]["after"]
    dora = growing(previous.get("doraIndicators", []), current.get("doraIndicators", []))
    river_candidates: dict[str, Any] = {}
    river_repairs = []

    opponents = []
    for latest in current.get("opponentDiscards", []):
        prior = next((item for item in previous.get("opponentDiscards", [])
                      if item.get("seat") == latest.get("seat")), {})
        prior_river = prior.get("discards", [])
        latest_river = latest.get("discards", [])
        river = growing(prior_river, latest_river)
        captured_at = current.get("capturedAt")
        captured_seconds = public_capture_seconds(captured_at)
        # A transient false tile used to pin an opponent's entire river
        # forever. Require two complete safe observations, at least two more tiles,
        # ordered independent captures and agreement with subsequent growth.
        # A single false identity can also freeze a longer prefix. Correct
        # only that one position, with the other established identities and
        # the own river/dora still agreeing. Never replace a longer history
        # wholesale or use evidence from a different own-river baseline.
        aligned = all(current.get(key, [])[:len(previous.get(key, []))]
                      == previous.get(key, []) for key in ("ownDiscards", "doraIndicators"))
        single_error = (len(prior_river) >= 3 and aligned
                        and len(latest_river) >= len(prior_river)
                        and sum(before != after for before, after in
                                zip(prior_river, latest_river)) == 1)
        if (river != latest_river and (1 <= len(prior_river) <= 2 or single_error)
                and len(latest_river) >= len(prior_river) + 2
                and latest.get("discardsObserved") is True and captured_seconds is not None):
            seat = latest["seat"]
            candidate = previous.get("_opponentRiverCandidates", {}).get(seat, {})
            candidate_seconds = public_capture_seconds(candidate.get("capturedAt"))
            gap = captured_seconds - candidate_seconds if candidate_seconds is not None else None
            candidate_river = candidate.get("discards", [])
            agrees = (candidate.get("before") == prior_river and bool(candidate_river)
                      and latest_river[:len(candidate_river)] == candidate_river)
            if agrees and gap is not None and 0.5 <= gap <= 30:
                river = latest_river
                river_repairs.append({
                    "seat": seat, "before": prior_river, "after": latest_river,
                    "firstCapturedAt": candidate["capturedAt"], "confirmedCapturedAt": captured_at,
                })
            elif agrees and gap is not None and gap < 0.5:
                # Repeated/out-of-order captures cannot corroborate or replace
                # the first candidate; keep waiting for independent evidence.
                river_candidates[seat] = candidate
            else:
                river_candidates[seat] = {
                    "before": prior_river, "discards": latest_river, "capturedAt": captured_at,
                }
        latest_melds = latest.get("melds", [])
        prior_melds = prior.get("melds", [])
        if latest.get("meldsObserved") is True and len(latest_melds) == 0:
            merged_melds = []
        else:
            merged_melds = latest_melds if len(latest_melds) >= len(prior_melds) else prior_melds
        opponents.append({
            **latest,
            "discards": river,
            "riichiDeclared": bool(prior.get("riichiDeclared") or latest.get("riichiDeclared")),
            "melds": merged_melds,
        })
    current_own_melds = current.get("ownMelds", [])
    current_own_meld_tiles = current.get("ownMeldTiles", [])
    if confirmed_open_melds == 0 and current.get("ownMeldsObserved") is True \
            and len(current_own_melds) == 0:
        # A closed hand plus a complete empty meld-region observation is
        # stronger evidence than an earlier false positive.  Real confirmed
        # calls remain monotonic below.
        own_melds = []
        own_meld_tiles = []
    else:
        own_meld_tiles = growing(previous.get("ownMeldTiles", []), current_own_meld_tiles)
        own_melds = current_own_melds if len(current_own_melds) >= len(previous.get("ownMelds", [])) \
            else previous.get("ownMelds", [])
    # A fresh complete meld can conflict with a stale river tile while its
    # correction is still awaiting corroboration. Do not publish a fifth
    # copy in that intermediate state. Retain the prior meld evidence until
    # the river is repaired; the inventory limit itself remains unchanged.
    def normalize(tile):
        return "5" + tile[1:] if tile.startswith("0") else tile
    pending_old_tiles = {normalize(before)
                         for candidate in river_candidates.values()
                         for before, after in zip(candidate["before"], candidate["discards"])
                         if before != after}
    counts = Counter(normalize(tile) for tile in [*dora, *own_discards, *own_meld_tiles, *[
        tile for opponent in opponents for tile in [
            *opponent.get("discards", []),
            *[tile for meld in opponent.get("melds", []) for tile in meld.get("tiles", [])],
        ]
    ]])
    conflicts = {tile for tile in pending_old_tiles if counts[tile] > 4}
    deferred_melds = []
    if conflicts:
        for opponent in opponents:
            prior = next((item for item in previous.get("opponentDiscards", [])
                          if item.get("seat") == opponent["seat"]), {})
            prior_melds = prior.get("melds", [])
            new_melds = [meld for meld in opponent.get("melds", []) if meld not in prior_melds]
            if any(normalize(tile) in conflicts for meld in new_melds for tile in meld.get("tiles", [])):
                opponent["melds"] = prior_melds
                opponent["meldsObserved"] = False
                deferred_melds.append({"seat": opponent["seat"], "conflictingTiles": sorted(conflicts)})
    all_meld_tiles = [*own_meld_tiles, *[
        tile for opponent in opponents for meld in opponent.get("melds", []) for tile in meld.get("tiles", [])
    ]]
    other_visible = [
        *[tile for opponent in opponents for tile in opponent.get("discards", [])],
        *all_meld_tiles,
    ]
    hand_plan = current.get("handPlan") or previous.get("handPlan")
    return {
        **current,
        "doraIndicators": dora,
        "ownDiscards": own_discards,
        "_ownRiverCallWitnesses": withdrawal["witnesses"],
        "_ownRiverWithdrawalCandidate": withdrawal["candidate"],
        "ownRiverWithdrawals": withdrawal["repairs"],
        "ownRiichiDeclared": bool(previous.get("ownRiichiDeclared") or current.get("ownRiichiDeclared")),
        "ownMelds": own_melds,
        "ownMeldsObserved": current.get("ownMeldsObserved", previous.get("ownMeldsObserved")),
        "opponentDiscards": opponents,
        "_opponentRiverCandidates": river_candidates,
        "opponentRiverRepairs": river_repairs,
        "opponentMeldsDeferred": deferred_melds,
        "ownMeldTiles": own_meld_tiles,
        "allMeldTiles": all_meld_tiles,
        "otherVisibleTiles": other_visible,
        "acceptedTiles": len(dora) + len(own_discards) + len(other_visible),
        **({"handPlan": hand_plan} if hand_plan else {}),
    }


class PythonAutoOperator:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.root = Path(args.project).resolve()
        reference_directory = getattr(args, "screen_references", None)
        self.screen_references = load_references(
            Path(reference_directory) if reference_directory else self.root / "artifacts" / "live"
        )
        self.layout_path = Path(args.layout).resolve()
        self.templates = Path(args.templates).resolve()
        self.state_path = Path(args.state).resolve()
        self.public_state = with_match_length(load_json(self.state_path), getattr(args, "match_length", None))
        self.layout = load_json(self.layout_path)
        # Live calibration files focus on tiles and may omit static action
        # buttons. Reuse those fixed screen-space regions from the base layout.
        base_layout_path = self.root / "config" / "layout.json"
        if not self.layout.get("actionButtonRegions") and base_layout_path.exists():
            base_layout = load_json(base_layout_path)
            self.layout["actionButtonRegions"] = base_layout.get("actionButtonRegions", {})
        self.evaluator_env = load_secret_environment(self.root, args.env_file)
        self.evaluator_env = configure_evaluator_click_budget(
            self.evaluator_env, getattr(args, "force_auto_click_budget_ms", None), args.action_deadline_ms,
        )
        self.hand_clip = clip_for_hand(self.layout)
        action_regions = list(self.layout.get("actionButtonRegions", {}).values())
        self.action_clip = None
        if action_regions:
            left = min(region["x"] for region in action_regions)
            top = min(region["y"] for region in action_regions)
            right = max(region["x"] + region["width"] for region in action_regions)
            bottom = max(region["y"] + region["height"] for region in action_regions)
            self.action_clip = {"x": left, "y": top, "width": right - left, "height": bottom - top}
        own_river = self.layout.get("publicTileRegions", {}).get("ownDiscards")
        if not own_river:
            raise RuntimeError("layout.publicTileRegions.ownDiscards is required")
        self.river_clip = {key: own_river[key] for key in ("x", "y", "width", "height")}
        self.artifacts = Path(args.artifacts).resolve()
        self.frames = self.artifacts / "frames"
        self.frames.mkdir(parents=True, exist_ok=True)
        self.log_path = self.artifacts / "python-operator.jsonl"
        self.replays = self.artifacts / "replays"
        self.replays.mkdir(parents=True, exist_ok=True)
        self.pending_round_replays: list[Path] = []
        self.pending_match_replays: list[Path] = []
        self.ranked_match_in_progress = False
        self.ranked_match_finished = False
        self.last_ranked_navigation_deferred_state = None
        self.recognition_request_id = 0
        self.recognition_server = subprocess.Popen(
            ["node", "dist/src/recognition/recognitionServer.js", str(self.layout_path), str(self.templates), str(self.state_path)],
            cwd=self.root,
            env=self.evaluator_env,
            text=True,
            encoding="utf-8",
            errors="strict",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        ready_line = self.recognition_server.stdout.readline() if self.recognition_server.stdout else ""
        if not ready_line:
            raise RuntimeError("resident recognition server stopped during startup")
        ready = json.loads(ready_line)
        if ready.get("ready") is not True:
            raise RuntimeError(f"resident recognition server failed to initialize: {ready}")
        self.public_recognition_server: subprocess.Popen[str] | None = None
        self.public_recognition_thread: threading.Thread | None = None
        self.public_recognition_result: dict[str, Any] | None = None
        self.public_recognition_lock = threading.Lock()
        self.public_recognition_io_lock = threading.Lock()
        self.public_recognition_request_id = 0
        self.board_metadata_thread: threading.Thread | None = None
        self.board_metadata_result: dict[str, Any] | None = None
        self.board_metadata_cache: dict[str, Any] | None = None
        self.riichi_metadata_history: dict[str, Any] | None = None
        self.black_screen_seen_since: float | None = None
        self.black_screen_reload_attempts: list[float] = []
        self.black_screen_recovery_pending_outcome = False
        self.black_screen_navigation_since: float | None = None
        self.board_metadata_lock = threading.Lock()
        self.board_metadata_ocr_lock = threading.Lock()
        self.board_metadata_last_scan_at = 0.0
        self.board_metadata_last_scan_signature = None
        self.public_cache_generation = 0
        self.public_cache_last_frame_hash: str | None = None
        self.last_public_scan_at = 0.0
        self.cached_public_observation: dict[str, Any] | None = None
        # A public OCR append immediately after our click is independent
        # evidence, but not yet reliable enough to replace the trusted river.
        # Keep it pending until a second asynchronous scan agrees.
        self.pending_own_river_confirmation: list[str] | None = None
        if args.mode == "force-auto" and args.public_cache:
            try:
                self.public_recognition_server = subprocess.Popen(
                    [
                        "node", "dist/src/recognition/publicRecognitionServer.js",
                        str(self.layout_path), self.public_state.get("seat", "east"),
                    ],
                    cwd=self.root,
                    env=self.evaluator_env,
                    text=True,
                    encoding="utf-8",
                    errors="strict",
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=1,
                )
                public_ready_line = self.public_recognition_server.stdout.readline() \
                    if self.public_recognition_server.stdout else ""
                public_ready = json.loads(public_ready_line) if public_ready_line else {}
                if public_ready.get("ready") is not True:
                    raise RuntimeError(f"public recognition server failed to initialize: {public_ready}")
            except Exception as error:
                if self.public_recognition_server and self.public_recognition_server.poll() is None:
                    self.public_recognition_server.terminate()
                self.public_recognition_server = None
                self.log("public_cache_disabled", error=str(error))
        self.last_processed_hand: str | None = None
        # A failed raised-tile confirmation is different from an ordinary
        # retryable recognition failure.  Its first click may have selected
        # the tile, so another click on the same physical row could deselect
        # it.  Keep a fence until independent table evidence proves that the
        # turn advanced; a changed hand crop alone is expected when a tile is
        # raised and is specifically not such evidence.
        self.selection_uncertainty_latch: dict[str, Any] | None = None
        self.previous_public_observation: dict[str, Any] | None = None
        self.cached_concealed_tiles: list[str] | None = None
        self.pending_own_discard: dict[str, Any] | None = None
        self.cached_open_melds = 0
        self.dynamic_layout_required = False
        self.last_shanten: int | None = None
        self.screencast_session: CDPSession | None = None
        self.screencast_diagnostic = None
        self.latest_screencast_frame: bytes | None = None
        # Monotonic receipt time for the exact streamed frame above.  A
        # force-auto evaluator can finish after the short ranked click budget
        # even though the much longer action deadline is still healthy.  Keep
        # this separately from the evidence clock so a stale decision cannot
        # be clicked just because the table has not changed yet.
        self.latest_screencast_captured_at: float | None = None
        self.screencast_sequence = 0
        # Sequence of the last frame that could still precede this
        # operator's explicit pointer retreat.  A later frame is required
        # before force-auto may reuse it for hand recognition.
        self.pointer_retreat_screencast_sequence: int | None = None
        self.screencast_draw_occupied: bool | None = None
        self.screencast_draw_generation = 0
        self.rejected_screencast_size: tuple[int, int] | None = None
        # A full-width but shorter stream is not a transient tile animation:
        # it means the browser viewport has been replaced or resized.  Keep a
        # separate latch so the run loop can stop before it interprets a
        # non-game page as a compact/open hand.
        self.rejected_viewport_frame_streak = 0
        self.screen_loss_stop_requested = False
        # Ranked play must not silently turn a persistently too-slow decision
        # pipeline into repeated away-dialog resumes and automatic discards.
        self.ranked_click_budget_expiry_streak = 0
        self.ranked_click_budget_safety_stop_requested = False
        self.pending_post_call_discard = False
        self.pending_post_call_started_at: float | None = None
        self.restart_open_hand_probe_hash: str | None = None
        self.open_meld_candidate: int | None = None
        self.open_meld_candidate_frames: set[str] = set()
        self.closed_new_round_candidate_frames: set[str] = set()
        self.round_terminal_latched = False
        self.round_terminal_result_observed = False
        self.round_terminal_unknown_since: float | None = None
        self.round_terminal_recovery: dict[str, Any] | None = None
        # A result overlay may animate into a dark ranked screen that the
        # generic classifier also recognizes as matchmaking.  Do not let a
        # ranked loop treat that ambiguous first transition as proof that a
        # fresh reservation is live.
        self.ranked_terminal_transition_pending = False
        self.ranked_terminal_transition_stop_requested = False
        # The fast screencast gate handles result overlays before the regular
        # full-screen branch.  Keep its completed friend-run stop request
        # explicit so that it cannot advance into matchmaking on the next
        # frame.
        self.match_completed_stop_requested = False
        self.last_ranked_loop_state: str | None = None
        self.last_ranked_loop_click_at = 0.0
        self.login_button_clicked_at: float | None = None
        self.result_screen_advanced: str | None = None
        self.action_evidence_started_at: float | None = None
        self.action_budget_started_at: float | None = None
        self.action_evidence_kind: str | None = None
        self.action_evidence_generation: int | None = None
        self.last_action_clicked_at: float | None = None
        self.action_evidence_last_seen_at: float | None = None
        if self.log_path.exists():
            for line in reversed(self.log_path.read_text(encoding="utf-8").splitlines()):
                try:
                    previous = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if previous.get("event") != "decision":
                    continue
                decision = previous.get("evaluation", {}).get("decision", {})
                selected_id = decision.get("selectedActionId")
                candidate = next((item for item in decision.get("candidates", []) if item.get("actionId") == selected_id), None)
                if candidate is not None:
                    self.last_shanten = candidate.get("shanten")
                break
        self.armed = True

    def mark_action_evidence(
        self, kind: str, *, observed_at: float | None = None,
        gate_generation: int | None = None, supersede: bool = False,
        budget_observed_at: float | None = None,
    ) -> None:
        """Latch first visible evidence; later recognition must not reset the SLA clock."""
        seen_at = time.monotonic() if observed_at is None else observed_at
        previous_started = getattr(self, "action_evidence_started_at", None)
        previous_kind = getattr(self, "action_evidence_kind", None)
        if previous_started is not None and previous_kind == kind and not supersede:
            self.action_evidence_last_seen_at = seen_at
            self.action_evidence_generation = gate_generation
            return
        if previous_started is not None and not supersede:
            # A different gate must not refresh the old evidence. In
            # particular, draw frames following a vanished reaction prompt
            # previously kept the reaction deadline alive indefinitely.
            return
        if previous_started is not None:
            self.log(
                "action_deadline_superseded",
                previousActionKind=previous_kind,
                actionKind=kind,
                previousGateGeneration=getattr(self, "action_evidence_generation", None),
                gateGeneration=gate_generation,
            )
        self.action_evidence_started_at = seen_at
        self.action_budget_started_at = budget_observed_at if budget_observed_at is not None else seen_at
        self.action_budget_draw_generation = getattr(self, "screencast_draw_generation", None)
        self.action_evidence_kind = kind
        self.action_evidence_generation = gate_generation
        self.action_evidence_last_seen_at = budget_observed_at if budget_observed_at is not None else seen_at
        self.last_action_clicked_at = None
        self.log("action_deadline_started", actionKind=kind, deadlineMs=self.configured_action_deadline_ms())

    def configured_action_deadline_ms(self) -> int:
        return getattr(getattr(self, "args", None), "action_deadline_ms", ACTION_DEADLINE_MS)

    def action_timing(self, decision_started_at: float | None = None, *, clear: bool = False) -> dict[str, Any]:
        clicked_at = getattr(self, "last_action_clicked_at", None) or time.monotonic()
        timing = action_deadline_timing(
            getattr(self, "action_evidence_started_at", None), decision_started_at, clicked_at,
            self.configured_action_deadline_ms(),
        )
        timing["actionKind"] = getattr(self, "action_evidence_kind", None)
        if clear:
            self.action_evidence_started_at = None
            self.action_budget_started_at = None
            self.action_evidence_kind = None
            self.action_evidence_generation = None
            self.last_action_clicked_at = None
            self.action_evidence_last_seen_at = None
        return timing

    def clear_discard_evidence_on_confirmed_opponent_turn(self) -> None:
        """Forget an earlier false draw gate only after a verified empty draw slot."""
        if getattr(self, "action_evidence_kind", None) != "discard":
            return
        self.action_timing(clear=True)
        self.log("discard_deadline_cleared", reason="confirmed_opponent_turn")

    def observe_post_call_timeout_river(self, observation: dict[str, Any]) -> None:
        """Corroborate a post-call automatic discard in two newer public captures."""
        latch = getattr(self, "post_call_timeout_recovery", None)
        if not latch or not getattr(self, "pending_post_call_discard", False):
            return
        captured = public_capture_seconds(observation.get("capturedAt"))
        river = observation.get("ownDiscards")
        baseline = latch["baseline"]
        if (captured is None or captured <= latch["after"]
                or observation.get("ownDiscardsObserved") is not True
                or not isinstance(river, list) or len(river) != len(baseline) + 1
                or river[:len(baseline)] != baseline):
            latch.pop("candidate", None)
            latch.pop("candidateAt", None)
            latch.pop("confirmedAt", None)
            latch.pop("confirmedMonotonic", None)
            return
        if latch.get("candidate") == river and captured > latch.get("candidateAt", captured):
            latch["confirmedAt"] = captured
            latch["confirmedMonotonic"] = time.monotonic()
        elif captured > latch.get("candidateAt", 0):
            latch["candidate"] = list(river)
            latch["candidateAt"] = captured
            latch.pop("confirmedAt", None)
            latch.pop("confirmedMonotonic", None)

    def recover_post_call_timeout(self, *, frame: bytes, captured_at: float | None,
                                  open_melds: int | None, draw_occupied: bool) -> bool:
        """Release a post-call latch only after an independently observed discard."""
        latch = getattr(self, "post_call_timeout_recovery", None)
        if (not latch or not getattr(self, "pending_post_call_discard", False)
                or getattr(self, "selection_uncertainty_latch", None)
                or not isinstance(captured_at, (int, float))
                or captured_at < latch.get("confirmedMonotonic", float("inf"))
                or not latch.get("confirmedAt")
                or open_melds != latch["openMelds"] or draw_occupied
                or geometric_open_meld_count(frame, self.layout) != open_melds):
            return False
        age = self.force_auto_action_evidence_age_ms()
        budget = self.force_auto_click_budget_ms()
        if age is None or budget is None or age < budget:
            return False
        self.pending_post_call_discard = False
        self.pending_post_call_started_at = None
        self.post_call_timeout_recovery = None
        self.cached_concealed_tiles = None
        self.clear_discard_evidence_on_confirmed_opponent_turn()
        self.log("post_call_timeout_recovered", ownDiscards=latch["candidate"],
                 firstObservedAt=latch["candidateAt"], secondObservedAt=latch["confirmedAt"],
                 openMelds=open_melds, reason="confirmed_river_append_and_empty_draw")
        return True

    @staticmethod
    def quick_draw_occupied(*, open_melds: int, closed_slot_occupied: bool,
                            open_slot_occupied: bool) -> bool:
        """The fixed closed-hand slot is not a draw slot after a call."""
        return open_slot_occupied if open_melds > 0 else closed_slot_occupied

    @staticmethod
    def restart_open_hand_probe_needed(*, frame_hash: str | None,
                                       last_hash: str | None, cached_open_melds: int) -> bool:
        return frame_hash is not None and frame_hash != last_hash and cached_open_melds == 0

    def supersede_reaction_on_verified_draw(
        self, *, draw_occupied: bool, exact_open_melds: int | None,
        geometric_open_melds: int | None,
    ) -> bool:
        closed_draw = draw_occupied and self.cached_open_melds == 0 \
            and exact_open_melds in {None, 0}
        open_draw = draw_occupied and geometric_open_melds is not None \
            and exact_open_melds == geometric_open_melds
        if not (closed_draw or open_draw) or self.action_evidence_kind not in {"reaction", "win"}:
            return False
        self.mark_action_evidence(
            "discard", gate_generation=self.screencast_sequence, supersede=True,
        )
        return True

    def action_deadline_remaining_ms(self) -> int:
        started = getattr(self, "action_evidence_started_at", None)
        if started is None:
            return self.configured_action_deadline_ms()
        return max(0, self.configured_action_deadline_ms() - round((time.monotonic() - started) * 1000))

    def force_auto_click_budget_ms(self) -> int | None:
        """Return the optional short decision-to-click budget for ranked play."""
        budget = getattr(getattr(self, "args", None), "force_auto_click_budget_ms", None)
        return budget if isinstance(budget, int) and budget > 0 else None

    def force_auto_capture_age_ms(self, captured_at: float | None) -> int | None:
        """Age of the actual frame receipt used for a force-auto decision.

        This deliberately uses the CDP receipt timestamp, not the time a
        temporary PNG happened to be written.  File-write time can make an
        already old streamed frame look fresh and start a recognizer that no
        longer has any chance of producing a safe ranked click.
        """
        if captured_at is None:
            return None
        return max(0, round((time.monotonic() - captured_at) * 1000))

    def force_auto_same_draw_grace_ms(self, captured_at: float | None) -> int:
        """Extend only a verified current draw, never stale frame freshness."""
        budget = self.force_auto_click_budget_ms()
        generation = getattr(self, "action_budget_draw_generation", None)
        if (budget is None or budget > FORCE_AUTO_SHORT_CLICK_BUDGET_MAX_MS
                or captured_at is None or generation is None
                or generation != getattr(self, "screencast_draw_generation", None)
                or getattr(self, "screencast_draw_occupied", None) is not True
                or getattr(self, "action_evidence_kind", None) != "discard"
                or getattr(self, "selection_uncertainty_latch", None)):
            return 0
        return max(0, FORCE_AUTO_SAME_DRAW_ACTION_BUDGET_MS - budget)

    def force_auto_action_evidence_age_ms(self) -> int | None:
        """Age of the current self-action, when the turn gate observed one.

        A fresh screencast receipt is not a fresh Mahjong Soul turn.  In
        particular, an expensive metadata refresh can produce a recent hand
        frame several seconds after the self-turn gate first opened.  The
        action clock includes that earlier observation, even when a verified
        unchanged draw receives the bounded additional-time allowance. Image
        freshness remains a separate short budget. The game timer is not
        observed, so an unchanged generation never proves how much of the
        additional 20 seconds remains.
        """
        started = getattr(self, "action_budget_started_at", None)
        if started is None:
            started = getattr(self, "action_evidence_started_at", None)
        if not isinstance(started, (int, float)):
            return None
        return max(0, round((time.monotonic() - started) * 1000))

    def force_auto_has_recognition_window(self, captured_at: float | None) -> bool:
        """Whether a ranked receipt has enough time left for expensive work.

        A missing timestamp remains eligible because the final click guard is
        the authority in that case.  The short-window admission applies only
        to the 2600ms ranked mode; longer friend-match functional runs retain
        their normal recognition path.
        """
        budget = self.force_auto_click_budget_ms()
        if budget is None or budget > FORCE_AUTO_SHORT_CLICK_BUDGET_MAX_MS:
            return True
        age_ms = self.force_auto_capture_age_ms(captured_at)
        return age_ms is None or budget - age_ms >= FORCE_AUTO_MIN_RECOGNITION_WINDOW_MS

    def require_force_auto_click_budget(
        self, captured_at: float | None, *, phase: str,
        include_action_evidence: bool = True,
    ) -> None:
        """Fail closed when a force-auto decision is based on an old frame.

        ``action_deadline_ms`` is deliberately long in 300+0 functional
        tests.  It must not accidentally permit a ranked 2600ms decision to
        click a hand captured several seconds before recognition completed.
        Re-observation is safe; clicking that frame is not.
        """
        budget = self.force_auto_click_budget_ms()
        if budget is None:
            return
        capture_age_ms = self.force_auto_capture_age_ms(captured_at)
        # The self-turn gate bounds tile choices, but it does not bound a
        # reaction PASS.  PASS is re-certified immediately from its own
        # stable button affordance and a stale self-turn latch can otherwise
        # suppress that safe, prompt-local action indefinitely.
        action_evidence_age_ms = (
            self.force_auto_action_evidence_age_ms()
            if include_action_evidence else None
        )
        elapsed_ms = max(age for age in (capture_age_ms, action_evidence_age_ms) if age is not None) \
            if capture_age_ms is not None or action_evidence_age_ms is not None else None
        if elapsed_ms is None:
            return
        effective_budget = budget + (self.force_auto_same_draw_grace_ms(captured_at)
                                     if include_action_evidence else 0)
        capture_valid = capture_age_ms is None or capture_age_ms < budget
        evidence_valid = action_evidence_age_ms is None or action_evidence_age_ms < effective_budget
        if capture_valid and evidence_valid:
            if elapsed_ms >= budget:
                self.log("force_auto_same_draw_grace_applied", phase=phase,
                         clickBudgetMs=budget, effectiveActionBudgetMs=effective_budget,
                         actionEvidenceAgeMs=action_evidence_age_ms,
                         captureAgeBeforeDecisionMs=capture_age_ms,
                         drawGeneration=getattr(self, "screencast_draw_generation", None))
                if action_evidence_age_ms is not None \
                        and action_evidence_age_ms > FORCE_AUTO_NORMAL_TURN_BUDGET_MS:
                    self.log("force_auto_same_draw_additional_time_used", phase=phase,
                             clickBudgetMs=budget, effectiveActionBudgetMs=effective_budget,
                             normalTurnBudgetMs=FORCE_AUTO_NORMAL_TURN_BUDGET_MS,
                             actionEvidenceAgeMs=action_evidence_age_ms,
                             captureAgeBeforeDecisionMs=capture_age_ms,
                             drawGeneration=getattr(self, "screencast_draw_generation", None),
                             remainingGameExtraTimeMs=None,
                             reason="remaining_game_timer_not_observed")
            return
        timing_payload = {
            "phase": phase,
            "clickBudgetMs": budget,
            "captureAgeBeforeDecisionMs": capture_age_ms,
            "decisionBudgetMs": max(0, budget - elapsed_ms),
        }
        if action_evidence_age_ms is not None:
            timing_payload["actionEvidenceAgeMs"] = action_evidence_age_ms
        if effective_budget != budget:
            timing_payload["effectiveActionBudgetMs"] = effective_budget
        self.log(
            "force_auto_click_budget_expired",
            **timing_payload,
        )
        # A stale discard or win decision means the ranked action pipeline is
        # persistently unsafe and must eventually stop.  A call is different:
        # declining an expired chi/pon is the safe legal outcome.  Counting
        # repeated re-observations of that *same* transient call prompt as
        # ranked failures turns a conservative no-click into an away-dialog
        # auto-discard for the rest of the live match.
        is_expired_optional_call = phase == "before_reaction_call_click"
        if getattr(getattr(self, "args", None), "ranked_loop", False) and not is_expired_optional_call:
            streak = getattr(self, "ranked_click_budget_expiry_streak", 0) + 1
            self.ranked_click_budget_expiry_streak = streak
            if streak >= 3:
                self.ranked_click_budget_safety_stop_requested = True
                self.log(
                    "ranked_click_budget_safety_stop",
                    expiryStreak=streak,
                    clickBudgetMs=budget,
                    effectiveActionBudgetMs=effective_budget,
                    captureAgeBeforeDecisionMs=capture_age_ms,
                    **({"actionEvidenceAgeMs": action_evidence_age_ms}
                       if action_evidence_age_ms is not None else {}),
                    reason="three_consecutive_force_auto_click_budget_expiries",
                )
        raise RetryableSafetyAbort(
            "force-auto click budget expired before safe click; reobserve current hand"
        )

    def require_force_auto_discard_selection_window(self, captured_at: float | None) -> None:
        """Reserve time for the observed second click of a discard gesture.

        Checking the ordinary budget immediately before the *first* click is
        insufficient: selecting a tile is not a discard, and the client can
        auto-tsumogiri the draw while the operator waits for a screencast
        receipt proving that selected tile's raised hitbox.  This admission
        guard leaves the measured selection/confirmation reserve before any
        hand input is sent.
        """
        budget = self.force_auto_click_budget_ms()
        if budget is None or budget > FORCE_AUTO_SHORT_CLICK_BUDGET_MAX_MS:
            return
        capture_age_ms = self.force_auto_capture_age_ms(captured_at)
        action_evidence_age_ms = self.force_auto_action_evidence_age_ms()
        elapsed_ms = max(age for age in (capture_age_ms, action_evidence_age_ms)
                         if age is not None) \
            if capture_age_ms is not None or action_evidence_age_ms is not None else None
        effective_budget = budget + self.force_auto_same_draw_grace_ms(captured_at)
        remaining_ms = min(
            budget - capture_age_ms if capture_age_ms is not None else budget,
            effective_budget - action_evidence_age_ms if action_evidence_age_ms is not None else budget,
        )
        if elapsed_ms is None or remaining_ms >= FORCE_AUTO_DISCARD_SELECTION_RESERVE_MS:
            return
        self.log(
            "force_auto_discard_selection_window_insufficient",
            clickBudgetMs=budget,
            **({"effectiveActionBudgetMs": effective_budget} if effective_budget != budget else {}),
            reserveMs=FORCE_AUTO_DISCARD_SELECTION_RESERVE_MS,
            captureAgeBeforeSelectionMs=capture_age_ms,
            **({"actionEvidenceAgeMs": action_evidence_age_ms}
               if action_evidence_age_ms is not None else {}),
            remainingMs=max(0, remaining_ms),
        )
        raise RetryableSafetyAbort(
            "force-auto discard selection lacks time for confirmed second click; reobserve current hand"
        )

    def reset_ranked_click_budget_expiry_streak(self) -> None:
        """A confirmed action proves the ranked click path recovered."""
        if getattr(self, "ranked_click_budget_expiry_streak", 0):
            self.ranked_click_budget_expiry_streak = 0

    def require_action_deadline(self) -> None:
        remaining = self.action_deadline_remaining_ms()
        if remaining <= 0:
            timing = self.action_timing()
            self.log("action_deadline_expired", actionTiming=timing)
            raise RetryableSafetyAbort("five-second action deadline expired before safe click")

    def close(self) -> None:
        if self.screencast_session is not None:
            try:
                self.screencast_session.send("Page.stopScreencast")
                self.screencast_session.detach()
            except Exception:
                pass
            self.screencast_session = None
        diagnostic = getattr(self, "screencast_diagnostic", None)
        if diagnostic is not None:
            self.log("screencast_diagnostic_closed", **diagnostic.close())
            self.screencast_diagnostic = None
        if self.recognition_server.poll() is None:
            self.recognition_server.terminate()
            try:
                self.recognition_server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.recognition_server.kill()
        if self.public_recognition_server and self.public_recognition_server.poll() is None:
            if self.public_recognition_server.stdin:
                self.public_recognition_server.stdin.close()
            try:
                self.public_recognition_server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.public_recognition_server.terminate()
                try:
                    self.public_recognition_server.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.public_recognition_server.kill()

    def request_public_recognition(self, request: dict[str, Any]) -> dict[str, Any]:
        # The background cache and prompt recognition share one resident model.
        # Serialize each complete exchange so neither consumes the other's reply.
        with self.public_recognition_io_lock:
            server = self.public_recognition_server
            if not server or server.poll() is not None or not server.stdin or not server.stdout:
                raise RuntimeError("public recognition server pipes are unavailable")
            server.stdin.write(json.dumps(request) + "\n")
            server.stdin.flush()
            line = server.stdout.readline()
            if not line:
                raise RuntimeError("public recognition server closed its output")
            response = json.loads(line)
            if response.get("id") != request["id"]:
                raise RuntimeError("public recognition response id mismatch")
            if response.get("error"):
                raise RuntimeError(response["error"])
            return response["result"]

    def schedule_public_recognition(
        self, screenshot: bytes, *, force: bool = False, verified_match: bool = False,
        include_hand_plan: bool = True,
    ) -> None:
        server = self.public_recognition_server
        if not server or server.poll() is not None:
            return
        if self.public_recognition_thread and self.public_recognition_thread.is_alive():
            return
        # Use the same gameplay admission rule as board_metadata, rather than
        # force-auto's permissive unknown-screen fallback. UI labels in a friend
        # room can otherwise become persistent dora/river cache entries.
        try:
            with Image.open(io.BytesIO(screenshot)) as image:
                if image.size != (1920, 1080):
                    return
            screen_state = "match" if verified_match else classify_screen(screenshot, {})[0]
        except Exception:
            return
        if screen_state != "match":
            return
        frame_hash = perceptual_hash(screenshot)
        if not force and frame_hash == self.public_cache_last_frame_hash:
            return
        self.public_cache_last_frame_hash = frame_hash
        captured_at = datetime.now(timezone.utc).isoformat()
        frame_path = self.frames / f"{utc_stamp()}.public-cache.jpg"
        frame_path.write_bytes(screenshot)
        self.public_recognition_request_id += 1
        request_id = self.public_recognition_request_id
        generation = self.public_cache_generation

        def recognize() -> None:
            envelope: dict[str, Any]
            try:
                result = self.request_public_recognition({
                    "id": request_id, "screenshot": str(frame_path), "capturedAt": captured_at,
                    **({"concealedTiles": self.cached_concealed_tiles,
                        "openMelds": self.cached_open_melds,
                        "seat": self.public_state.get("seat", "east"),
                        "round": self.public_state.get("round", "unknown")}
                       if include_hand_plan else {}),
                })
                envelope = {"generation": generation, "result": result}
            except Exception as error:
                envelope = {"generation": generation, "error": str(error)}
            with self.public_recognition_lock:
                self.public_recognition_result = envelope

        self.public_recognition_thread = threading.Thread(target=recognize, daemon=True)
        self.public_recognition_thread.start()

    def prewarm_startup_context(self, frame: bytes | None, *, verified_match: bool) -> None:
        """Overlap verified startup frames with independent context workers.

        This does not authorize a turn or alter its clock.  Room/transition
        frames must never populate public caches, and a prewarm must not build
        a hand plan using a seat or round that OCR has not verified yet.
        """
        if not verified_match or not frame:
            return
        try:
            with Image.open(io.BytesIO(frame)) as image:
                if image.size != (1920, 1080):
                    return
        except Exception:
            return
        if getattr(self.args, "board_metadata", False):
            self.schedule_board_metadata(frame)
        if getattr(self.args, "public_cache", False):
            self.schedule_public_recognition(frame, verified_match=True, include_hand_plan=False)

    def schedule_periodic_public_recognition(
        self, screenshot: bytes, *, now: float | None = None, verified_match: bool = False,
    ) -> bool:
        """Refresh dora and other public tiles independently of turn state."""
        if not getattr(self.args, "public_cache", False) or not self.public_recognition_server:
            return False
        observed_at = time.monotonic() if now is None else now
        interval = max(0.1, float(getattr(self.args, "public_scan_interval", 2.0)))
        pending = getattr(self, "pending_own_discard", None)
        registered_at = pending.get("registeredMonotonic") if pending else None
        receipt_burst = isinstance(registered_at, (int, float)) and 0 <= observed_at - registered_at < 3.0
        latch = getattr(self, "selection_uncertainty_latch", None) or {}
        candidate_at = latch.get("riverBurstStartedMonotonic")
        uncertainty_burst = isinstance(candidate_at, (int, float)) and 0 <= observed_at - candidate_at < 3.0
        if receipt_burst or uncertainty_burst:
            # Seek the same independently corroborated river receipt sooner,
            # while the other players act. Do not force repeated recognition
            # of the same frame: the normal frame-hash gate remains in place.
            # Bound the burst even when an expected discard was called away.
            interval = min(interval, 0.4)
        if observed_at - self.last_public_scan_at < interval:
            return False
        self.last_public_scan_at = observed_at
        self.schedule_public_recognition(screenshot, verified_match=verified_match,
                                         include_hand_plan=not (receipt_burst or uncertainty_burst))
        return True

    def poll_public_recognition(self) -> None:
        with self.public_recognition_lock:
            envelope = self.public_recognition_result
            self.public_recognition_result = None
        if not envelope:
            return
        if envelope.get("generation") != self.public_cache_generation:
            return
        if envelope.get("error"):
            self.log("public_cache_failed", error=envelope["error"])
            return
        self.accept_public_observation(envelope["result"])

    def selection_uncertainty_rearm_reason(
        self, draw_generation: int | None, public_observation: dict[str, Any] | None,
    ) -> str | None:
        """Return independently observed evidence that an uncertain click is stale.

        A visual hand change cannot clear this latch: it may be the exact
        selected-tile lift left by the first click.  The only local evidence
        accepted here is a subsequent draw generation, and the only public
        evidence is a *merged* own-river extension.  ``accept_public_observation``
        only preserves such an extension after its normal corroboration, so a
        one-frame OCR candidate cannot release this safety fence.
        """
        latch = getattr(self, "selection_uncertainty_latch", None)
        if not latch:
            return None
        baseline_generation = latch.get("drawGeneration")
        if (draw_generation is not None and baseline_generation is not None
                and draw_generation > baseline_generation
                and getattr(self, "screencast_draw_occupied", None) is True):
            return "new_draw_generation"
        baseline_river = latch.get("ownDiscards")
        current_river = (public_observation or {}).get("ownDiscards")
        if (isinstance(baseline_river, list) and isinstance(current_river, list)
                and len(current_river) > len(baseline_river)
                and current_river[:len(baseline_river)] == baseline_river):
            return "confirmed_own_river_append"
        return None

    def observe_uncertain_selection_river(self, current: dict[str, Any]) -> None:
        """Independently corroborate a post-abort own-river extension twice."""
        latch = getattr(self, "selection_uncertainty_latch", None)
        if not latch:
            return
        baseline = latch.get("ownDiscards")
        river = current.get("ownDiscards")
        captured = public_capture_seconds(current.get("capturedAt"))
        aborted = public_capture_seconds(latch.get("abortedAt"))
        def diagnostic(reason: str) -> None:
            candidate = latch.get("riverCandidate")
            candidate_river = candidate.get("river") if isinstance(candidate, dict) else None
            self.log("selection_uncertainty_river_observation", reason=reason,
                     capturedAt=current.get("capturedAt"),
                     baselineCount=len(baseline) if isinstance(baseline, list) else None,
                     observedCount=len(river) if isinstance(river, list) else None,
                     candidateCount=len(candidate_river) if isinstance(candidate_river, list) else None)
        if current.get("ownDiscardsObserved") is not True:
            diagnostic("river_not_observed")
            return
        if captured is None or aborted is None or captured <= aborted:
            diagnostic("capture_not_after_abort")
            return
        if (not isinstance(baseline, list) or not isinstance(river, list)
                or len(river) <= len(baseline) or river[:len(baseline)] != baseline):
            if not isinstance(baseline, list) or not isinstance(river, list):
                diagnostic("river_or_baseline_missing")
            elif len(river) <= len(baseline):
                diagnostic("no_extension")
            else:
                diagnostic("baseline_prefix_mismatch")
            latch.pop("riverCandidate", None)
            latch.pop("confirmedOwnDiscards", None)
            return
        candidate = latch.get("riverCandidate")
        if candidate and candidate["river"] == river and captured - candidate["captured"] >= 0.5:
            latch["confirmedOwnDiscards"] = list(river)
            diagnostic("confirmed")
        elif not candidate or candidate["river"] != river:
            diagnostic("candidate_changed" if candidate else "candidate_started")
            latch.pop("confirmedOwnDiscards", None)
            latch.setdefault("riverBurstStartedMonotonic", time.monotonic())
            latch["riverCandidate"] = {"river": list(river), "captured": captured}
        else:
            diagnostic("candidate_too_soon")

    def rearm_uncertain_selection_clock(self, draw_generation: int | None,
                                        observed_at: float | None) -> bool:
        """Supersede a stale discard clock only after a verified later turn."""
        latch = getattr(self, "selection_uncertainty_latch", None)
        if not latch or getattr(self, "action_evidence_kind", None) != "discard":
            return False
        baseline = latch.get("drawGeneration")
        if (not isinstance(baseline, int) or not isinstance(draw_generation, int)
                or draw_generation <= baseline
                or getattr(self, "screencast_draw_occupied", None) is not True):
            return False
        if latch.get("firstNewDrawObservedAt") is None and observed_at is not None:
            latch["firstNewDrawObservedAt"] = observed_at
        river = latch.get("confirmedOwnDiscards")
        original = latch.get("ownDiscards")
        first_seen = latch.get("firstNewDrawObservedAt")
        if (not isinstance(original, list) or not isinstance(river, list)
                or len(river) <= len(original) or river[:len(original)] != original
                or not isinstance(first_seen, (int, float))):
            return False
        self.mark_action_evidence("discard", observed_at=first_seen,
                                  gate_generation=draw_generation, supersede=True)
        self.log("selection_uncertainty_action_clock_rearmed", drawGeneration=draw_generation,
                 confirmedOwnDiscards=river)
        return True

    def selection_uncertainty_stop_due(self, now: float) -> bool:
        """Fail closed when a later draw has no corroborated own-river receipt.

        Draw-slot occupancy is susceptible to animation and delivery timing,
        so it may start the public-confirmation grace period but can never
        clear the latch or restart an action deadline by itself.
        """
        latch = getattr(self, "selection_uncertainty_latch", None)
        first_draw = (latch or {}).get("firstNewDrawObservedAt")
        return isinstance(first_draw, (int, float)) and now - first_draw >= \
            SELECTION_UNCERTAINTY_PUBLIC_CONFIRMATION_GRACE_SECONDS

    def accept_public_observation(self, current: dict[str, Any]) -> bool:
        """Apply one capture through the shared history and receipt guards."""
        prior = self.cached_public_observation
        captured = public_capture_seconds(current.get("capturedAt"))
        previous_capture = public_capture_seconds((prior or {}).get("capturedAt"))
        if captured is not None and previous_capture is not None and captured <= previous_capture:
            return False
        self.observe_post_call_timeout_river(current)
        self.observe_uncertain_selection_river(current)
        merged = merge_public_observations(prior, current, getattr(self, "cached_open_melds", 0))
        for repair in merged.get("opponentRiverRepairs", []):
            self.log("opponent_river_prefix_repaired", **repair)
        for deferred in merged.get("opponentMeldsDeferred", []):
            self.log("public_meld_evidence_deferred", reason="pending_river_correction_inventory_conflict",
                     **deferred)
        pending_discard = getattr(self, "pending_own_discard", None)
        receipt_prior = prior
        for withdrawal in merged.get("ownRiverWithdrawals", []):
            # The river change invalidates any concealed-cache inference. A
            # pending click must still get two fresh append observations after
            # its baseline is rebased; a call is not an own-discard receipt.
            self.cached_concealed_tiles = None
            self.pending_own_river_confirmation = None
            if pending_discard:
                receipts = [pending_discard, *pending_discard.get("earlierReceipts", [])]
                old = withdrawal["before"]
                if all(receipt.get("before", [])[:len(old)] == old for receipt in receipts):
                    for receipt in receipts:
                        before = receipt["before"]
                        i = withdrawal["index"]
                        receipt["before"] = before[:i] + before[i + 1:]
                        receipt.pop("riverWithdrawalCapturedAt", None)
                else:
                    self.log("own_discard_reconciliation_unresolved",
                             reason="called_discard_withdrawal_baseline_incompatible",
                             expected=pending_discard.get("tile"), before=pending_discard.get("before"),
                             concealedCacheInvalidated=True)
                    self.pending_own_discard = pending_discard = None
                receipt_prior = {**prior, "ownDiscards": list(withdrawal["retained"])}
            self.log("own_called_discard_withdrawal_verified", **withdrawal,
                     concealedCacheInvalidated=True)
        if prior is not None and pending_discard:
            prior_own = receipt_prior.get("ownDiscards", [])
            merged_own = merged.get("ownDiscards", [])
            if merged_own != prior_own:
                pending_discard.pop("riverWithdrawalCapturedAt", None)
                confirmed = getattr(self, "pending_own_river_confirmation", None)
                if confirmed == merged_own:
                    self.pending_own_river_confirmation = None
                    self.log("public_own_river_append_confirmed", ownDiscards=merged_own,
                             capturedAt=merged.get("capturedAt"))
                else:
                    self.pending_own_river_confirmation = list(merged_own)
                    # Do not let a single false tile identity alter safety,
                    # remaining-tile counts, or a later discard decision.
                    merged["ownDiscards"] = list(prior_own)
                    self.log("public_own_river_append_pending", expected=pending_discard.get("tile"),
                             observed=merged_own, capturedAt=merged.get("capturedAt"))
            elif (getattr(self, "pending_own_river_confirmation", None) is not None
                  and current.get("ownDiscards") == prior_own == pending_discard.get("before")
                  and current.get("capturedAt")):
                # A briefly visible discard can be called before a second
                # scan confirms it. Do not wait through the next turn for a
                # river tile that is gone. Two later baseline observations
                # retire the unconfirmed click and force fresh hand recognition;
                # they do not certify either a call or the requested discard.
                captured_at = current["capturedAt"]
                withdrawn_at = pending_discard.get("riverWithdrawalCapturedAt")
                if withdrawn_at and captured_at > withdrawn_at:
                    self.log(
                        "own_discard_reconciliation_unresolved",
                        reason="river_candidate_disappeared",
                        expected=pending_discard.get("tile"), before=prior_own,
                        confirmationCandidate=self.pending_own_river_confirmation,
                        baselineObservedAt=[withdrawn_at, captured_at],
                        concealedCacheInvalidated=True,
                    )
                    self.cached_concealed_tiles = None
                    self.pending_own_discard = None
                    self.pending_own_river_confirmation = None
                elif not withdrawn_at:
                    pending_discard["riverWithdrawalCapturedAt"] = captured_at
            else:
                pending_discard.pop("riverWithdrawalCapturedAt", None)
        def river_signature(observation: dict[str, Any]) -> tuple[Any, ...]:
            return (tuple(observation.get("ownDiscards", [])), tuple(sorted(
                (item["seat"], tuple(item.get("discards", [])))
                for item in observation.get("opponentDiscards", [])
            )))
        if prior is None or river_signature(prior) != river_signature(merged):
            self.previous_public_observation = prior
        self.cached_public_observation = merged
        self.log(
            "public_cache_updated",
            capturedAt=self.cached_public_observation.get("capturedAt"),
            recognitionLatencyMs=self.cached_public_observation.get("recognitionLatencyMs"),
            acceptedTiles=self.cached_public_observation.get("acceptedTiles"),
            detectedCandidates=self.cached_public_observation.get("detectedCandidates"),
            configuredRegions=self.cached_public_observation.get("configuredRegions"),
            handPlan=self.cached_public_observation.get("handPlan", {}).get("planId"),
            handPlanConfidence=self.cached_public_observation.get("handPlan", {}).get("confidence"),
        )
        return True

    def promote_reaction_public_observation(self, observation: dict[str, Any] | None) -> None:
        """Retain fresh prompt evidence even when the strategy passes the call."""
        if not observation or public_capture_seconds(observation.get("capturedAt")) is None:
            return
        if self.accept_public_observation(observation):
            # An in-flight scan predating this prompt must not restore its
            # old partial melds or contradict the new consensus candidate.
            self.public_cache_generation = getattr(self, "public_cache_generation", 0) + 1
            self.public_cache_last_frame_hash = None
            self.last_public_scan_at = 0.0

    def start_screencast_gate(self, page: Page) -> None:
        """Stream low-latency frames for the turn gate without CDP screenshots."""
        if self.args.mode != "force-auto" or self.screencast_session is not None:
            return
        session = page.context.new_cdp_session(page)
        diagnostic_path = getattr(self.args, "screencast_diagnostic", None)
        if diagnostic_path:
            self.screencast_diagnostic = ScreencastDiagnostic(diagnostic_path)

        def receive_frame(event: dict[str, Any]) -> None:
            try:
                receipt = time.monotonic()
                receipt_wall = time.time() if self.screencast_diagnostic is not None else None
                frame = base64.b64decode(event["data"])
                self.accept_screencast_frame(frame)
                if self.screencast_diagnostic is not None:
                    try:
                        self.screencast_diagnostic.offer(self.screencast_sequence, receipt,
                                                         event.get("metadata", {}), frame,
                                                         receipt_wall=receipt_wall)
                    except Exception as error:
                        self.log("screencast_diagnostic_offer_failed", error=str(error))
            finally:
                session.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})

        session.on("Page.screencastFrame", receive_frame)
        session.send("Page.startScreencast", {
            "format": "jpeg",
            "quality": 55,
            "maxWidth": self.layout["viewport"]["width"],
            "maxHeight": self.layout["viewport"]["height"],
            "everyNthFrame": 1,
        })
        self.screencast_session = session

    def accept_screencast_frame(self, frame: bytes) -> bool:
        """Publish only frames whose pixels match the calibrated viewport."""
        self.screencast_sequence += 1
        try:
            with Image.open(io.BytesIO(frame)) as image:
                actual = image.size
        except Exception:
            actual = (0, 0)
        expected = (
            int(self.layout["viewport"]["width"]),
            int(self.layout["viewport"]["height"]),
        )
        if actual != expected:
            # Never retain a previously valid action gate while Chrome is
            # emitting resized pixels. Fixed ROIs against the observed
            # 1058x1080 frame caused both PIL index and Sharp extract errors.
            self.latest_screencast_frame = None
            # Keep the frame and its receipt together.  A stale timestamp
            # must never be paired with a later fallback capture (or survive
            # as apparently valid evidence after this stream gate was
            # invalidated).
            self.latest_screencast_captured_at = None
            self.screencast_draw_occupied = None
            if actual != self.rejected_screencast_size:
                self.log("screencast_frame_rejected", expected=list(expected), actual=list(actual))
                self.rejected_screencast_size = actual
            # CDP can interleave tiny iframe/thumbnail captures with the
            # top-level stream.  Count only repeated full-width frames whose
            # height no longer matches the calibrated table viewport.  Three
            # such frames without a calibrated frame in between is evidence
            # that the table has been lost, not a momentary stream hiccup.
            if actual[0] == expected[0] and actual[1] > 0:
                self.rejected_viewport_frame_streak = \
                    getattr(self, "rejected_viewport_frame_streak", 0) + 1
                if self.rejected_viewport_frame_streak >= 3 \
                        and not getattr(self, "screen_loss_stop_requested", False):
                    self.screen_loss_stop_requested = True
                    self.log(
                        "screen_loss_stop", expected=list(expected), actual=list(actual),
                        rejectedViewportFrames=self.rejected_viewport_frame_streak,
                        gameplayClicks=0,
                        reason="repeated_full_width_screencast_dimension_mismatch",
                    )
            return False
        self.rejected_screencast_size = None
        self.rejected_viewport_frame_streak = 0
        self.latest_screencast_frame = frame
        self.latest_screencast_captured_at = time.monotonic()
        # A confirmed open hand draws next to its compact row. The closed-row
        # slot can be covered by exposed tiles throughout opponents' turns.
        draw_slot = open_hand_draw_slot(self.layout, getattr(self, "cached_open_melds", 0)) \
            or self.layout.get("drawSlot")
        if draw_slot:
            occupied = is_draw_slot_clip_occupied(crop_screenshot(frame, draw_slot))
            if occupied and self.screencast_draw_occupied is not True:
                self.screencast_draw_generation += 1
                self.screencast_draw_generation_at = self.latest_screencast_captured_at
            self.screencast_draw_occupied = occupied
        return True

    def fresh_screencast_selection_receipt(
        self, sequence_before: int | None, first_click_at: float,
    ) -> bytes | None:
        """Return a post-click calibrated stream frame for tile confirmation.

        The action gate frame is evidence only for the first click.  A second
        click may use a frame only when its receipt sequence *and* local
        arrival time prove that it followed that first click.  This avoids the
        several-second synchronous screenshot path observed on a compact
        open-hand selection.
        """
        frame = getattr(self, "latest_screencast_frame", None)
        captured_at = getattr(self, "latest_screencast_captured_at", None)
        sequence = getattr(self, "screencast_sequence", None)
        # ``__new__`` unit fixtures predating the stream metadata deliberately
        # provide their receipt directly. Real operators initialise both
        # fields, so this compatibility path cannot weaken live safety.
        if sequence_before is None or captured_at is None:
            return frame
        if frame is None or sequence is None or sequence <= sequence_before \
                or captured_at < first_click_at:
            return None
        return frame

    def record_unverified_selection(self, baseline: bytes, receipt: bytes | None) -> None:
        stamp = utc_stamp()
        before_path = self.frames / f"{stamp}.selection-before.png"
        before_path.write_bytes(baseline)
        before_path.chmod(0o600)
        receipt_path = None
        if receipt is not None:
            receipt_path = self.frames / f"{stamp}.selection-receipt.png"
            receipt_path.write_bytes(receipt)
            receipt_path.chmod(0o600)
        self.log("unverified_selection_evidence", baseline=str(before_path),
                 receipt=str(receipt_path) if receipt_path else None)

    def seed_silent_screencast_gate(self, page: Page) -> bool:
        """Seed a newly silent stream once from an exact-size current screenshot."""
        if self.screencast_session is None or self.latest_screencast_frame is not None:
            return False
        sequence_before = self.screencast_sequence
        frame = page.screenshot(animations="disabled")
        # Playwright may dispatch the first screencast event while the
        # screenshot command is in flight. In that race the real streamed
        # frame wins and the seed must not create a second gate event.
        if self.latest_screencast_frame is not None or self.screencast_sequence != sequence_before:
            return False
        if not self.accept_screencast_frame(frame):
            return False
        self.log("screencast_gate_seeded", source="one_shot_screenshot")
        return True

    def refresh_silent_screencast_gate(self, page: Page) -> bool:
        """Refresh a stalled stream without racing a newly delivered frame."""
        if self.screencast_session is None:
            return False
        sequence_before = self.screencast_sequence
        prior_frame = self.latest_screencast_frame
        prior_hash = perceptual_hash(prior_frame) if prior_frame is not None else None
        first = page.screenshot(animations="disabled")
        page.wait_for_timeout(20)
        frame = page.screenshot(animations="disabled")
        if mean_pixel_delta(first, frame) > self.args.stability_pixel_delta:
            return False
        if self.screencast_sequence != sequence_before:
            streamed = self.latest_screencast_frame
            if streamed is not None and perceptual_hash(streamed) != prior_hash:
                return False
        if not self.accept_screencast_frame(frame):
            return False
        self.log("screencast_gate_refreshed", source="silent_stream_one_shot")
        return True

    def stop_screencast_gate(self) -> None:
        """Drop the subscription before navigation or viewport replacement."""
        session = self.screencast_session
        if session is None:
            return
        try:
            session.send("Page.stopScreencast")
            session.detach()
        except Exception:
            # A viewport change may already have invalidated the old CDP
            # subscription. It is still safe and necessary to replace it.
            pass
        finally:
            self.screencast_session = None
            self.latest_screencast_frame = None
            self.screencast_draw_occupied = None

    def restart_screencast_gate(self, page: Page) -> None:
        """Re-subscribe after a viewport override invalidates Chrome's stream."""
        if self.screencast_session is None:
            return
        self.stop_screencast_gate()
        self.start_screencast_gate(page)

    def recognize_resident(
        self, screenshot: Path, *, concealed_only: bool = False, draw_only: bool = False,
        concealed_tiles: list[str] | None = None, evaluate_force_auto: bool = False,
        dynamic_layout: bool = False, open_melds: int | None = None,
        public_observation: dict[str, Any] | None = None,
        force_auto_action_buttons: list[dict[str, Any]] | None = None,
        stage_force_auto_recognition: bool = False,
        force_auto_recognition_id: str | None = None,
        frame_public_state: dict[str, Any] | None = None,
        captured_at: float | None = None,
    ) -> dict[str, Any]:
        if self.recognition_server.poll() is not None:
            raise RuntimeError("resident recognition server is not running")
        if not self.recognition_server.stdin or not self.recognition_server.stdout:
            raise RuntimeError("resident recognition server pipes are unavailable")
        self.recognition_request_id += 1
        request_id = self.recognition_request_id
        if frame_public_state is None and evaluate_force_auto and getattr(self.args, "board_metadata", False):
            frame_public_state, public_observation, _ = self.frame_metadata_state(
                screenshot, public_observation, refresh_public_cache=True,
            )
        elif frame_public_state is None and evaluate_force_auto:
            frame_public_state = getattr(self, "public_state", None)
        self.recognition_server.stdin.write(json.dumps({
            "id": request_id,
            "screenshot": str(screenshot),
            # Preserve time spent in the stream gate before writing the file.
            **({"frameCapturedAtMs": (time.time() - max(0.0, time.monotonic() - captured_at)) * 1000}
               if captured_at is not None else {}),
            "concealedOnly": concealed_only,
            "drawOnly": draw_only,
            "concealedTiles": concealed_tiles,
            "evaluateForceAuto": evaluate_force_auto,
            "stageForceAutoRecognition": stage_force_auto_recognition,
            "forceAutoRecognitionId": force_auto_recognition_id,
            "dynamicLayout": dynamic_layout,
            "openMelds": open_melds,
            "publicObservation": public_observation,
            **({"publicState": frame_public_state} if frame_public_state is not None else {}),
            "forceAutoActionButtons": force_auto_action_buttons,
            "actionDeadlineRemainingMs": self.action_deadline_remaining_ms(),
        }) + "\n")
        self.recognition_server.stdin.flush()
        response_line = self.recognition_server.stdout.readline()
        if not response_line:
            raise RuntimeError("resident recognition server closed its output")
        response = json.loads(response_line)
        if response.get("id") != request_id:
            raise RuntimeError(f"resident recognition response id mismatch: {response}")
        if response.get("error"):
            raise RuntimeError(f"resident recognition failed: {response['error']}")
        return response["result"]

    def recognize_force_auto_or_defer(self, screenshot: Path, **kwargs) -> dict[str, Any] | None:
        """Reobserve transient metadata failures without retrying hand geometry.

        RetryableSafetyAbort is a RuntimeError subclass. Letting it reach the
        dynamic-layout recovery path repeats OCR and hand recognition on the
        same aging frame even when the hand geometry was never at fault.
        """
        captured_at = kwargs.get("captured_at")
        if not kwargs.get("staged_recognition") and not self.force_auto_has_recognition_window(captured_at):
            # In ranked play, doing OCR/recognition/evaluation here can only
            # reach execute() after its 2600ms freshness budget.  Do not turn
            # a harmless old receipt into a pre-click expiry (and eventually
            # a three-expiry safety stop); wait for a newer streamed receipt.
            self.last_processed_hand = None
            self.armed = True
            self.log(
                "recognition_deferred_insufficient_click_window",
                screenshot=str(screenshot),
                captureAgeMs=self.force_auto_capture_age_ms(captured_at),
                clickBudgetMs=self.force_auto_click_budget_ms(),
                requiredRecognitionWindowMs=FORCE_AUTO_MIN_RECOGNITION_WINDOW_MS,
            )
            return None
        if getattr(self.args, "board_metadata", False) \
                and self.force_auto_click_budget_ms() is not None \
                and self.force_auto_click_budget_ms() <= FORCE_AUTO_SHORT_CLICK_BUDGET_MAX_MS \
                and self.cached_board_metadata(screenshot) is None:
            # Never run synchronous scoreboard OCR on a short ranked turn.
            # Queue it independently, then recognize a fresh frame only once
            # the matching HUD cache is available.
            self.schedule_board_metadata(screenshot.read_bytes())
            self.last_processed_hand = None
            self.armed = True
            self.log(
                "recognition_deferred_board_metadata_refresh",
                screenshot=str(screenshot),
                captureAgeMs=self.force_auto_capture_age_ms(captured_at),
                clickBudgetMs=self.force_auto_click_budget_ms(),
            )
            return None
        try:
            if getattr(self.args, "board_metadata", False):
                return self.recognize_force_auto_parallel(screenshot, **kwargs)
            kwargs.pop("staged_recognition", None)
            return self.recognize_resident(screenshot, evaluate_force_auto=True, **kwargs)
        except RetryableSafetyAbort as error:
            self.last_processed_hand = None
            self.armed = True
            self.log("recognition_deferred", screenshot=str(screenshot), error=str(error),
                     reason="retryable_safety_abort")
            return None

    def recognize_force_auto_parallel(
        self, screenshot: Path, *, dynamic_layout: bool, open_melds: int | None,
        public_observation: dict[str, Any] | None,
        force_auto_action_buttons: list[dict[str, Any]] | None,
        captured_at: float | None = None,
        staged_recognition: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Overlap hand recognition and board OCR for one immutable screenshot.

        The resident evaluator binds its staged hand result to SHA-256 of the
        screenshot.  The second request will fail closed if either side was
        produced from another frame or with another compact-row layout.
        """
        started_at = time.monotonic()
        staged: dict[str, Any] = dict(staged_recognition or {})
        failure: list[BaseException] = []
        hand_staged_at: float | None = started_at if staged_recognition is not None else None

        def stage_hand() -> None:
            nonlocal hand_staged_at
            try:
                staged.update(self.recognize_resident(
                    screenshot, dynamic_layout=dynamic_layout, open_melds=open_melds,
                    stage_force_auto_recognition=True,
                ))
                hand_staged_at = time.monotonic()
            except BaseException as error:
                failure.append(error)

        worker = None
        if staged_recognition is None:
            worker = threading.Thread(target=stage_hand, daemon=True)
            worker.start()
        try:
            frame_public_state, public_observation, _ = self.frame_metadata_state(
                screenshot, public_observation, refresh_public_cache=True,
            )
            board_metadata_ready_at = time.monotonic()
        finally:
            if worker:
                worker.join()
        if failure:
            raise failure[0]
        recognition_id = staged.get("recognitionId")
        if not isinstance(recognition_id, str):
            raise RuntimeError("resident recognition staging returned no recognition id")
        result = self.recognize_resident(
            screenshot, evaluate_force_auto=True, dynamic_layout=dynamic_layout,
            open_melds=open_melds, public_observation=public_observation,
            force_auto_action_buttons=force_auto_action_buttons,
            force_auto_recognition_id=recognition_id, frame_public_state=frame_public_state,
            captured_at=captured_at,
        )
        completed_at = time.monotonic()
        # Keep profiling attached to the evaluation rather than the wall-clock
        # action timing.  The latter intentionally ends at the physical click;
        # adding post-click confirmation to it previously obscured where a
        # short ranked budget was actually consumed.
        result["operatorTiming"] = {
            "parallelHandRecognitionMs": round(((hand_staged_at or completed_at) - started_at) * 1000),
            "parallelBoardMetadataMs": round((board_metadata_ready_at - started_at) * 1000),
            "forceAutoDecisionAfterParallelMs": round((completed_at - board_metadata_ready_at) * 1000),
            "forceAutoRecognitionAndDecisionMs": round((completed_at - started_at) * 1000),
        }
        return result

    def defer_missing_public_context(self, evaluation: dict[str, Any], frame: bytes) -> bool:
        if self.args.mode != "force-auto" or not getattr(self.args, "public_cache", False):
            return False
        action = evaluation.get("decision", {}).get("selectedAction", {}).get("action")
        cache = evaluation.get("publicCache", {})
        if evaluation.get("status") != "decision" or action not in {"discard", "riichi"} or cache.get("applied"):
            return False
        self.schedule_public_recognition(frame, force=True)
        self.log("public_context_deferred", reason=cache.get("ignoredReason", "not_available"),
                 ageMs=cache.get("ageMs"))
        return True

    def schedule_board_metadata(self, frame: bytes) -> None:
        if not getattr(self.args, "board_metadata", False):
            return
        self.poll_board_metadata()
        if self.board_metadata_thread and self.board_metadata_thread.is_alive():
            return
        now = time.monotonic()
        # Let the foreground validate the newest score/counter pixels before
        # a second full OCR takes the shared lock again. Otherwise changing
        # turn highlights can starve partial verification for an entire turn.
        cache = getattr(self, "board_metadata_cache", None)
        if (getattr(self, "board_metadata_partial_retry_pending", False)
                and cache and now - cache["capturedAt"] <= 8.0):
            return
        self.board_metadata_partial_retry_pending = False
        signature = board_state_signature(frame)
        wall_signature = wall_counter_signature(frame)
        previous_signature = getattr(self, "board_metadata_last_scan_signature", None)
        if now - self.board_metadata_last_scan_at < 6.0 and previous_signature is not None \
                and board_state_signature_matches(signature, previous_signature):
            return
        self.board_metadata_last_scan_at = now
        self.board_metadata_last_scan_signature = signature
        path = self.frames / f"{utc_stamp()}.board-cache.jpg"
        path.write_bytes(frame)

        def recognize() -> None:
            from board_metadata import recognize_board
            try:
                with self.board_metadata_ocr_lock:
                    result = recognize_board(path)
            except Exception as error:
                with self.board_metadata_lock:
                    self.board_metadata_result = {"error": str(error), "screenshot": str(path)}
                return
            with self.board_metadata_lock:
                self.board_metadata_result = {
                    "metadata": result, "signature": signature,
                    "wallSignature": wall_signature,
                    "capturedAt": now, "screenshot": str(path),
                }

        self.board_metadata_thread = threading.Thread(target=recognize, daemon=True)
        self.board_metadata_thread.start()

    def poll_board_metadata(self) -> None:
        with self.board_metadata_lock:
            result = self.board_metadata_result
            self.board_metadata_result = None
        if result and result.get("error"):
            self.log("board_metadata_cache_failed", screenshot=result["screenshot"], error=result["error"])
            # A transitional startup frame may not yet contain readable HUD
            # text.  Do not suppress a subsequent valid scan for six seconds.
            self.board_metadata_last_scan_at = 0.0
            self.board_metadata_last_scan_signature = None
        elif result and result["metadata"].get("verified"):
            current = getattr(self, "board_metadata_cache", None)
            if current and result["capturedAt"] < current["capturedAt"]:
                self.log("board_metadata_cache_older_result_ignored", screenshot=result["screenshot"])
                return
            self.board_metadata_cache = result
            self.log("board_metadata_cache_updated", screenshot=result["screenshot"],
                     round=result["metadata"].get("round"),
                     scores=result["metadata"].get("scores"))
        elif result:
            self.board_metadata_last_scan_at = 0.0
            self.board_metadata_last_scan_signature = None
            self.log("board_metadata_cache_unverified", screenshot=result["screenshot"])

    def current_board_metadata(self, screenshot: Path) -> dict[str, Any]:
        from board_metadata import recognize_board
        if not hasattr(self, "board_metadata_lock"):
            # Isolated frame-state probes construct the operator without its
            # background worker; keep their direct OCR path intact.
            return recognize_board(screenshot)
        cached = self.cached_board_metadata(screenshot)
        if cached is not None:
            return cached
        if self.board_metadata_thread and self.board_metadata_thread.is_alive():
            self.board_metadata_thread.join(timeout=0.3)
            cached = self.cached_board_metadata(screenshot)
            if cached is not None:
                return cached
            if self.board_metadata_thread.is_alive():
                raise RetryableSafetyAbort("board metadata refresh in progress")
        with self.board_metadata_ocr_lock:
            return recognize_board(screenshot)

    def cached_board_metadata(self, screenshot: Path) -> dict[str, Any] | None:
        """Return only a matching, recent HUD cache; never start OCR here."""
        if not hasattr(self, "board_metadata_lock"):
            return None
        self.poll_board_metadata()
        cache = self.board_metadata_cache
        if not cache:
            return self.board_metadata_cache_miss("missing_cache")
        age_ms = round((time.monotonic() - cache["capturedAt"]) * 1000)
        if age_ms > 8000:
            return self.board_metadata_cache_miss("expired_cache")
        frame = screenshot.read_bytes()
        memo = getattr(self, "board_metadata_frame_memo", None)
        if memo is not None and memo[0] is cache and memo[1] == frame:
            self.board_metadata_partial_retry_pending = False
            self.board_metadata_cache_miss_reason = None
            self.log("board_metadata_frame_memo_applied", screenshot=str(screenshot),
                     source=cache["screenshot"], ageMs=age_ms)
            return copy.deepcopy(memo[2])
        signature = board_state_signature(frame)
        previous = cache["signature"]
        if len(signature) != len(BOARD_STATE_REGIONS) or len(previous) != len(BOARD_STATE_REGIONS):
            return self.board_metadata_cache_miss("invalid_signature")
        changed = [index for index, (a, b) in enumerate(zip(signature, previous))
                   if sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3 > 3.0]
        # Turn highlights can change any of the four score panels.  The round
        # and sticks must still match; every changed score is independently
        # OCR-verified against the cache rather than ignored.
        if any(index not in {1, 2, 3, 4, 5} for index in changed):
            return self.board_metadata_cache_miss("round_changed")
        refresh_round_counters = 5 in changed
        score_changed = [index for index in changed if index in {1, 2, 3, 4}]
        refresh_wall = "remainingTiles" in cache["metadata"] and (
            cache.get("wallSignature") is None
            or wall_counter_signature(frame) != cache["wallSignature"]
        )
        if score_changed or refresh_wall or refresh_round_counters:
            from board_metadata import recognize_remaining_count, recognize_right_score, recognize_score, recognize_round_counters
            lock = getattr(self, "board_metadata_ocr_lock", None)
            if lock is None or not lock.acquire(blocking=False):
                return self.board_metadata_cache_miss("partial_ocr_lock_busy", retry_partial=True)
            self.board_metadata_partial_retry_pending = False
            try:
                try:
                    if refresh_round_counters:
                        counters = recognize_round_counters(screenshot)
                        if counters is None or counters != (cache["metadata"].get("riichiSticks"),
                                                           cache["metadata"].get("honba")):
                            return self.board_metadata_cache_miss("counters_unreadable_or_changed")
                    if score_changed:
                        seat_order = ("east", "south", "west", "north")
                        seat = cache["metadata"].get("seat")
                        if seat not in seat_order:
                            return self.board_metadata_cache_miss("unknown_seat")
                        positions = {1: (0, "own"), 2: (1, "right"),
                                     3: (2, "opposite"), 4: (3, "left")}
                        # The new multi-panel path rechecks every score, not
                        # just panels crossing the image-delta threshold: a
                        # small digit change in another panel must not be
                        # hidden by its low average pixel difference.
                        score_indices = [1, 2, 3, 4] if any(index != 2 for index in score_changed) else score_changed
                        for index in score_indices:
                            offset, position = positions[index]
                            score_seat = seat_order[(seat_order.index(seat) + offset) % 4]
                            score = recognize_right_score(screenshot) if position == "right" \
                                else recognize_score(screenshot, position)
                            if score is None or score != cache["metadata"].get("scores", {}).get(score_seat):
                                return self.board_metadata_cache_miss("score_unreadable_or_changed")
                    remaining = recognize_remaining_count(screenshot) if refresh_wall else None
                except Exception as error:
                    self.log("board_metadata_counter_refresh_failed", screenshot=str(screenshot),
                             error=str(error))
                    return self.board_metadata_cache_miss("partial_ocr_failed")
            finally:
                lock.release()
            if refresh_wall and remaining is None:
                return self.board_metadata_cache_miss("remaining_tiles_unreadable")
            metadata = copy.deepcopy(cache["metadata"])
            if refresh_wall:
                metadata["remainingTiles"] = remaining
            self.log("board_metadata_partial_refreshed" if score_changed or refresh_round_counters else "board_metadata_counter_refreshed", screenshot=str(screenshot),
                     source=cache["screenshot"], ageMs=age_ms,
                     remainingTiles=remaining, rightScoreVerified=bool(score_changed),
                     scorePanelsVerified=score_indices if score_changed else [],
                     roundCountersVerified=refresh_round_counters)
            self.board_metadata_frame_memo = (cache, frame, copy.deepcopy(metadata))
            self.board_metadata_cache_miss_reason = None
            return metadata
        self.log("board_metadata_cache_applied", screenshot=str(screenshot),
                 source=cache["screenshot"], ageMs=age_ms)
        self.board_metadata_partial_retry_pending = False
        self.board_metadata_cache_miss_reason = None
        return cache["metadata"]

    def board_metadata_cache_miss(self, reason: str, *, retry_partial: bool = False) -> None:
        """Report a changed miss reason once, without flooding the live log."""
        self.board_metadata_partial_retry_pending = retry_partial
        if getattr(self, "board_metadata_cache_miss_reason", None) != reason:
            self.log("board_metadata_cache_miss", reason=reason, partialRetryPending=retry_partial)
            self.board_metadata_cache_miss_reason = reason
        return None

    def reset_post_riichi_safety(self) -> None:
        self.post_riichi_safety_generation = getattr(self, "post_riichi_safety_generation", 0) + 1
        self.post_riichi_safety_key = None
        self.post_riichi_pass_candidates = []
        self.post_riichi_safe_tiles = {}

    @staticmethod
    def post_riichi_round_key(state):
        if not isinstance(state, dict) or not isinstance(state.get("round"), str) \
                or not re.fullmatch(r"(?:east|south|west|north)_[1-4]", state["round"]):
            return None
        if state.get("seat") not in {"east", "south", "west", "north"}:
            return None
        honba = state.get("honba")
        if not isinstance(honba, int) or isinstance(honba, bool) or honba < 0:
            return None
        return state["round"], honba, state["seat"]

    def own_discard_riichi_context(self, evaluation):
        state = evaluation.get("state", {})
        metadata = getattr(self, "riichi_metadata_history", None)
        key = self.post_riichi_round_key(state)
        if not key or not metadata or not metadata.get("verified") \
                or key != self.post_riichi_round_key(metadata) \
                or key != getattr(self, "post_riichi_safety_key", None):
            return None
        seats = sorted(opponent["seat"] for opponent in state.get("opponents", [])
                       if opponent.get("riichi") and opponent.get("seat") != state["seat"]
                       and opponent.get("seat") in metadata.get("riichiSeats", []))
        return {"key": key, "scopeGeneration": self.post_riichi_safety_generation,
                "seats": seats} if seats else None

    def record_post_riichi_pass_candidate(self, pending, actual) -> None:
        context = pending.get("riichiContext")
        if not context or context.get("scopeGeneration") != getattr(self, "post_riichi_safety_generation", None) \
                or tuple(context.get("key", [])) != getattr(self, "post_riichi_safety_key", None) \
                or getattr(self, "screencast_session", None) is None:
            return
        generation = getattr(self, "screencast_draw_generation", None)
        if not isinstance(generation, int):
            return
        # River confirmation alone is not a pass: the ron window can still
        # be open. Require a later observed own draw before using this tile.
        self.post_riichi_pass_candidates.append({"tile": actual,
            "seats": list(context["seats"]), "confirmedDrawGeneration": generation,
            "sourceClickedAt": pending.get("clickedAt"), "sourceRiverIndex": len(pending["before"])})
        self.log("post_riichi_pass_candidate", tile=actual, seats=context["seats"],
                 confirmedDrawGeneration=generation, sourceClickedAt=pending.get("clickedAt"),
                 sourceRiverIndex=len(pending["before"]))

    def apply_post_riichi_safety(self, state, *, self_turn: bool) -> None:
        # Configured or old remapped markers are not live evidence.
        state["opponents"] = [{name: value for name, value in opponent.items()
                              if name != "postRiichiSafeTiles"}
                             for opponent in state.get("opponents", [])]
        key = self.post_riichi_round_key(state)
        if key != getattr(self, "post_riichi_safety_key", None):
            self.reset_post_riichi_safety()
            self.post_riichi_safety_key = key
        if not key:
            return
        generation = getattr(self, "screencast_draw_generation", None)
        new_draw = self_turn and getattr(self, "screencast_session", None) is not None \
            and getattr(self, "screencast_draw_occupied", None) is True and isinstance(generation, int)
        riichi_seats = {opponent["seat"] for opponent in state.get("opponents", []) if opponent.get("riichi")}
        remaining = []
        for candidate in getattr(self, "post_riichi_pass_candidates", []):
            if not new_draw or generation <= candidate["confirmedDrawGeneration"]:
                remaining.append(candidate)
                continue
            for seat in candidate["seats"]:
                if seat not in riichi_seats:
                    continue
                tiles = self.post_riichi_safe_tiles.setdefault(seat, set())
                tile = candidate["tile"]
                tile = "5" + tile[1:] if tile.startswith("0") else tile
                if tile not in tiles:
                    tiles.add(tile)
                    self.log("post_riichi_pass_verified", seat=seat, tile=tile,
                             round=state["round"], honba=state["honba"],
                             sourceClickedAt=candidate["sourceClickedAt"],
                             sourceRiverIndex=candidate["sourceRiverIndex"],
                             confirmedDrawGeneration=candidate["confirmedDrawGeneration"],
                             currentDrawGeneration=generation)
        self.post_riichi_pass_candidates = remaining
        # Do not mutate the shared configured state/remapped opponent objects.
        state["opponents"] = [{**opponent,
            **({"postRiichiSafeTiles": sorted(self.post_riichi_safe_tiles[opponent["seat"]])}
               if opponent.get("riichi") and opponent["seat"] in self.post_riichi_safe_tiles else {})}
            for opponent in state.get("opponents", [])]

    def frame_metadata_state(self, screenshot: Path, observation=None, pending=None, *, refresh_public_cache=False, prepared_metadata=None):
        from board_metadata import remap_seats, recognize_riichi_sticks, reconcile_riichi_metadata
        metadata = prepared_metadata if prepared_metadata is not None else self.current_board_metadata(screenshot)
        if not metadata.get("verified"):
            raise RetryableSafetyAbort(f"board metadata not verified: {metadata.get('reason')}")
        # Score-cache signatures intentionally omit animated stick rectangles.
        # Read positive stick evidence from the exact evaluated frame as well.
        with Image.open(screenshot) as image:
            fresh_riichi = recognize_riichi_sticks(image, metadata["seat"])
        visual_riichi = sorted(set(metadata.get("riichiSeats", [])) | set(fresh_riichi))
        previous_metadata = getattr(self, "riichi_metadata_history", None)
        metadata = reconcile_riichi_metadata(previous_metadata, {
            **metadata, "riichiSeats": visual_riichi,
        })
        self.riichi_metadata_history = {**metadata, "scores": dict(metadata.get("scores", {}))}
        if metadata["riichiScoreDeclarations"]:
            self.log("riichi_score_transition_verified", screenshot=str(screenshot),
                     seats=metadata["riichiScoreDeclarations"], beforeScores=previous_metadata["scores"],
                     afterScores=metadata["scores"], beforeSticks=previous_metadata["riichiSticks"],
                     afterSticks=metadata["riichiSticks"])
        if refresh_public_cache:
            # OCR can take seconds while the independent public worker finishes.
            # Promote its completed result before freezing the decision request.
            self.poll_public_recognition()
            if self.cached_public_observation is not None:
                observation = self.cached_public_observation
        fields = {key: metadata[key] for key in
                  ("seat", "round", "scores", "honba", "riichiSticks", "remainingTiles")
                  if key in metadata}
        source_seat = self.public_state.get("seat", "east")
        state = {**remap_seats(self.public_state, source_seat, fields["seat"]), **fields}
        # Unknown current wall length must not inherit a configured or prior
        # observation, including the schema's legacy snake_case alias.
        state.pop("remaining_tiles", None)
        if "remainingTiles" not in fields:
            state.pop("remainingTiles", None)
        self.log("board_metadata_verified", screenshot=str(screenshot), **fields)
        mapped_observation = remap_seats(observation, source_seat, fields["seat"])
        riichi_seats = metadata.get("riichiSeats", [])
        if mapped_observation is not None:
            # River orientation alone can misclassify an early, incomplete
            # crop as a sideways declaration and keep that flag even after
            # its river prefix is repaired. On the verified HUD path, only
            # positive sticks or conserved payments establish declarations.
            # Work on the remapped copy: retain the raw cache for diagnostics.
            ignored = []
            own_riichi = bool(state.get("riichiDeclared") or fields["seat"] in riichi_seats)
            if mapped_observation.get("ownRiichiDeclared") and not own_riichi:
                ignored.append(fields["seat"])
            mapped_observation["ownRiichiDeclared"] = own_riichi
            for observed in mapped_observation.get("opponentDiscards", []):
                declared = observed.get("seat") in riichi_seats
                if observed.get("riichiDeclared") and not declared:
                    ignored.append(observed.get("seat"))
                observed["riichiDeclared"] = declared
            if ignored:
                self.log("unverified_river_riichi_ignored", screenshot=str(screenshot),
                         seats=ignored, verifiedRiichiSeats=riichi_seats)
        for seat in riichi_seats:
            if seat == fields["seat"]:
                state["riichiDeclared"] = True
                if mapped_observation is not None:
                    mapped_observation["ownRiichiDeclared"] = True
            else:
                opponents = state.setdefault("opponents", [])
                opponent = next((item for item in opponents if item["seat"] == seat), None)
                if opponent is None:
                    opponent = {"seat": seat, "discards": []}
                    opponents.append(opponent)
                opponent["riichi"] = True
                if mapped_observation is not None:
                    observed = next((item for item in mapped_observation.get("opponentDiscards", [])
                                     if item["seat"] == seat), None)
                    if observed is not None:
                        observed["riichiDeclared"] = True
        if visual_riichi:
            self.log("riichi_stick_verified", screenshot=str(screenshot), seats=visual_riichi)
        self.apply_post_riichi_safety(state, self_turn=pending is None)
        return (state, mapped_observation,
                remap_seats(pending, source_seat, fields["seat"]))

    def ensure_viewport(self, page: Page, *, force: bool = False) -> None:
        """Keep CDP clients from leaving the game canvas at a stale viewport."""
        expected = self.layout["viewport"]
        actual = page.evaluate("() => ({ width: window.innerWidth, height: window.innerHeight })")
        if actual == expected and not force:
            return
        page.set_viewport_size({"width": expected["width"], "height": expected["height"]})
        # CDP attachment can asynchronously apply its inferred viewport just
        # after connect. Let that initialization settle before verification.
        page.wait_for_timeout(250)
        confirmed = page.evaluate("() => ({ width: window.innerWidth, height: window.innerHeight })")
        if confirmed != expected:
            raise RuntimeError(f"viewport restore failed: expected={expected}, actual={confirmed}")
        if actual != confirmed:
            self.log("viewport_restored", previous=actual, viewport=confirmed)
            # Page.set_viewport_size can leave the existing CDP screencast
            # subscription silent. A fresh subscription is required for the
            # reaction/turn gate to resume after the restore.
            if getattr(self, "screencast_session", None) is not None:
                self.restart_screencast_gate(page)

    def resume_startup_away(self, page: Page, screenshot: bytes | None) -> bool:
        """Recover a verified away dialog without authorizing a gameplay turn.

        The stream is only a cue: resume_if_away captures and checks the current
        screen independently, so a stale dialog cannot cause a later click.
        """
        if not getattr(self.args, "resume_away", False) or not screenshot:
            return False
        if not is_away_resume_dialog(screenshot, self.layout["viewport"]):
            return False
        return self.resume_if_away(page)

    def resume_if_away(self, page: Page, screenshot: bytes | None = None) -> bool:
        if not self.args.resume_away:
            return False
        screenshot = screenshot or page.screenshot(animations="disabled")
        viewport = self.layout["viewport"]
        if not is_away_resume_dialog(screenshot, viewport):
            return False
        button, _ = away_resume_geometry(viewport)
        point = {"x": button["x"] + button["width"] / 2, "y": button["y"] + button["height"] / 2}
        page.mouse.click(point["x"], point["y"])
        for _ in range(20):
            page.wait_for_timeout(100)
            if not is_away_resume_dialog(page.screenshot(animations="disabled"), viewport):
                break
        else:
            raise RuntimeError("away dialog resume click was not confirmed")
        self.log("away_resumed", clickPoint=point)
        self.last_processed_hand = None
        self.armed = True
        return True

    def log(self, event: str, **payload: Any) -> None:
        record = {"timestamp": datetime.now(timezone.utc).isoformat(), "event": event, **payload}
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        print(json.dumps(record, ensure_ascii=False), flush=True)
        # Analysis must never interrupt gameplay or replace the raw evidence log.
        try:
            if not hasattr(self, "analysis_recorder"):
                self.analysis_recorder = AnalysisRecorder(self.log_path.parent / "analysis", str(self.log_path.parent))
            self.analysis_recorder.observe(record)
        except Exception as exc:
            print(f"analysis_export_failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)


    @staticmethod
    def ranked_loop_click_point(state: str, viewport: dict[str, int]) -> dict[str, float] | None:
        """Return the fixed navigation target for a Bronze Room East loop."""
        ratios = {
            "lobby": (0.724, 0.300),       # ranked match
            "ranked_menu": (0.724, 0.380), # Bronze Room
            "ranked_room": (0.724, 0.375), # four-player East
        }
        ratio = ratios.get(state)
        if ratio is None:
            return None
        return {"x": viewport["width"] * ratio[0], "y": viewport["height"] * ratio[1]}

    @staticmethod
    def verified_visible_open_meld_count(
        inferred_open_melds: int, public_observation: dict[str, Any] | None,
    ) -> int | None:
        """Accept restart recovery only from complete, internally consistent meld evidence."""
        if inferred_open_melds <= 0 or not public_observation:
            return None
        melds = public_observation.get("ownMelds")
        visible_tiles = public_observation.get("ownMeldTiles")
        if not isinstance(melds, list) or len(melds) != inferred_open_melds \
                or not isinstance(visible_tiles, list):
            return None
        promoted_tiles: list[str] = []
        for meld in melds:
            if not isinstance(meld, dict) or meld.get("type") not in {"chi", "pon", "minkan"}:
                return None
            tiles = meld.get("tiles")
            expected_tiles = 4 if meld.get("type") == "minkan" else 3
            if not isinstance(tiles, list) or len(tiles) != expected_tiles:
                return None
            confidence = meld.get("confidence")
            if not isinstance(confidence, (int, float)) or confidence <= 0:
                return None
            promoted_tiles.extend(tiles)
        # Extra or missing safe tiles mean the public recognizer did not
        # explain the complete visible meld region, so retain fail-closed.
        if promoted_tiles != visible_tiles:
            return None
        return inferred_open_melds

    @classmethod
    def verified_visible_open_melds(
        cls, public_observation: dict[str, Any] | None,
    ) -> int | None:
        """Return the visible meld count only when every meld is fully explained."""
        melds = public_observation.get("ownMelds") if public_observation else None
        if not isinstance(melds, list) or not melds:
            return None
        return cls.verified_visible_open_meld_count(len(melds), public_observation)

    @classmethod
    def restart_open_discard_meld_count(
        cls, concealed_tile_count: int, public_observation: dict[str, Any] | None,
    ) -> int | None:
        """Distinguish a post-call discard state from the ordinary opponent turn."""
        open_melds = cls.verified_visible_open_melds(public_observation)
        if open_melds is None:
            return None
        expected_discard_count = 14 - open_melds * 3
        return open_melds if concealed_tile_count == expected_discard_count else None

    @classmethod
    def compact_hand_is_proven(
        cls, open_melds: int, dynamic_layout_was_required: bool,
        public_observation: dict[str, Any] | None = None,
    ) -> bool:
        return open_melds == 0 or dynamic_layout_was_required \
            or cls.verified_visible_open_meld_count(open_melds, public_observation) is not None

    def stable_open_meld_count(self, candidate: int | None, frame: bytes) -> int | None:
        """Reject count jumps and require two distinct frames before adoption."""
        if candidate is None:
            return None
        if self.cached_open_melds > 0:
            return candidate if candidate == self.cached_open_melds else None
        if candidate != self.open_meld_candidate:
            self.open_meld_candidate = candidate
            self.open_meld_candidate_frames = set()
        self.open_meld_candidate_frames.add(hashlib.sha256(frame).hexdigest())
        return candidate if len(self.open_meld_candidate_frames) >= 2 else None

    def stable_closed_new_round(self, frame: bytes) -> bool:
        """Confirm a closed new hand twice before clearing prior meld state."""
        if not closed_concealed_row_visible(frame, self.layout) \
                or geometric_open_meld_count(frame, self.layout) is not None:
            self.closed_new_round_candidate_frames = set()
            return False
        if not hasattr(self, "closed_new_round_candidate_frames"):
            self.closed_new_round_candidate_frames = set()
        self.closed_new_round_candidate_frames.add(hashlib.sha256(frame).hexdigest())
        return len(self.closed_new_round_candidate_frames) >= 2

    def should_reset_open_hand_state(self, frame: bytes) -> bool:
        """Never treat a pre-call/choice animation as closed-new-round proof."""
        if getattr(self, "pending_post_call_discard", False):
            self.closed_new_round_candidate_frames = set()
            return False
        return self.cached_open_melds > 0 and self.stable_closed_new_round(frame)

    @staticmethod
    def round_advanced_after_recovery(previous: dict[str, Any] | None,
                                      current: dict[str, Any]) -> bool:
        """A visible hand alone cannot distinguish a new round from a lost win."""
        if not isinstance(previous, dict) or current.get("verified") is not True \
                or not isinstance(current.get("remainingTiles"), int) \
                or isinstance(current.get("remainingTiles"), bool) \
                or not 0 < current["remainingTiles"] <= 70:
            return False
        winds = ["east", "south", "west", "north"]
        keys = []
        for state in (previous, current):
            match = re.fullmatch(r"(east|south|west|north)_([1-4])", str(state.get("round", "")))
            honba = state.get("honba")
            if not match or state.get("seat") not in winds \
                    or not isinstance(honba, int) or isinstance(honba, bool) or honba < 0:
                return False
            keys.append((winds.index(match[1]) * 4 + int(match[2]), honba))
        rounds = keys[1][0] - keys[0][0]
        if rounds < 0 or (rounds == 0 and keys[1][1] <= keys[0][1]):
            return False
        return winds.index(current["seat"]) == (winds.index(previous["seat"]) - rounds) % 4

    def start_self_win_capture(self, action: str) -> None:
        """Arm a bounded, click-free capture after our confirmed ron/tsumo."""
        self.self_win_capture = {
            "id": utc_stamp(), "action": action, "started": time.monotonic(),
            "frames": [], "sawOverlay": False,
        }
        self.log("self_win_capture_started", winId=self.self_win_capture["id"],
                 action=action, maxDurationMs=15000, intervalMs=500)

    def capture_self_win_result(self, page: Page) -> bool:
        """Sample the whole yaku animation before result-confirmation can click.

        Canvas animations are not frozen by Playwright animations='disabled'.
        Keep a sequence rather than calling the first result frame a settled
        yaku screen. This is image evidence, not OCR or a verified yaku label.
        """
        capture = getattr(self, "self_win_capture", None)
        if capture is None:
            return False
        elapsed = time.monotonic() - capture["started"]
        reason = None
        if elapsed >= 15 or len(capture["frames"]) >= 30:
            reason = "capture_window_complete"
        else:
            try:
                frame = page.screenshot(animations="disabled")
                state, _ = classify_screen(frame, getattr(self, "screen_references", {}))
                # Do not delay a later live hand if the client auto-advanced.
                live = (capture["sawOverlay"] and state == "match"
                        and closed_concealed_row_visible(frame, self.layout)
                        and round_result_conflicts_with_live_table(frame, self.layout))
                if live:
                    reason = "live_table_returned"
                else:
                    snapshot = self.frames / f"{utc_stamp()}.self-win-{capture['action']}.png"
                    snapshot.write_bytes(frame)
                    snapshot.chmod(0o600)
                    evidence = {"observedAt": datetime.now(timezone.utc).isoformat(),
                                "screenshot": str(snapshot), "screenState": state,
                                "elapsedMs": round(elapsed * 1000),
                                "awayDialogObserved": bool(self.layout.get("viewport")) and
                                    is_away_resume_dialog(frame, self.layout["viewport"])}
                    capture["frames"].append(evidence)
                    self.log("self_win_frame", winId=capture["id"],
                             action=capture["action"], evidence=evidence)
                    capture["sawOverlay"] |= state in {"round_result", "match_result", "unknown"}
                    if state == "match_result":
                        reason = "match_result_reached"
            except Exception as error:
                # A recording error must never repeat an already-sent win.
                reason = "capture_error"
                self.log("self_win_capture_error", winId=capture["id"], error=str(error))
        if reason:
            self.log("self_win_capture_finished", winId=capture["id"],
                     action=capture["action"], frameCount=len(capture["frames"]), reason=reason)
            # A self-win animation can be captured as round_result without the
            # normal result-handling path ever seeing the summary. If the
            # client auto-advances, use the same independent new-hand/round
            # verification as black-screen recovery; never turn the animation
            # itself into an attached score result.
            if (getattr(self, "round_terminal_latched", False)
                    and not getattr(self, "round_terminal_result_observed", False)
                    and getattr(self, "round_terminal_recovery", None) is None
                    and any(item.get("screenState") == "round_result"
                            or item.get("awayDialogObserved") is True for item in capture["frames"])):
                previous = self.round_terminal_previous_state()
                self.round_terminal_recovery = {"previous": previous, "since": None,
                                                "source": "self_win_capture"}
                self.closed_new_round_candidate_frames = set()
                self.log("round_terminal_recovery_armed", source="self_win_capture",
                         previous=previous, gameplayClicks=0)
            self.self_win_capture = None
            return False
        page.wait_for_timeout(500)
        return True

    def round_terminal_previous_state(self) -> dict[str, Any] | None:
        pending = getattr(self, "pending_round_replays", [])
        if pending:
            try:
                previous = load_json(pending[-1]).get("state")
                if previous is not None:
                    return previous
            except (OSError, ValueError):
                pass
        return (getattr(self, "board_metadata_cache", None) or {}).get("metadata")

    def clear_round_terminal_latch(self, source: str) -> None:
        self.round_terminal_latched = False
        self.round_terminal_result_observed = False
        self.round_terminal_unknown_since = None
        self.round_terminal_recovery = None
        self.closed_new_round_candidate_frames = set()
        self.ranked_terminal_transition_pending = False
        self.last_observed_outcome_kind = None
        self.log("round_terminal_latch_cleared", source=source)

    def wait_for_round_terminal(self, page: Page, frame: bytes, state: str) -> bool:
        """Keep win overlays noninteractive; recover only a verified later hand."""
        if not getattr(self, "round_terminal_latched", False):
            return False
        # Result animations normally own this latch, but a long terminal wait
        # can also reveal the independently verified away/resume dialog.  Do
        # not let the latch hide that dialog behind an ``unknown`` screen
        # state: its geometry is stricter than screen classification and the
        # existing resume flow re-observes before any gameplay decision.
        if self.resume_if_away(page, frame):
            self.round_terminal_unknown_since = None
            self.log("round_terminal_away_resumed", gameplayClicks=0)
            return True
        if getattr(self, "round_terminal_result_observed", False) and state == "match" \
                and closed_concealed_row_visible(frame, self.layout):
            self.clear_round_terminal_latch("verified_new_round_closed_row")
            return False
        recovery = getattr(self, "round_terminal_recovery", None)
        if recovery is not None:
            # This dialog shares most pixels with a live table and can be
            # classified as match. Its independently checked geometry remains
            # authoritative even while the missing-result latch is armed.
            if self.resume_if_away(page, frame):
                return True
            now = time.monotonic()
            if recovery.get("since") is None:
                recovery["since"] = now
            if now - recovery["since"] >= 30:
                snapshot = self.frames / f"{utc_stamp()}.round-terminal-recovery-stop.png"
                snapshot.write_bytes(frame)
                snapshot.chmod(0o600)
                self.log("round_terminal_recovery_stop", screenshot=str(snapshot),
                         previous=recovery["previous"], gameplayClicks=0,
                         reason="new_round_not_verified_within_30s")
                raise RuntimeError("round terminal recovery could not verify a new hand")
            if state == "match" and self.stable_closed_new_round(frame):
                snapshot = recovery.get("screenshot")
                if snapshot is None:
                    snapshot = self.frames / f"{utc_stamp()}.round-terminal-recovery.png"
                    recovery["screenshot"] = snapshot
                snapshot.write_bytes(frame)
                snapshot.chmod(0o600)
                try:
                    metadata = self.current_board_metadata(snapshot)
                except RetryableSafetyAbort:
                    metadata = {"verified": False, "reason": "metadata_refresh_in_progress"}
                if self.round_advanced_after_recovery(recovery["previous"], metadata):
                    # Do not attach this later hand's result to decisions from
                    # the hand whose summary was lost during reload. Retain
                    # their match scope so the eventual native final still
                    # reaches every replay without restarting the operator.
                    pending = list(getattr(self, "pending_round_replays", []))
                    ledger = snapshot.with_suffix(".round-terminal-unobserved-result.json")
                    ledger.write_text(json.dumps({
                        "reason": ("round_result_not_observed_after_self_win_capture"
                                   if recovery.get("source") == "self_win_capture"
                                   else "round_result_lost_during_black_recovery"),
                        "previous": recovery["previous"], "current": metadata,
                        "screenshot": str(snapshot),
                        "pendingRoundReplays": [str(p) for p in pending],
                        "matchScopeRetained": True,
                    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    ledger.chmod(0o600)
                    self.pending_round_replays = []
                    if recovery.get("source") == "self_win_capture":
                        # Unlike the reload path, this path has not yet
                        # invalidated any data belonging to the old round.
                        self.cached_concealed_tiles = None
                        self.cached_open_melds = 0
                        self.dynamic_layout_required = False
                        self.pending_post_call_discard = False
                        self.pending_post_call_started_at = None
                        self.cached_public_observation = None
                        self.previous_public_observation = None
                        self.pending_own_discard = None
                        self.pending_own_river_confirmation = None
                        self.selection_uncertainty_latch = None
                        self.public_cache_generation = getattr(self, "public_cache_generation", 0) + 1
                        self.public_cache_last_frame_hash = None
                        self.last_public_scan_at = 0.0
                        self.board_metadata_cache = None
                        self.board_metadata_last_scan_at = 0.0
                        self.riichi_metadata_history = None
                        self.reset_post_riichi_safety()
                        self.last_processed_hand = None
                        self.last_shanten = None
                        self.armed = True
                    self.log("round_terminal_recovered_without_result", screenshot=str(snapshot),
                             ledger=str(ledger), retiredRoundReplays=len(pending),
                             previous=recovery["previous"], current=metadata, gameplayClicks=0)
                    self.clear_round_terminal_latch(
                        "verified_new_round_after_self_win_capture"
                        if recovery.get("source") == "self_win_capture"
                        else "verified_new_round_after_black_reload")
                    return False
        # A result latch must never turn an unclassified modal into an
        # infinite polling loop.  Give ordinary result fades time to settle,
        # then retain a screenshot and stop with no gameplay click.
        if state == "unknown":
            now = time.monotonic()
            since = getattr(self, "round_terminal_unknown_since", None)
            if since is None:
                self.round_terminal_unknown_since = now
            elif now - since >= 30:
                snapshot = self.frames / f"{utc_stamp()}.round-terminal-unknown-stop.png"
                snapshot.write_bytes(frame)
                snapshot.chmod(0o600)
                self.log("round_terminal_unknown_screen_stop", screenshot=str(snapshot),
                         waitSeconds=round(now - since, 3), gameplayClicks=0)
                raise RuntimeError("round terminal remained on an unknown screen for 30 seconds")
        else:
            self.round_terminal_unknown_since = None
        self.log("round_terminal_wait", screenState=state,
                 resultObserved=getattr(self, "round_terminal_result_observed", False))
        return True

    def observe_ranked_match_screen(self, state: str) -> None:
        # Result animations can briefly expose the old table. A completed
        # match stays completed until an authorized new room selection.
        if state == "match" and not getattr(self, "ranked_match_finished", False):
            self.ranked_match_in_progress = True

    def observe_ranked_outcome(self, kind: str) -> None:
        if kind in {"round", "match"}:
            self.reset_post_riichi_safety()
        if kind == "match":
            self.ranked_match_in_progress = False
            self.ranked_match_finished = True
        elif not getattr(self, "ranked_match_finished", False):
            self.ranked_match_in_progress = True

    def advance_ranked_loop(
        self, page: Page, state: str, confidence: float, *, screenshot: bytes | None = None,
    ) -> bool:
        """Enter or re-enter Bronze Room four-player East after every match."""
        if not self.args.ranked_loop or confidence < 0.25:
            return False
        point = self.ranked_loop_click_point(state, self.layout["viewport"])
        if point is None:
            self.last_ranked_navigation_deferred_state = None
            return False
        pending = getattr(self, "pending_match_replays", [])
        if pending or getattr(self, "ranked_match_in_progress", False) \
                or (getattr(self, "last_observed_outcome_kind", None) == "round"
                    and not getattr(self, "ranked_match_finished", False)):
            # A drawn hand hides the bottom tile faces while its overlay fades.
            # The remaining dark table/rivers can resemble the lobby panels.
            # Only a native MATCH result releases navigation, never a round
            # result or the disappearance of hand faces. Consume this frame
            # and reobserve without clicking into an unfinished match.
            if getattr(self, "last_ranked_navigation_deferred_state", None) != state:
                evidence = {}
                if screenshot is not None:
                    snapshot = self.frames / f"{utc_stamp()}.ranked-navigation-deferred.png"
                    snapshot.write_bytes(screenshot)
                    evidence["screenshot"] = str(snapshot)
                self.log("ranked_navigation_deferred_active_match", state=state,
                         confidence=confidence, pendingMatchReplays=len(pending),
                         lastOutcomeKind=getattr(self, "last_observed_outcome_kind", None),
                         **evidence)
            self.last_ranked_navigation_deferred_state = state
            return True
        self.last_ranked_navigation_deferred_state = None
        now = time.monotonic()
        if state == self.last_ranked_loop_state and now - self.last_ranked_loop_click_at < 1.5:
            return True
        page.mouse.click(point["x"], point["y"])
        if state == "ranked_room":
            self.reset_post_riichi_safety()
            self.ranked_match_finished = False
            self.last_observed_outcome_kind = None
            self.rank_promotion_stages_advanced = set()
        self.last_ranked_loop_state = state
        self.last_ranked_loop_click_at = now
        self.log("ranked_loop_advanced", state=state, confidence=confidence, clickPoint=point)
        return True

    def advance_result_screen_once(self, page: Page, state: str, confidence: float) -> bool:
        """Confirm each distinct terminal-result stage exactly once."""
        if state not in {"round_result", "match_result", "rank_progress", "post_match_reward",
                         "rank_promotion", "rank_certificate"} \
                or self.result_screen_advanced == state:
            return False
        if state in {"rank_promotion", "rank_certificate"}:
            point = {"x": 1400 if state == "rank_promotion" else 1525,
                     "y": 550 if state == "rank_promotion" else 150}
        else:
            y_ratio = 0.92 if state in {"match_result", "rank_progress", "post_match_reward"} else 0.935
            point = {"x": self.layout["viewport"]["width"] * 0.91,
                     "y": self.layout["viewport"]["height"] * y_ratio}
        page.mouse.click(point["x"], point["y"])
        self.result_screen_advanced = state
        self.log("screen_advanced", state=state, confidence=confidence, clickPoint=point)
        return True

    def ranked_terminal_transition_requires_stop(self, state: str) -> bool:
        """Fail closed when a *verified match result* becomes ``matchmaking``.

        A round-result summary is not a terminal transition: normal play
        continues at the next hand.  Only the independently classified
        match-result sequence (result board, rank progress, or reward) may
        arm this guard.  That prevents a completed hand from making a later
        in-match frame stop the operator merely because it resembles the
        ranked reservation screen.
        """
        if not (getattr(self.args, "ranked_loop", False)
                and getattr(self, "ranked_terminal_transition_pending", False)
                and state == "matchmaking"):
            self.ranked_terminal_matchmaking_seen_at = None
            return False
        now = time.monotonic()
        first_seen = getattr(self, "ranked_terminal_matchmaking_seen_at", None)
        if first_seen is None:
            self.ranked_terminal_matchmaking_seen_at = now
            return False
        return now - first_seen >= 5.0

    def log_ranked_terminal_transition_stop(self, state, confidence, screenshot=None):
        evidence = {}
        if screenshot is not None:
            snapshot = self.frames / f"{utc_stamp()}.ranked-terminal-transition.png"
            snapshot.write_bytes(screenshot)
            evidence["screenshot"] = str(snapshot)
        self.log("ranked_terminal_transition_stop", state=state,
                 confidence=confidence, gameplayClicks=0,
                 reason="result_transition_missing_verified_ranked_navigation", **evidence)

    def recover_black_screen(self, page: Page) -> bool:
        """Reload a persistently blank client once, using this CDP owner only."""
        now = time.monotonic()
        since = getattr(self, "black_screen_seen_since", None)
        if since is None:
            self.black_screen_seen_since = now
            self.log("black_screen_waiting", minimumDurationSeconds=15, gameplayClicks=0)
            return True
        if now - since < 15:
            return True
        current = page.screenshot(animations="disabled")
        if classify_screen(current, {})[0] != "black_screen":
            self.black_screen_seen_since = None
            self.log("black_screen_stale_frame_ignored", gameplayClicks=0)
            return True
        snapshot = self.frames / f"{utc_stamp()}.black-screen.png"
        snapshot.write_bytes(current)
        snapshot.chmod(0o600)
        attempts = [at for at in getattr(self, "black_screen_reload_attempts", []) if now - at < 600]
        self.black_screen_reload_attempts = attempts
        if attempts:
            self.log("black_screen_recovery_limit_stop", screenshot=str(snapshot),
                     attempts=len(attempts), windowSeconds=600, gameplayClicks=0)
            raise RuntimeError("black client persisted after one reload in ten minutes")
        attempts.append(now)
        self.black_screen_seen_since = None
        if getattr(self, "round_terminal_latched", False) \
                and not getattr(self, "round_terminal_result_observed", False):
            previous = self.round_terminal_previous_state()
            self.round_terminal_recovery = {"previous": previous, "since": None}
            self.closed_new_round_candidate_frames = set()
        self.black_screen_recovery_pending_outcome = bool(getattr(self, "pending_match_replays", []))
        self.black_screen_navigation_since = None
        self.cached_concealed_tiles = None
        self.cached_open_melds = 0
        self.dynamic_layout_required = False
        self.pending_post_call_discard = False
        self.pending_post_call_started_at = None
        self.cached_public_observation = None
        self.previous_public_observation = None
        self.pending_own_discard = None
        self.pending_own_river_confirmation = None
        self.selection_uncertainty_latch = None
        self.public_cache_generation = getattr(self, "public_cache_generation", 0) + 1
        self.public_cache_last_frame_hash = None
        self.last_public_scan_at = 0.0
        self.board_metadata_cache = None
        self.board_metadata_last_scan_at = 0.0
        self.riichi_metadata_history = None
        self.reset_post_riichi_safety()
        self.last_processed_hand = None
        self.armed = True
        self.log("black_screen_reload_requested", screenshot=str(snapshot),
                 durationSeconds=round(now - since, 3), windowSeconds=600, gameplayClicks=0)
        resume_stream = getattr(self, "screencast_session", None) is not None
        if resume_stream:
            self.stop_screencast_gate()
        page.reload(wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2500)
        # Let the client's startup transitions run before resuming continuous
        # capture. A still-running pre-navigation stream kept returning the
        # dark startup logo in the controlled idle recovery check.
        after = page.screenshot()
        if resume_stream:
            self.start_screencast_gate(page)
        state, confidence = classify_screen(after, {})
        evidence = self.frames / f"{utc_stamp()}.black-screen-after-reload.png"
        evidence.write_bytes(after)
        evidence.chmod(0o600)
        self.log("black_screen_recovery_observed", state=state, confidence=confidence,
                 cleared=state != "black_screen", screenshot=str(evidence), gameplayClicks=0)
        return True

    def guard_black_recovery_outcome(self, page: Page, state: str) -> bool:
        """Do not attach an unobserved old match to a new ranked game's result."""
        if not getattr(self, "black_screen_recovery_pending_outcome", False):
            return False
        pending = getattr(self, "pending_match_replays", [])
        if not pending or state in {"match", "away", "round_result"}:
            self.black_screen_recovery_pending_outcome = False
            self.black_screen_navigation_since = None
            return False
        if state not in {"lobby", "ranked_menu", "ranked_room"}:
            self.black_screen_navigation_since = None
            return False
        now = time.monotonic()
        since = getattr(self, "black_screen_navigation_since", None)
        if since is None:
            self.black_screen_navigation_since = now
            return True
        if now - since < 2:
            return True
        current = page.screenshot(animations="disabled")
        if classify_screen(current, {})[0] != state:
            self.black_screen_navigation_since = None
            return True
        snapshot = self.frames / f"{utc_stamp()}.black-screen-unobserved-result.png"
        snapshot.write_bytes(current)
        snapshot.chmod(0o600)
        ledger = self.frames / f"{utc_stamp()}.black-screen-unobserved-result.json"
        ledger.write_text(json.dumps({"screenshot": str(snapshot), "pendingMatchReplays": [str(p) for p in pending],
                                      "reason": "navigation_after_black_recovery_without_match_result"}, indent=2) + "\n")
        ledger.chmod(0o600)
        self.log("black_screen_outcome_missing_stop", screenshot=str(snapshot),
                 ledger=str(ledger), replayCount=len(pending), gameplayClicks=0)
        raise RuntimeError("black-screen recovery reached lobby without the prior match result; recover history before queuing")

    def recover_connection_error(self, page: Page) -> bool:
        """Acknowledge only the verified network message, with bounded retries."""
        # A screencast can still contain the overlay after it was dismissed.
        # Recheck a fresh screenshot before touching its shared confirm target.
        current = page.screenshot(animations="disabled")
        if classify_screen(current, {})[0] != "connection_error":
            self.log("connection_error_stale_frame_ignored", gameplayClicks=0)
            return True
        now = time.monotonic()
        attempts = [at for at in getattr(self, "connection_error_attempts", []) if now - at < 600]
        self.connection_error_attempts = attempts
        if attempts and now - attempts[-1] < 5:
            page.wait_for_timeout(250)
            return True
        snapshot = self.frames / f"{utc_stamp()}.connection-error.png"
        snapshot.write_bytes(current)
        snapshot.chmod(0o600)
        if len(attempts) >= 3:
            self.log("connection_recovery_limit_stop", screenshot=str(snapshot),
                     attempts=len(attempts), windowSeconds=600, gameplayClicks=0)
            raise RuntimeError("Mahjong Soul connection error persisted after three confirmations in ten minutes")
        with Image.open(io.BytesIO(current)) as image:
            point = {"x": image.width * .5, "y": image.height * .639}
        attempts.append(now)
        page.mouse.click(point["x"], point["y"])
        # The game can advance behind this message. Discard observations made
        # before acknowledgement and require current hand/public evidence.
        self.cached_concealed_tiles = None
        self.cached_public_observation = None
        self.previous_public_observation = None
        self.pending_own_discard = None
        self.pending_own_river_confirmation = None
        self.selection_uncertainty_latch = None
        self.public_cache_generation = getattr(self, "public_cache_generation", 0) + 1
        self.public_cache_last_frame_hash = None
        self.last_public_scan_at = 0.0
        self.board_metadata_cache = None
        self.board_metadata_last_scan_at = 0.0
        self.riichi_metadata_history = None
        self.reset_post_riichi_safety()
        self.last_processed_hand = None
        self.armed = True
        self.log("connection_error_confirmed", screenshot=str(snapshot),
                 clickPoint=point, attempt=len(attempts), windowSeconds=600, gameplayClicks=0)
        page.wait_for_timeout(250)
        after = page.screenshot(animations="disabled")
        after_state, after_confidence = classify_screen(after, {})
        evidence = self.frames / f"{utc_stamp()}.connection-after-confirm.png"
        evidence.write_bytes(after)
        evidence.chmod(0o600)
        self.log("connection_recovery_observed", state=after_state, confidence=after_confidence,
                 cleared=after_state != "connection_error", screenshot=str(evidence), gameplayClicks=0)
        return True

    def handle_early_non_gameplay_screen(self, page: Page, state: str, confidence: float,
                                       screenshot: bytes | None = None) -> bool:
        """Handle verified non-gameplay screens before latency quick gates."""
        self.observe_ranked_match_screen(state)
        if state in {"rank_promotion", "rank_certificate"}:
            self.ranked_terminal_matchmaking_seen_at = None
            # Promotion controls are authorized only by this process's verified
            # completed ranked match, with all match replays already attached.
            # A stale stream frame must not click into a later screen.
            if (confidence >= .95 and screenshot is not None
                    and getattr(self.args, "ranked_loop", False)
                    and getattr(self, "ranked_terminal_transition_pending", False)
                    and getattr(self, "ranked_match_finished", False)
                    and not getattr(self, "pending_match_replays", [])
                    and state not in getattr(self, "rank_promotion_stages_advanced", set())
                    and self.result_screen_advanced != state):
                current = page.screenshot(animations="disabled")
                if classify_screen(current, {})[0] == state:
                    self.advance_result_screen_once(page, state, confidence)
                    self.rank_promotion_stages_advanced = {
                        *getattr(self, "rank_promotion_stages_advanced", set()), state,
                    }
            self.log("screen_state_bypassed", state=state, confidence=confidence, gameplayClicks=0)
            return True
        if state == "black_screen":
            if confidence >= .95 and screenshot is not None \
                    and getattr(getattr(self, "args", None), "mode", None) == "force-auto":
                return self.recover_black_screen(page)
            self.black_screen_seen_since = None
            return True
        self.black_screen_seen_since = None
        if self.guard_black_recovery_outcome(page, state):
            return True
        if (state == "connection_error" and confidence >= .95 and screenshot is not None
                and getattr(getattr(self, "args", None), "mode", None) == "force-auto"):
            return self.recover_connection_error(page)
        if state in {"session_conflict", "connection_error"}:
            self.log("blocking_dialog_stop", state=state, confidence=confidence, gameplayClicks=0)
            raise RuntimeError(f"Mahjong Soul {state} dialog blocks the table; operator stopped without confirming it")
        if state in {"round_result", "match_result", "rank_progress", "post_match_reward"}:
            # Only uninterrupted matchmaking observations count toward the
            # five-second guard. These stages bypass its normal reset path.
            self.ranked_terminal_matchmaking_seen_at = None
            if screenshot is not None and state in {"round_result", "match_result"}:
                self.attach_outcome("match" if state == "match_result" else "round",
                                    screenshot, confidence)
            self.cached_concealed_tiles = None
            self.pending_own_discard = None
            self.cached_open_melds = 0
            self.dynamic_layout_required = False
            self.restart_open_hand_probe_hash = None
            self.open_meld_candidate = None
            self.open_meld_candidate_frames = set()
            self.closed_new_round_candidate_frames = set()
            self.public_cache_generation = getattr(self, "public_cache_generation", 0) + 1
            self.public_cache_last_frame_hash = None
            self.cached_public_observation = None
            self.board_metadata_cache = None
            self.board_metadata_last_scan_at = 0.0
            self.riichi_metadata_history = None
            self.reset_post_riichi_safety()
            self.previous_public_observation = None
            self.pending_own_river_confirmation = None
            self.selection_uncertainty_latch = None
            self.last_shanten = None
            self.last_processed_hand = None
            self.armed = True
            self.pending_post_call_discard = False
            self.pending_post_call_started_at = None
            self.round_terminal_latched = True
            self.round_terminal_result_observed = True
            # A hand summary is a normal in-match transition.  Never carry a
            # ranked-navigation guard from it into the next hand; only the
            # independently recognized match-end result sequence can justify
            # stopping on an unverified matchmaking screen.
            if self.args.ranked_loop:
                self.ranked_terminal_transition_pending = state in {
                    "match_result", "rank_progress", "post_match_reward",
                }
            # Save the result first, then permit one confirmation only.  The
            # stop prevents navigating or starting another friend match.
            if self.should_stop_after_match_result(state):
                self.confirm_friend_match_result(page, state, confidence, screenshot)
                self.match_completed_stop_requested = True
                self.log("match_completed_stop", confidence=confidence)
                return True
            if self.args.advance_screens or self.args.ranked_loop:
                self.advance_result_screen_once(page, state, confidence)
            return True
        if state in {"lobby", "ranked_menu", "ranked_room", "matchmaking", "loading"}:
            # A discard whose second, raised-tile confirmation was withheld
            # deliberately leaves the selection state unresolved.  Never
            # issue a retry against it.  If that live friend table has since
            # returned to the lobby without exposing a result frame, there is
            # no safe automated destination and continuing would otherwise
            # spin forever in ``screen_state_bypassed``.  This is terminal
            # evidence for the *operator*, not a synthetic match result: do
            # not attach it to decision replays as one.
            if state == "lobby" \
                    and getattr(self.args, "mode", None) == "force-auto" \
                    and not getattr(self.args, "ranked_loop", False) \
                    and getattr(self, "selection_uncertainty_latch", None):
                self.match_completed_stop_requested = True
                self.log(
                    "match_completed_stop", confidence=confidence,
                    terminalState=state,
                    reason="selection_uncertainty_followed_by_lobby",
                    gameplayClicks=0,
                )
                return True
            if self.ranked_terminal_transition_requires_stop(state):
                self.ranked_terminal_transition_stop_requested = True
                self.log_ranked_terminal_transition_stop(state, confidence, screenshot)
                return True
            # The table-result fade can match the generic lobby reference for
            # several frames (including after a *round*, not a match, result).
            # A lobby alone is therefore not independent proof that ranked
            # navigation has resumed.  Keep the terminal transition guard
            # armed until the rank menu or room is observed after the lobby
            # navigation click.  This still permits that click below, while a
            # subsequent ambiguous matchmaking frame remains fail-closed.
            if state in {"ranked_menu", "ranked_room"} \
                    and getattr(self, "ranked_terminal_transition_pending", False):
                self.ranked_terminal_transition_pending = False
                self.log("ranked_terminal_reentry_verified", state=state, confidence=confidence)
            self.result_screen_advanced = None
            if not self.advance_ranked_loop(page, state, confidence, screenshot=screenshot):
                self.log("screen_state_bypassed", state=state,
                         confidence=confidence, gameplayClicks=0)
            return True
        return False

    def verify_screencast_non_gameplay_state(
        self,
        page: Page,
        state: str,
        confidence: float,
        screenshot: bytes | None,
    ) -> tuple[str, float, bytes | None, bool]:
        """Confirm a streamed navigation/result frame before bypassing table work.

        CDP's screencast may lag behind a fresh page screenshot when a table
        resumes underneath an old lobby frame.  A non-match classification
        otherwise returns from the latency gate before any current table
        evidence is inspected.  This confirmation is deliberately limited to
        the non-gameplay branch, so normal turn handling still uses the low
        latency streamed frame.
        """
        if screenshot is None or state == "match":
            return state, confidence, screenshot, False
        current = page.screenshot(animations="disabled")
        current_state, current_confidence = classify_screen(current, self.screen_references)
        if current_state == state:
            return state, confidence, screenshot, False
        self.log(
            "screencast_non_gameplay_state_rejected",
            streamedState=state,
            streamedConfidence=confidence,
            currentState=current_state,
            currentConfidence=current_confidence,
            gameplayClicks=0,
        )
        return current_state, current_confidence, current, True

    def record_replay(
        self,
        evaluation: dict[str, Any],
        screenshot: Path,
        execution: dict[str, Any] | None = None,
        execution_error: str | None = None,
    ) -> Path:
        """Persist one decision with an explicit, auditable execution state."""
        replay_id = str(uuid.uuid4())
        decision = evaluation["decision"]
        action_id = decision.get("selectedActionId", decision.get("recommendedAction", "unknown"))
        if execution_error:
            execution_evidence = {"status": "failed", "actionId": action_id, "reason": execution_error}
        elif execution and execution.get("clicked") is True:
            execution_evidence = {"status": "verified", "actionId": action_id, "receipt": execution}
        else:
            execution_evidence = {
                "status": "not_attempted",
                "actionId": action_id,
                "reason": (execution or {}).get("reason", "advisor_or_safety_stop"),
            }
        record = {
            "schemaVersion": 1,
            "id": replay_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "screenshot": str(screenshot),
            "state": evaluation["state"],
            "decision": decision,
            "executionEvidence": execution_evidence,
            "evidence": {
                "recognition": evaluation["recognition"],
                **{key: evaluation[key] for key in ("operatorTiming", "turnTiming", "publicCache")
                   if key in evaluation},
                **({"execution": execution} if execution else {}),
                **({"executionError": execution_error} if execution_error else {}),
            },
        }
        path = self.replays / f"{replay_id}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)
        with (self.replays / "decisions.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        (self.replays / "decisions.jsonl").chmod(0o600)
        self.pending_round_replays.append(path)
        self.pending_match_replays.append(path)
        return path

    def attach_outcome(self, kind: str, screenshot: bytes, confidence: float) -> int:
        """Attach one observed result screen to all decisions in its scope."""
        if kind not in {"round", "match"}:
            raise ValueError(f"unsupported outcome kind: {kind}")
        pending = self.pending_round_replays if kind == "round" else self.pending_match_replays
        if not pending and getattr(self, "last_observed_outcome_kind", None) == kind:
            self.observe_ranked_outcome(kind)
            return 0
        screen_state = f"{kind}_result"
        screenshot_path = self.frames / f"{utc_stamp()}.{screen_state}.png"
        screenshot_path.write_bytes(screenshot)
        evidence = {
            "observedAt": datetime.now(timezone.utc).isoformat(),
            "screenshot": str(screenshot_path),
            "screenState": screen_state,
            "screenConfidence": confidence,
        }
        self.last_observed_outcome_kind = kind
        self.log("outcome_observed", kind=kind, replayCount=len(pending), evidence=evidence)
        if not pending:
            self.observe_ranked_outcome(kind)
            return 0
        for replay_path in pending:
            record = load_json(replay_path)
            record.setdefault("actualResult", {})[kind] = evidence
            replacement = replay_path.with_suffix(".json.tmp")
            replacement.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            replacement.chmod(0o600)
            replacement.replace(replay_path)
        jsonl_path = self.replays / "decisions.jsonl"
        pending_ids = {replay_path.stem for replay_path in pending}
        if jsonl_path.exists():
            records = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line]
            for record in records:
                if record.get("id") in pending_ids:
                    record.setdefault("actualResult", {})[kind] = evidence
            replacement = jsonl_path.with_suffix(".jsonl.tmp")
            replacement.write_text(
                "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records),
                encoding="utf-8",
            )
            replacement.chmod(0o600)
            replacement.replace(jsonl_path)
        count = len(pending)
        if kind == "round":
            self.pending_round_replays = []
        else:
            self.pending_match_replays = []
            self.pending_round_replays = []
        self.log("outcome_attached", kind=kind, replayCount=count, evidence=evidence)
        self.observe_ranked_outcome(kind)
        return count

    def evaluate(self, screenshot: Path, pending_discard: dict[str, str] | None = None,
                 public_observation: dict[str, Any] | None = None,
                 recognition: dict[str, Any] | None = None,
                 available_ui_actions: list[str] | None = None, *,
                 prepared_metadata: dict[str, Any] | None = None,
                 captured_at: float | None = None) -> dict[str, Any]:
        evaluator_mode = "advisor" if self.args.mode == "observer" else self.args.mode
        state_path = self.state_path
        if getattr(self.args, "board_metadata", False):
            state, public_observation, pending_discard = self.frame_metadata_state(
                screenshot, public_observation, pending_discard, prepared_metadata=prepared_metadata,
            )
            state_path = self.frames / f"{utc_stamp()}.board-state.json"
            state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        elif getattr(self.args, "match_length", None) is not None:
            state_path = self.frames / f"{utc_stamp()}.board-state.json"
            state_path.write_text(json.dumps(self.public_state, ensure_ascii=False), encoding="utf-8")
        command = [
            "node", "dist/src/cli.js", "evaluate-frame", str(screenshot),
            str(self.layout_path), str(self.templates), f"--state={state_path}",
            f"--mode={evaluator_mode}",
        ]
        if self.args.action_templates:
            command.append(f"--action-templates={Path(self.args.action_templates).resolve()}")
        if pending_discard:
            command.append(f"--pending-discard={pending_discard['tile']},{pending_discard['fromSeat']}")
        if public_observation:
            observation_path = self.frames / f"{utc_stamp()}.public-observation.json"
            observation_path.write_text(json.dumps(public_observation, ensure_ascii=False), encoding="utf-8")
            command.append(f"--public-observation={observation_path}")
        if recognition is not None:
            recognition_path = self.frames / f"{utc_stamp()}.recognition.json"
            recognition_path.write_text(json.dumps(recognition, ensure_ascii=False), encoding="utf-8")
            command.append(f"--recognition-file={recognition_path}")
        if available_ui_actions:
            command.append(f"--available-ui-actions={','.join(available_ui_actions)}")
        if evaluator_mode == "force-auto" and pending_discard and public_observation and recognition is not None and available_ui_actions:
            command = [
                "node", "dist/src/recognition/reactionEvaluator.js", str(state_path),
                str(observation_path), str(recognition_path), pending_discard["tile"],
                pending_discard["fromSeat"], ",".join(available_ui_actions),
            ]
        evaluation_env = self.evaluator_env
        if captured_at is not None and self.args.mode == "force-auto":
            # The CLI has launch/serialization work in addition to the normal
            # 350ms click guard reserve. Age the original prompt, never reset it.
            remaining = self.force_auto_click_budget_ms() - round((time.monotonic() - captured_at) * 1000)
            decision_budget = max(1, min(int(self.evaluator_env.get("JEV_FORCE_AUTO_DEADLINE_MS", "2300")),
                                         remaining - 650))
            evaluation_env = {**self.evaluator_env, "JEV_FORCE_AUTO_DEADLINE_MS": str(decision_budget)}
            self.log("reaction_decision_budget", remainingMs=remaining, decisionBudgetMs=decision_budget,
                     preClickAndLaunchReserveMs=650)
        result = subprocess.run(
            command,
            cwd=self.root,
            env=evaluation_env,
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            timeout=self.args.evaluation_timeout,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "frame evaluator failed").strip())
        return json.loads(result.stdout)

    def recognize_reaction_context(self, screenshot: Path, *, captured_at: float | None = None):
        """Recognize the same immutable prompt across independent workers."""
        results = {}
        failures = []
        started = time.monotonic()
        timings = {}
        def run(name, callback):
            try:
                results[name] = callback()
                timings[name + "Ms"] = round((time.monotonic() - started) * 1000)
            except Exception as error:
                failures.append(error)
        workers = [
            threading.Thread(target=run, args=("public", lambda: self.observe_public_board(screenshot, reaction_highlight=True))),
            threading.Thread(target=run, args=("hand", lambda: self.recognize_reaction_hand(screenshot))),
        ]
        for worker in workers:
            worker.start()
        frame = screenshot.read_bytes() if captured_at is not None else None
        try:
            metadata = self.current_board_metadata(screenshot)
            timings["metadataMs"] = round((time.monotonic() - started) * 1000)
        finally:
            for worker in workers:
                worker.join()
        if failures:
            raise failures[0]
        # Publish only direct OCR of this immutable prompt, never extend the
        # lifetime of a previously cached result merely because it was reused.
        now = time.monotonic()
        current = getattr(self, "board_metadata_cache", None)
        if (frame is not None and isinstance(captured_at, (int, float))
                and now - 8.0 <= captured_at <= now
                and metadata.get("verified") is True
                and metadata.get("source") == str(screenshot)
                and screenshot.read_bytes() == frame
                and (not current or current["capturedAt"] < captured_at)):
            self.board_metadata_cache = {
                "metadata": copy.deepcopy(metadata), "signature": board_state_signature(frame),
                "wallSignature": wall_counter_signature(frame), "capturedAt": captured_at,
                "screenshot": str(screenshot),
            }
            self.log("board_metadata_reaction_promoted", screenshot=str(screenshot))
        self.log("reaction_parallel_recognition", screenshot=str(screenshot),
                 elapsedMs=round((time.monotonic() - started) * 1000), **timings)
        return results["public"], results["hand"], metadata

    def evaluate_force_auto_call_policy(
        self, screenshot: Path, call_action: str, *, captured_at: float | None = None,
    ) -> dict[str, Any] | None:
        """Run a visually unambiguous call through the normal legal policy.

        A lone green button proves only the UI action variant.  It does not
        prove that opening the hand is strategically sound, nor which discard
        triggered it. Require one exact river append or an independently
        verified unique highlight on the prompt's final river tile.
        """
        public_observation = self.cached_public_observation
        def river_evidence(observation):
            if not observation:
                return None
            return {"capturedAt": observation.get("capturedAt"),
                    "ownDiscards": observation.get("ownDiscards", []),
                    "opponentDiscards": [{"seat": item.get("seat"),
                                          "discards": item.get("discards", [])}
                                         for item in observation.get("opponentDiscards", [])]}
        # Always recognize this prompt before rejecting stale cache history.
        # Prefer the newest baseline; the older one is useful only if the
        # async cache already contains this prompt's exact single append.
        recognition = None
        metadata = None
        if getattr(getattr(self, "args", None), "board_metadata", False):
            fresh_public, recognition, metadata = self.recognize_reaction_context(screenshot, captured_at=captured_at)
        else:
            fresh_public = self.observe_public_board(screenshot, reaction_highlight=True)
        pending = self.infer_pending_discard(public_observation, fresh_public)
        baseline = "cached"
        if not pending:
            pending = self.infer_pending_discard(self.previous_public_observation, fresh_public)
            baseline = "previous"
        highlighted = self.pending_highlighted_discard(fresh_public, call_action,
                                                       self.public_state.get("seat", "east"))
        # Infer the call against the old baseline before publishing this
        # observation. Cache promotion is independent of call approval.
        if metadata is None or metadata.get("verified"):
            self.promote_reaction_public_observation(fresh_public)
        if pending and highlighted and pending != highlighted:
            self.log("reaction_call_policy_rejected", action=call_action,
                     reason="river_history_and_highlight_conflict")
            return None
        if not pending and highlighted:
            pending = highlighted
            baseline = "verified_prompt_highlight"
        if not pending:
            self.log("reaction_call_policy_rejected", action=call_action,
                     reason="pending_discard_not_verified_on_prompt_frame",
                     riverEvidence={"previous": river_evidence(self.previous_public_observation),
                                    "cached": river_evidence(public_observation),
                                    "prompt": river_evidence(fresh_public)})
            return None
        self.log("reaction_discard_verified", action=call_action, pendingDiscard=pending,
                 baseline=baseline, screenshot=str(screenshot))
        public_observation = fresh_public
        if recognition is None:
            recognition = self.recognize_reaction_hand(screenshot)
        expected = 13 - getattr(self, "cached_open_melds", 0) * 3
        if len(recognition.get("tiles", [])) != expected:
            self.log("reaction_call_policy_rejected", action=call_action,
                     reason="concealed_hand_not_verified", recognized=len(recognition.get("tiles", [])),
                     expected=expected)
            return None
        try:
            evaluation = self.evaluate(
                screenshot, pending, public_observation, recognition,
                [call_action, "pass"], prepared_metadata=metadata, captured_at=captured_at,
            )
        except RuntimeError as error:
            # Invalid recognized tile counts must never reach mouse execution.
            # Reacquire within the existing deadline; unrelated failures remain fatal.
            if re.search(r"^More than four copies of (?:[1-9][mps]|[ESWNPFC])\r?$",
                         str(error), re.MULTILINE):
                raise RetryableSafetyAbort("reaction_tile_count_conflict") from error
            raise
        decision = evaluation.get("decision", {})
        selected = decision.get("selectedAction", {})
        if evaluation.get("status") != "decision" or selected.get("action") != call_action:
            self.log("reaction_call_policy_rejected", action=call_action,
                     reason="strategy_selected_pass", handPlan=decision.get("handPlan"),
                     callAssessments=decision.get("callAssessments"))
            return None
        assessment = next((item for item in decision.get("callAssessments", [])
                           if item.get("actionId") == selected.get("id")), None)
        if not assessment or not assessment.get("approved"):
            self.log("reaction_call_policy_rejected", action=call_action,
                     reason="call_not_certified", assessment=assessment)
            return None
        evaluation["verifiedCallDiscard"] = dict(pending)
        return evaluation

    def reconcile_confirmed_call_discard(
        self, pending: dict[str, Any], selected_action: dict[str, Any] | None = None,
    ) -> None:
        """Record the confirmed meld and remove only the verified called tail.

        Old asynchronous snapshots must not restore the pre-call river. Do not
        interpret arbitrary OCR shrinkage as a call or remove an interior tile.
        """
        self.public_cache_generation = getattr(self, "public_cache_generation", 0) + 1
        self.public_cache_last_frame_hash = None
        self.last_public_scan_at = 0.0
        removed = 0
        confirmed_meld = confirmed_call_meld(selected_action)
        for attribute in ("cached_public_observation", "previous_public_observation"):
            observation = getattr(self, attribute, None)
            if not observation:
                continue
            opponents = []
            changed = False
            for item in observation.get("opponentDiscards", []):
                river = item.get("discards", [])
                if item.get("seat") == pending.get("fromSeat") and river and river[-1] == pending.get("tile"):
                    item = {**item, "discards": river[:-1]}
                    removed += 1
                    changed = True
                opponents.append(item)
            own_melds = list(observation.get("ownMelds", []))
            if confirmed_meld and confirmed_meld not in own_melds:
                own_melds.append(confirmed_meld)
                changed = True
            own_meld_tiles = [tile for meld in own_melds for tile in meld.get("tiles", [])]
            if changed:
                all_meld_tiles = [*own_meld_tiles, *[
                    tile for item in opponents for meld in item.get("melds", []) for tile in meld.get("tiles", [])
                ]]
                other_visible = [*[tile for item in opponents for tile in item.get("discards", [])], *all_meld_tiles]
                setattr(self, attribute, {**observation, "opponentDiscards": opponents,
                    "ownMelds": own_melds, "ownMeldTiles": own_meld_tiles,
                    "ownMeldsObserved": bool(confirmed_meld),
                    "allMeldTiles": all_meld_tiles, "otherVisibleTiles": other_visible,
                    "acceptedTiles": len(observation.get("doraIndicators", []))
                    + len(observation.get("ownDiscards", [])) + len(other_visible)})
        self.log("called_river_reconciled", pendingDiscard=pending, removedSnapshots=removed,
                 confirmedMeld=confirmed_meld, publicCacheGeneration=self.public_cache_generation)

    def reconcile_own_discard(self) -> None:
        """Trust the concealed-hand cache only after the observed river agrees.

        On a short clock Mahjong Soul can tsumogiri while an evaluation is in
        flight.  The resulting hand/river pixel changes used to be accepted as
        proof that the requested tile was discarded, poisoning the cached hand
        for every later turn.  The asynchronous public observation supplies an
        independent tile identity before that cache may be reused.
        """
        pending = getattr(self, "pending_own_discard", None)
        if not pending:
            return
        observation = getattr(self, "cached_public_observation", None)
        if not observation:
            return
        before = pending["before"]
        after = observation.get("ownDiscards", [])
        if len(after) <= len(before):
            return
        if pending.get("earlierReceipts"):
            self.reconcile_own_discard_receipts(pending, observation)
            return
        # A public scan can catch up with the discard immediately before this
        # click.  In that case the first confirmed append is not evidence that
        # this click selected the wrong tile: the requested tile can appear as
        # the next append on the following independently-confirmed scan.  Do
        # not quarantine that public identity or label it a wrong physical
        # click until a later capture has had an opportunity to distinguish
        # those two histories.
        mismatch = pending.get("mismatchCandidate")
        if mismatch:
            candidate = mismatch["actual"]
            if (after[:len(before)] == before and len(after) >= len(before) + 1
                    and same_physical_tile(after[len(before)], pending["tile"])):
                self.pending_own_discard = None
                self.pending_own_river_confirmation = None
                self.cached_concealed_tiles = None
                self.log("own_discard_reconciled", tile=after[len(before)],
                         followingAutomaticDiscards=len(after) - len(before) - 1,
                         concealedCacheInvalidated=True)
                return
            if (after[:len(before)] == before and len(after) >= len(before) + 2
                    and same_physical_tile(after[len(before)], candidate)
                    and same_physical_tile(after[len(before) + 1], pending["tile"])):
                self.cached_concealed_tiles = None
                self.pending_own_discard = None
                self.pending_own_river_confirmation = None
                self.log("own_discard_reconciled_after_delayed_prior_append",
                         tile=after[len(before) + 1], delayedPriorAppend=candidate,
                         before=before, observed=after,
                         firstCapturedAt=mismatch.get("capturedAt"),
                         confirmedCapturedAt=observation.get("capturedAt"),
                         concealedCacheInvalidated=True)
                return
            first_capture = public_capture_seconds(mismatch.get("capturedAt"))
            current_capture = public_capture_seconds(observation.get("capturedAt"))
            if (after[:len(before)] == before and len(after) == len(before) + 1
                    and same_physical_tile(after[-1], candidate)
                    and first_capture is not None and current_capture is not None
                    and current_capture > first_capture):
                # A third, newer capture with the same single append rules out
                # a momentary recognition lag.  This remains a real mismatch,
                # so preserve the existing cache quarantine behaviour.
                pending.pop("mismatchCandidate", None)
            else:
                return
        # After a confirmed riichi declaration the game can tsumogiri several
        # times before two independent public scans agree. Verify the exact
        # declaration position, never merely search for the tile in the tail.
        if (pending.get("riichiDeclaration") and observation.get("ownRiichiDeclared")
                and after[:len(before)] == before and len(after) > len(before) + 1
                and same_physical_tile(after[len(before)], pending["tile"])):
            self.cached_concealed_tiles = None
            self.pending_own_discard = None
            self.log("own_discard_reconciled", tile=after[len(before)],
                     followingAutomaticDiscards=len(after) - len(before) - 1,
                     concealedCacheInvalidated=True)
            return
        if after[:len(before)] != before or len(after) != len(before) + 1:
            self.cached_concealed_tiles = None
            self.pending_own_discard = None
            self.log(
                "own_discard_reconciliation_failed",
                expected=pending["tile"], before=before, observed=after,
                reason="river_history_not_single_append",
                clickIndex=pending.get("clickIndex"), clickPoint=pending.get("clickPoint"),
                clickedAt=pending.get("clickedAt"), confirmation=pending.get("confirmation"),
            )
            return
        actual = after[-1]
        if not same_physical_tile(actual, pending["tile"]):
            if not mismatch:
                pending["mismatchCandidate"] = {
                    "actual": actual,
                    "capturedAt": observation.get("capturedAt"),
                }
                # Block a subsequent discard while this receipt is ambiguous.
                # The candidate had already passed the public-cache's first
                # two-scan admission; this is a separate temporal check for a
                # prior append that recognition observed late.
                self.pending_own_river_confirmation = list(after)
                self.log(
                    "own_discard_mismatch_pending",
                    expected=pending["tile"], actual=actual, before=before,
                    observed=after, capturedAt=observation.get("capturedAt"),
                    clickIndex=pending.get("clickIndex"), clickPoint=pending.get("clickPoint"),
                    clickedAt=pending.get("clickedAt"), confirmation=pending.get("confirmation"),
                )
                return
            self.cached_concealed_tiles = None
            # The independent river scan proved only that *some* tile was
            # appended. It did not prove this OCR identity. Keeping that
            # identity in the public cache would feed a false safe tile and
            # false remaining-tile count into every subsequent decision.
            # Retain the rest of the fresh public observation, but quarantine
            # the untrusted own-river append until a later scan can establish
            # it without being tied to this failed click reconciliation.
            observation["ownDiscards"] = list(before)
            self.pending_own_river_confirmation = None
            self.log(
                "own_discard_mismatch",
                expected=pending["tile"], actual=actual,
                evidenceToClickMs=pending.get("evidenceToClickMs"),
                before=before,
                observed=after,
                capturedAt=observation.get("capturedAt"),
                clickIndex=pending.get("clickIndex"), clickPoint=pending.get("clickPoint"),
                clickedAt=pending.get("clickedAt"), confirmation=pending.get("confirmation"),
            )
            self.log(
                "own_discard_mismatch_cache_quarantined",
                expected=pending["tile"], rejected=actual,
                retainedOwnDiscards=list(before),
            )
            # Keep the receipt unresolved: an incomplete river must never be
            # supplied to a later discard decision. Future scans can still
            # resolve it when the expected tile is recognized.
            pending["mismatchCandidate"] = {"actual": actual,
                                            "capturedAt": observation.get("capturedAt")}
            self.pending_own_river_confirmation = list(after)
            return
        else:
            self.log("own_discard_reconciled", tile=actual)
            self.record_post_riichi_pass_candidate(pending, actual)
        self.pending_own_discard = None

    @staticmethod
    def own_discard_meld_snapshot(evaluation: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        """Retain only explicitly observed opponent melds from before a click."""
        result = {}
        opponents = evaluation.get("state", {}).get("opponents", [])
        seats = [opponent.get("seat") for opponent in opponents]
        if len(set(seats)) != len(seats):
            return result
        for opponent in opponents:
            melds = opponent.get("melds", [])
            if (opponent.get("openMeldsObserved") is not True
                    or opponent.get("openMelds") != len(melds)):
                continue
            result[opponent["seat"]] = [{"type": meld["type"], "tiles": list(meld["tiles"])}
                                        for meld in melds]
        return result

    def register_pending_own_discard(self, pending: dict[str, Any]) -> None:
        """Keep earlier unverified receipts when public recognition skips a turn.

        No requested tile is added to the public river here. A later independent
        river observation must match every receipt in order before any of these
        identities can certify the concealed cache.
        """
        previous = getattr(self, "pending_own_discard", None)
        if previous:
            if previous["before"] == pending["before"]:
                earlier = [*previous.get("earlierReceipts", []),
                           {key: value for key, value in previous.items() if key != "earlierReceipts"}]
                possible_calls = []
                signature = lambda meld: (meld["type"], tuple(sorted(meld["tiles"])))
                for receipt in earlier:
                    for seat, old in receipt.get("opponentMeldsBefore", {}).items():
                        current = pending.get("opponentMeldsBefore", {}).get(seat)
                        if current is None or [signature(meld) for meld in current[:len(old)]] \
                                != [signature(meld) for meld in old]:
                            continue
                        for meld in current[len(old):]:
                            if meld["type"] in {"chi", "pon", "minkan"} and any(
                                    same_physical_tile(tile, receipt["tile"]) for tile in meld["tiles"]):
                                possible_calls.append({"seat": seat, "meld": meld,
                                    "tile": receipt["tile"], "clickedAt": receipt.get("clickedAt")})
                if possible_calls:
                    # A later identical tile in the river cannot identify which
                    # click survived a call. Retire the older queue without
                    # certifying a call, discard, or post-riichi safe tile.
                    self.cached_concealed_tiles = None
                    self.pending_own_river_confirmation = None
                    self.log("own_discard_reconciliation_unresolved",
                             reason="new_meld_may_contain_pending_discard", before=pending["before"],
                             receiptTiles=[item["tile"] for item in earlier],
                             possibleCalledReceipts=possible_calls, concealedCacheInvalidated=True)
                else:
                    pending["earlierReceipts"] = earlier
                    self.log("own_discard_receipts_queued", before=pending["before"],
                             expected=[item["tile"] for item in earlier] + [pending["tile"]])
            else:
                self.cached_concealed_tiles = None
                self.log("own_discard_reconciliation_unresolved",
                         reason="receipt_replaced_with_different_river_baseline",
                         expected=previous["tile"], before=previous["before"],
                         earlierReceipts=previous.get("earlierReceipts", []),
                         nextBaseline=pending["before"], concealedCacheInvalidated=True)
        pending["registeredMonotonic"] = time.monotonic()
        self.pending_own_discard = pending

    def reconcile_own_discard_receipts(self, pending: dict[str, Any], observation: dict[str, Any]) -> None:
        """Verify a strict prefix of queued receipts against independent scans."""
        before = pending["before"]
        after = observation.get("ownDiscards", [])
        receipts = [*pending["earlierReceipts"], pending]
        appended = after[len(before):]
        if after[:len(before)] != before or len(appended) > len(receipts):
            self.cached_concealed_tiles = None
            self.pending_own_discard = None
            self.log("own_discard_reconciliation_failed", expected=pending["tile"],
                     before=before, observed=after, reason="river_history_not_receipt_sequence",
                     receiptTiles=[item["tile"] for item in receipts],
                     clickIndex=pending.get("clickIndex"), clickPoint=pending.get("clickPoint"),
                     clickedAt=pending.get("clickedAt"), confirmation=pending.get("confirmation"))
            return
        wrong = next((index for index, actual in enumerate(appended)
                      if not same_physical_tile(actual, receipts[index]["tile"])), None)
        if wrong is None and len(appended) < len(receipts):
            # Even a matching prefix is ambiguous when a later identical
            # receipt can explain the same observed river. Unknown/unreadable
            # melds must not turn this into proof of the older click.
            latest_positions = []
            cursor = len(receipts) - 1
            for actual in reversed(appended):
                while cursor >= 0 and not same_physical_tile(actual, receipts[cursor]["tile"]):
                    cursor -= 1
                latest_positions.append(cursor)
                cursor -= 1
            if list(reversed(latest_positions)) != list(range(len(appended))):
                self.cached_concealed_tiles = None
                self.pending_own_discard = None
                observation["ownDiscards"] = list(before)
                self.pending_own_river_confirmation = None
                self.log("own_discard_reconciliation_unresolved",
                         reason="ambiguous_identical_receipt_prefix", before=before, observed=after,
                         capturedAt=observation.get("capturedAt"),
                         receiptTiles=[item["tile"] for item in receipts],
                         concealedCacheInvalidated=True, untrustedAppendQuarantined=True)
                return
        if wrong is not None:
            # A requested discard may disappear into a call before either
            # independent scan sees it. A sparse ordered sequence cannot tell
            # that apart from an unverified/ineffective earlier click. Neither
            # case proves an identity mismatch or certifies any queued click.
            cursor = 0
            for receipt in receipts:
                if cursor < len(appended) and same_physical_tile(appended[cursor], receipt["tile"]):
                    cursor += 1
            if len(appended) < len(receipts) and cursor == len(appended):
                self.cached_concealed_tiles = None
                self.pending_own_discard = None
                # Two independently admitted river scans can show the later
                # receipt while the first tile was taken before any scan saw
                # it. Preserve the visible append only when an independently
                # observed new pon is compatible with that missing receipt.
                # This still does not certify which physical tile was called
                # or retain the concealed cache.
                retain_append = False
                if (len(receipts) == 2 and len(appended) == 1
                        and not same_physical_tile(receipts[0]["tile"], receipts[1]["tile"])
                        and same_physical_tile(appended[0], receipts[1]["tile"])):
                    first = receipts[0]
                    captured = public_capture_seconds(observation.get("capturedAt"))
                    clicked = public_capture_seconds(first.get("clickedAt"))
                    if captured is not None and clicked is not None and captured > clicked:
                        for row in observation.get("opponentDiscards", []):
                            old = first.get("opponentMeldsBefore", {}).get(row.get("seat"))
                            new = row.get("melds", [])
                            if row.get("meldsObserved") is not True or old is None:
                                continue
                            if new[:len(old)] != old or len(new) != len(old) + 1:
                                continue
                            meld = new[-1]
                            tiles = meld.get("tiles", [])
                            if (meld.get("type") == "pon" and len(tiles) == 3
                                    and all(tile == first["tile"] for tile in tiles)):
                                retain_append = True
                                break
                if not retain_append:
                    observation["ownDiscards"] = list(before)
                self.pending_own_river_confirmation = None
                self.log("own_discard_reconciliation_unresolved",
                         reason="river_missing_queued_receipt", before=before, observed=after,
                         capturedAt=observation.get("capturedAt"),
                         receiptTiles=[item["tile"] for item in receipts],
                         concealedCacheInvalidated=True, untrustedAppendQuarantined=not retain_append)
                return
            rejected = receipts[wrong]
            self.cached_concealed_tiles = None
            observation["ownDiscards"] = list(before)
            # As with a single mismatched receipt, quarantining the OCR
            # identity does not make the missing river history safe to use.
            # Keep the whole sequence pending until independent observations
            # establish it, and block further discard decisions meanwhile.
            self.pending_own_river_confirmation = list(after)
            self.log("own_discard_mismatch", expected=rejected["tile"], actual=appended[wrong],
                     before=before, observed=after, capturedAt=observation.get("capturedAt"),
                     evidenceToClickMs=rejected.get("evidenceToClickMs"),
                     clickIndex=rejected.get("clickIndex"), clickPoint=rejected.get("clickPoint"),
                     clickedAt=rejected.get("clickedAt"), confirmation=rejected.get("confirmation"),
                     receiptTiles=[item["tile"] for item in receipts])
            self.log("own_discard_mismatch_cache_quarantined", expected=rejected["tile"],
                     rejected=appended[wrong], retainedOwnDiscards=list(before))
            return
        # Partial observations certify only their exact prefix. Later receipts
        # remain pending and continue to prevent reuse of the concealed cache.
        for index, (receipt, actual) in enumerate(zip(receipts, appended)):
            self.log("own_discard_reconciled", tile=actual,
                     receiptSequenceLength=len(receipts), clickedAt=receipt.get("clickedAt"))
            self.record_post_riichi_pass_candidate({**receipt,
                "before": [*before, *appended[:index]]}, actual)
        remaining = receipts[len(appended):]
        if remaining:
            pending["before"] = list(after)
            pending["earlierReceipts"] = remaining[:-1]
            if not pending["earlierReceipts"]:
                pending.pop("earlierReceipts")
        else:
            self.pending_own_discard = None

    def own_discard_baseline(self, evaluation: dict[str, Any]) -> list[str]:
        """Return the river snapshot that the asynchronous verifier will extend.

        A force-auto evaluation may carry an older, independently recognized
        public state while the resident public-cache worker has already
        observed additional own discards.  Comparing that old evaluation
        snapshot to a later cache observation makes a single correct discard
        look like a multi-tile jump.  The pending verifier must therefore use
        the cache snapshot it will subsequently reconcile against.
        """
        cached = getattr(self, "cached_public_observation", None)
        if isinstance(cached, dict) and isinstance(cached.get("ownDiscards"), list):
            return list(cached["ownDiscards"])
        state = evaluation.get("state", {})
        return list(state.get("ownDiscards", []))

    def own_discard_reconciliation_pending(self) -> bool:
        """Whether another discard would outrun independent river evidence.

        Only an observed candidate can block a later self turn.  A pending
        click without a candidate may be a false post-click confirmation; in
        that state waiting for the river can consume the entire 300-second
        game timer and turn the eventual automatic discard into fake evidence.
        Once a candidate exists, however, a later discard could make two
        additions indistinguishable from one bad append.
        """
        return bool(
            getattr(self, "pending_own_discard", None)
            and getattr(self, "pending_own_river_confirmation", None) is not None
        )

    def refresh_discard_reconciliation_before_click(self) -> bool:
        """Close the async-cache race between evaluation and a next click."""
        if hasattr(self, "public_recognition_lock"):
            self.poll_public_recognition()
        if not self.own_discard_reconciliation_pending():
            return False
        pending = self.pending_own_discard
        self.log(
            "own_discard_reconciliation_pre_click_wait",
            expected=pending.get("tile"), before=pending.get("before"),
            confirmationCandidate=self.pending_own_river_confirmation,
        )
        return True

    def stage_hand_during_discard_reconciliation(
        self, screenshot: Path, captured_at: float | None,
    ) -> dict[str, Any] | None:
        """Overlap hand recognition with the independent public receipt scan.

        Staging never decides or clicks. Return a result only if the normal
        two-observation reconciliation has completed, so the later evaluator
        sees the updated public state and the normal pre-click guards apply.
        """
        if not getattr(self.args, "board_metadata", False) \
                or not self.force_auto_has_recognition_window(captured_at) \
                or self.cached_board_metadata(screenshot) is None:
            return None
        try:
            staged = self.recognize_resident(
                screenshot, dynamic_layout=self.dynamic_layout_required,
                open_melds=self.cached_open_melds if self.cached_open_melds > 0 else None,
                stage_force_auto_recognition=True,
            )
        except RuntimeError as error:
            self.log("reconciliation_hand_stage_failed", error=str(error))
            return None
        self.poll_public_recognition()
        self.reconcile_own_discard()
        if self.own_discard_reconciliation_pending():
            return None
        return staged

    def should_stop_after_match_result(self, screen_state: str) -> bool:
        """Stop a completed friend regression after its optional confirmation.

        Ranked-loop is the only mode that is allowed to continue beyond a
        match result. Friend functional runs must stop after result evidence
        is attached even when callers intentionally disabled screen advances.
        """
        return bool(
            screen_state == "match_result"
            and getattr(self.args, "mode", None) == "force-auto"
            and not getattr(self.args, "ranked_loop", False)
        )

    def confirm_friend_match_result(self, page: Page, state: str, confidence: float,
                                    screenshot: bytes | None) -> None:
        """Confirm only after the caller has attached the captured result."""
        if self.args.advance_screens and screenshot is not None:
            self.advance_result_screen_once(page, state, confidence)

    def force_auto_riichi_kan_fallback(self, screenshot: Path, evaluation: dict[str, Any]) -> dict[str, Any] | None:
        """Route the existing decline-kan-after-riichi policy to an actual skip.

        A pending kan selection blocks tile clicks. It is not an opponent's
        thirteen-tile reaction, and magenta must not be promoted to tsumo/ron.
        """
        if self.args.mode != "force-auto" or evaluation.get("status") != "decision":
            return None
        state = evaluation.get("state", {})
        recognition = evaluation.get("recognition", {})
        selected = evaluation.get("decision", {}).get("selectedAction", {})
        tiles = recognition.get("tiles", [])
        if (not state.get("riichiDeclared") or state.get("openMelds", 0) != 0
                or selected.get("action") != "discard" or len(tiles) != 14
                or not isinstance(state.get("draw"), str) or not all(isinstance(tile, str) for tile in tiles)
                or tiles != [*state.get("hand", []), state.get("draw")]):
            return None
        canonical = lambda tile: f"5{tile[1]}" if len(tile) == 2 and tile[0] == "0" else tile
        if sum(canonical(tile) == canonical(state["draw"]) for tile in tiles) != 4:
            return None
        prompt = force_auto_riichi_kan_prompt(screenshot.read_bytes(), self.layout["viewport"],
                                            self.layout.get("actionButtonRegions", {}).get("pass"))
        if not prompt:
            return None
        return {"schemaVersion": 1, "status": "reaction_prompt", "reactionFrame": str(screenshot),
                "state": state, "recognition": recognition, "availableUiActions": ["kan", "pass"],
                "decision": {"recommendedAction": "pass", "selectedAction": {"id": "pass", "action": "pass"},
                             "source": "decline_kan_after_riichi"},
                "actionButton": {"action": "pass", "present": True, "confidence": 1,
                                 "center": prompt["pass"]["center"], "source": "force_auto_riichi_kan_pass"}}

    def force_auto_reaction_fallback(
        self, screenshot: Path, *, contextual_prompt_verified: bool = False,
    ) -> dict[str, Any] | None:
        """Build a pass-only reaction result when action templates are absent."""
        if self.args.mode != "force-auto" or self.args.action_templates:
            return None
        region = self.layout.get("actionButtonRegions", {}).get("pass")
        if not region or (not contextual_prompt_verified
                          and not is_force_auto_pass_prompt(screenshot.read_bytes(), region)):
            return None
        recognition = self.recognize_reaction_hand(screenshot)
        expected_concealed = 13 - getattr(self, "cached_open_melds", 0) * 3
        if len(recognition.get("tiles", [])) != expected_concealed:
            return None
        point = {
            "x": region["x"] + region["width"] / 2,
            "y": region["y"] + region["height"] / 2,
        }
        return {
            "schemaVersion": 1,
            "status": "reaction_prompt",
            "reactionFrame": str(screenshot),
            "recognition": recognition,
            "availableUiActions": ["pass"],
            "actionButton": {
                "action": "pass", "present": True, "confidence": 1,
                "center": point, "source": "force_auto_fixed_geometry",
            },
        }

    def recognize_reaction_hand(self, screenshot: Path) -> dict[str, Any]:
        open_melds = getattr(self, "cached_open_melds", 0)
        if not open_melds and getattr(self, "layout", {}).get("handSlots"):
            frame = screenshot.read_bytes()
            candidate = geometric_reaction_open_meld_count(frame, self.layout)
            if candidate is not None:
                recovered = self.stable_open_meld_count(candidate, frame)
                if recovered is not None:
                    open_melds = self.cached_open_melds = recovered
                    self.dynamic_layout_required = True
                    self.log("reaction_open_hand_recovered", openMelds=recovered,
                             source="stable_compact_row_empty_draw_and_own_meld_surface")
        if open_melds:
            return self.recognize_resident(
                screenshot, concealed_only=True, dynamic_layout=True, open_melds=open_melds,
            )
        return self.recognize_resident(screenshot, concealed_only=True)

    def observe_public_board(self, screenshot: Path, *, reaction_highlight: bool = False) -> dict[str, Any] | None:
        server = getattr(self, "public_recognition_server", None)
        if self.args.mode == "force-auto" and server and server.poll() is None:
            self.public_recognition_request_id += 1
            started_at = time.monotonic()
            try:
                captured_at = datetime.fromtimestamp(screenshot.stat().st_mtime, timezone.utc).isoformat()
            except OSError:
                captured_at = None
            try:
                result = self.request_public_recognition({
                    "id": self.public_recognition_request_id,
                    "screenshot": str(screenshot),
                    "reactionHighlight": reaction_highlight,
                    "observationSeat": self.public_state.get("seat", "east"),
                    # Use the saved frame's time, not completion of an
                    # exchange that may wait behind an asynchronous scan.
                    **({"capturedAt": captured_at} if captured_at is not None else {}),
                })
                self.log("reaction_public_recognition", screenshot=str(screenshot),
                         latencyMs=round((time.monotonic() - started_at) * 1000),
                         source="resident", reactionHighlight=reaction_highlight)
                return result
            except Exception as error:
                self.log("public_observation_failed", error=str(error), source="resident")
                return None
        command = [
            "node", "dist/src/cli.js", "public-observation", str(screenshot),
            str(self.layout_path), str(self.templates), f"--seat={self.public_state.get('seat', 'east')}",
        ]
        if self.args.mode == "force-auto":
            command.append("--backend=hybrid")
        if reaction_highlight:
            command.append("--reaction-highlight")
        result = subprocess.run(command, cwd=self.root, env=self.evaluator_env, text=True,
                                encoding="utf-8", errors="strict",
                                capture_output=True, timeout=self.args.evaluation_timeout, check=False)
        if result.returncode != 0:
            self.log("public_observation_failed", error=(result.stderr or result.stdout).strip())
            return None
        return json.loads(result.stdout)

    @staticmethod
    def pending_highlighted_discard(observation, action, own_seat):
        if not observation or action not in {"chi", "pon", "kan"}:
            return None
        highlighted = observation.get("highlightedDiscard")
        if not isinstance(highlighted, dict):
            return None
        seats = ["east", "south", "west", "north"]
        seat, tile = highlighted.get("fromSeat"), highlighted.get("tile")
        if own_seat not in seats or seat not in seats or seat == own_seat:
            return None
        if action == "chi" and seat != seats[(seats.index(own_seat) + 3) % 4]:
            return None
        opponents = [item for item in observation.get("opponentDiscards", []) if item.get("seat") == seat]
        if len(opponents) != 1 or not opponents[0].get("discards") or opponents[0]["discards"][-1] != tile:
            return None
        return {"tile": tile, "fromSeat": seat}

    @staticmethod
    def infer_pending_discard(previous: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, str] | None:
        if not previous or not current:
            return None
        if previous.get("ownDiscards", []) != current.get("ownDiscards", []):
            return None
        previous_seats = [item.get("seat") for item in previous.get("opponentDiscards", [])]
        current_seats = [item.get("seat") for item in current.get("opponentDiscards", [])]
        if set(previous_seats) != set(current_seats) or len(set(current_seats)) != len(current_seats):
            return None
        additions = []
        for opponent in current.get("opponentDiscards", []):
            prior = next((item for item in previous.get("opponentDiscards", [])
                          if item.get("seat") == opponent.get("seat")), None)
            before = prior.get("discards", []) if prior else []
            after = opponent.get("discards", [])
            if after == before:
                continue
            if len(after) == len(before) + 1 and after[:-1] == before:
                additions.append({"tile": after[-1], "fromSeat": opponent["seat"]})
            else:
                return None
        return additions[0] if len(additions) == 1 else None

    def verify_post_discard(self, screenshot: bytes, before: list[str], click_index: int) -> dict[str, Any]:
        screenshot_path = self.frames / f"{utc_stamp()}.post-discard.png"
        screenshot_path.write_bytes(screenshot)
        command = [
            "node", "dist/src/cli.js", "verify-discard-frame", str(screenshot_path),
            str(self.layout_path), str(self.templates), f"--before={','.join(before)}",
            f"--click-index={click_index}",
        ]
        if self.args.mode == "force-auto":
            command.append("--force")
        result = subprocess.run(
            command,
            cwd=self.root,
            env=self.evaluator_env,
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            timeout=self.args.evaluation_timeout,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "post-discard verifier failed").strip())
        verification = json.loads(result.stdout)
        verification["screenshot"] = str(screenshot_path)
        return verification

    def confirm_discard(
        self,
        page: Page,
        hand_before: bytes,
        river_before: bytes,
        before_tiles: list[str],
        click_index: int,
    ) -> dict[str, Any]:
        started = time.monotonic()
        deadline = started + self.args.confirmation_timeout
        maximum_hand_delta = 0.0
        maximum_river_delta = 0.0
        terminal_transition = False
        while time.monotonic() < deadline:
            page.wait_for_timeout(100)
            if terminal_transition:
                full_screen = page.screenshot(animations="disabled")
                screen_state, screen_confidence = classify_screen(full_screen, self.screen_references)
                if screen_state == "round_result" and getattr(self, "layout", None) \
                        and round_result_conflicts_with_live_table(full_screen, self.layout):
                    screen_state, screen_confidence = "match", 1.0
                if screen_state in {"round_result", "match_result"}:
                    self.cached_concealed_tiles = None
                    return {
                        "confirmation": "discard_followed_by_terminal_result",
                        "confirmationLatencyMs": round((time.monotonic() - started) * 1000),
                        "handPixelDelta": maximum_hand_delta,
                        "riverPixelDelta": maximum_river_delta,
                        "terminalScreenState": screen_state,
                        "terminalScreenConfidence": screen_confidence,
                    }
                continue
            if getattr(self.args, "mode", None) == "force-auto":
                # CDP captures serialize behind Mahjong Soul's WebGL renderer.
                # Capture once and derive both evidence regions locally so the
                # confirmation loop cannot consume the next short-clock turn.
                full_after = page.screenshot(animations="disabled")
                hand_after = crop_screenshot(full_after, self.hand_clip)
                river_after = crop_screenshot(full_after, self.river_clip)
            else:
                full_after = None
                hand_after = page.screenshot(clip=self.hand_clip, animations="disabled")
                river_after = page.screenshot(clip=self.river_clip, animations="disabled")
            hand_delta = mean_pixel_delta(hand_before, hand_after)
            river_delta = mean_pixel_delta(river_before, river_after)
            maximum_hand_delta = max(maximum_hand_delta, hand_delta)
            maximum_river_delta = max(maximum_river_delta, river_delta)
            if hand_delta >= self.args.action_pixel_delta and river_delta >= self.args.river_pixel_delta:
                page.wait_for_timeout(200)
                if getattr(self.args, "mode", None) == "force-auto":
                    screenshot_path = self.frames / f"{utc_stamp()}.post-discard.png"
                    screenshot_path.write_bytes(full_after or page.screenshot(animations="disabled"))
                    return {
                        "confirmation": "hand_and_own_river_changed",
                        "confirmationLatencyMs": round((time.monotonic() - started) * 1000),
                        "handPixelDelta": hand_delta,
                        "riverPixelDelta": river_delta,
                        "screenshot": str(screenshot_path),
                    }
                verification = self.verify_post_discard(
                    page.screenshot(animations="disabled"), before_tiles, click_index,
                )
                if not verification.get("verified"):
                    # An exhaustive draw or win immediately reveals and moves
                    # every hand away from the configured concealed slots.
                    # Wait for the independently detected result summary, but
                    # keep every non-empty multiset mismatch fail-closed.
                    if verification.get("actual") == []:
                        terminal_transition = True
                        deadline = max(deadline, time.monotonic() + self.args.terminal_transition_timeout)
                        self.log("terminal_transition_wait", verification=verification)
                        continue
                    raise RuntimeError(f"post-discard tile multiset verification failed: {verification}")
                return {
                    "confirmation": "hand_and_own_river_changed",
                    "confirmationLatencyMs": round((time.monotonic() - started) * 1000),
                    "handPixelDelta": hand_delta,
                    "riverPixelDelta": river_delta,
                    "tileMultisetVerification": verification,
                }
        raise RuntimeError(
            "discard was not confirmed by both hand and own-river changes "
            f"(max hand delta={maximum_hand_delta:.3f}, max river delta={maximum_river_delta:.3f})"
        )

    def confirm_action_button(
        self, page: Page, action: str, before: bytes,
        hand_before: bytes | None = None, meld_before: bytes | None = None,
        region_override: dict[str, Any] | None = None,
        screen_before: bytes | None = None,
    ) -> dict[str, Any]:
        region = region_override or self.layout.get("actionButtonRegions", {}).get(action)
        if not region:
            raise RuntimeError(f"layout has no calibrated {action} button region")
        clip = {key: region[key] for key in ("x", "y", "width", "height")}
        expect_new_draw = action == "pass" and screen_before is not None and not self_turn_draw_visible(
            screen_before, self.layout, getattr(self, "cached_open_melds", 0))
        started = time.monotonic()
        while time.monotonic() - started < self.args.confirmation_timeout:
            page.wait_for_timeout(100)
            delta = mean_pixel_delta(before, page.screenshot(clip=clip, animations="disabled"))
            is_call = action in {"chi", "pon", "kan"}
            meld_region = self.layout.get("publicTileRegions", {}).get("ownMelds")
            if is_call and (hand_before is None or meld_before is None or not meld_region):
                raise RuntimeError(f"hand and own-meld evidence are required to verify {action}")
            hand_delta = mean_pixel_delta(hand_before, page.screenshot(clip=self.hand_clip, animations="disabled")) if is_call else 0
            meld_clip = {key: meld_region[key] for key in ("x", "y", "width", "height")} if meld_region else None
            meld_delta = mean_pixel_delta(meld_before, page.screenshot(clip=meld_clip, animations="disabled")) if is_call else 0
            call_confirmed = not is_call or (hand_delta >= self.args.action_pixel_delta and meld_delta >= self.args.action_pixel_delta)
            if delta >= self.args.action_pixel_delta and call_confirmed:
                return {
                    "confirmation": "action_button_hand_and_meld_changed" if is_call else "action_button_region_changed",
                    "confirmationLatencyMs": round((time.monotonic() - started) * 1000),
                    "buttonPixelDelta": delta,
                    **({"handPixelDelta": hand_delta, "meldPixelDelta": meld_delta} if is_call else {}),
                }
            if action == "riichi" and hand_before is not None:
                # The Riichi button sometimes remains painted in the same
                # region while the client switches to its discard-selection
                # UI.  Do not treat a changed hand alone as a receipt: a
                # late turn animation could cause that.  Require the known
                # dimmed selection signature and a still-live match screen.
                hand_after = page.screenshot(clip=self.hand_clip, animations="disabled")
                hand_delta = mean_pixel_delta(hand_before, hand_after)
                if hand_delta >= self.args.action_pixel_delta and riichi_selection_is_visible(hand_after):
                    full_after = page.screenshot(animations="disabled")
                    screen_state, screen_confidence = classify_screen(
                        full_after, getattr(self, "screen_references", {}),
                    )
                    if screen_state == "match":
                        return {
                            "confirmation": "riichi_selection_hand_changed",
                            "confirmationLatencyMs": round((time.monotonic() - started) * 1000),
                            "buttonPixelDelta": delta,
                            "handPixelDelta": hand_delta,
                            "screenState": screen_state,
                            "screenConfidence": screen_confidence,
                        }
            if expect_new_draw:
                full_after = page.screenshot(animations="disabled")
                if self_turn_draw_visible(
                    full_after, self.layout, getattr(self, "cached_open_melds", 0)
                ):
                    return {"confirmation": "reaction_to_self_draw",
                            "confirmationLatencyMs": round((time.monotonic() - started) * 1000),
                            "buttonPixelDelta": delta}
                # A second reaction prompt can replace the first one at the
                # same fixed button coordinates before this loop samples it.
                # Its pixels are then nearly identical, but a newly appended
                # river tile independently proves that the original prompt
                # has advanced (whether by our click or its timeout).
                public_regions = self.layout.get("publicTileRegions", {})
                river_deltas = {
                    name: mean_pixel_delta(
                        crop_screenshot(screen_before, region),
                        crop_screenshot(full_after, region),
                    )
                    for name, region in public_regions.items()
                    if name.endswith("Discards")
                }
                changed_river = next((
                    (name, river_delta) for name, river_delta in river_deltas.items()
                    if river_delta >= self.args.river_pixel_delta
                ), None)
                if changed_river:
                    return {
                        "confirmation": "reaction_river_advanced",
                        "confirmationLatencyMs": round((time.monotonic() - started) * 1000),
                        "buttonPixelDelta": delta,
                        "riverRegion": changed_river[0],
                        "riverPixelDelta": changed_river[1],
                    }
        raise RuntimeError(f"{action} click was not confirmed by its button region changing")

    def validate_action_certificate(self, action: str, evaluation: dict[str, Any]) -> dict[str, Any]:
        observed = evaluation.get("actionButton")
        if not observed or observed.get("action") != action or observed.get("present") is not True:
            raise RuntimeError(f"evaluated frame has no trusted {action} button")
        if observed.get("confidence", 0) < 0.98:
            raise RuntimeError(f"{action} button confidence is below threshold")
        certificate = self.layout.get("actionOperation", {}).get(action)
        if not certificate or certificate.get("enabled") is not True:
            raise RuntimeError(f"{action} click is forbidden without an action-specific calibration certificate")
        if certificate.get("templateSetFingerprint") != observed.get("templateSetFingerprint"):
            raise RuntimeError(f"{action} template set does not match its calibration certificate")
        return observed

    def verify_closed_hand_identity(
        self, page: Page, expected: list[str], evaluated_full: bytes, frame: bytes, generation: int,
    ) -> bool:
        """Prove a closed row still has the evaluated physical tile faces.

        Do not launch a new hybrid recognizer here.  It is a separate process
        operating on lossy screencast JPEG pixels and can disagree with the
        resident evaluation even when a glyph is unchanged.  Exact per-slot
        glyph structure is both cheaper and a more direct stale-frame guard.
        """
        if len(expected) != 14 or getattr(self, "cached_open_melds", 0) != 0:
            return False
        if self.screencast_draw_generation != generation:
            return False
        # Let queued screencast frames arrive, then prove identity against the
        # newest calibrated frame rather than an already superseded JPEG.
        page.wait_for_timeout(1)
        latest = getattr(self, "latest_screencast_frame", None) or frame
        path = self.frames / f"{utc_stamp()}.identity.jpg"
        path.write_bytes(latest)
        if is_away_resume_dialog(latest, self.layout["viewport"]):
            return False
        mismatches = closed_hand_face_mismatches(
            evaluated_full, latest, self.layout, self.args.stability_pixel_delta,
        )
        verified = not mismatches and self.screencast_draw_generation == generation \
            and self.screencast_draw_occupied is True
        if not verified and not mismatches:
            mismatches = [{"index": -1, "faceStructureDelta": None}]
        self.log("hand_identity_checked", screenshot=str(path), verified=verified,
                 verification="per_slot_glyph_structure",
                 expectedCount=len(expected), observedCount=len(expected),
                 mismatches=mismatches)
        return verified

    def execute(
        self, page: Page, evaluation: dict[str, Any], evaluated_hand: bytes | None = None,
        evaluated_full: bytes | None = None, evaluated_draw_generation: int | None = None,
        evaluated_captured_at: float | None = None,
    ) -> dict[str, Any]:
        decision = evaluation["decision"]
        recognition = evaluation["recognition"]
        selected = decision.get("selectedAction", {"action": decision.get("recommendedAction", "discard")})
        selected_action = selected.get("action")
        force_auto = self.args.mode == "force-auto"
        selection_local_budget = False
        certified_auto = self.args.mode == "auto" and decision.get("executable") is True
        local_auto = local_discard_allowed(self.args, evaluation)
        if not force_auto and not certified_auto and not local_auto:
            return {"clicked": False, "reason": "advisor_or_safety_stop"}
        established_riichi = bool((getattr(self, "cached_public_observation", None) or {}).get("riichiDeclared"))
        if selected_action in {"discard", "riichi"} and (evaluation.get("state", {}).get("riichiDeclared") or established_riichi):
            proposed_index = evaluation.get("clickIndex")
            proposed_point = evaluation.get("clickPoint")
            points = self.layout.get("clickPoints", [])
            if proposed_point is None and isinstance(proposed_index, int) and 0 <= proposed_index < len(points):
                proposed_point = points[proposed_index]
            require_post_riichi_draw_click(evaluation, selected, self.layout,
                                          proposed_index, proposed_point, established_riichi)
        if force_auto:
            self.require_force_auto_click_budget(
                evaluated_captured_at, phase="before_pre_click_validation",
            )
        # Certified Auto independently re-recognizes consensus frames.  In
        # force-auto, compare the current hand pixels with the stable hand
        # that produced the decision instead.  Re-running the template
        # recognizer twice costs roughly 35 seconds and can exhaust a 300s
        # clock, while this equality gate still rejects every stale decision.
        if not force_auto:
            for _ in range(self.args.consensus_frames - 1):
                page.wait_for_timeout(self.args.stability_ms)
                frame_path = self.frames / f"{utc_stamp()}.consensus.png"
                frame_path.write_bytes(page.screenshot(animations="disabled"))
                recognize_command = ["node", "dist/src/cli.js", "recognize", str(frame_path), str(self.layout_path), str(self.templates)]
                if evaluation.get("state", {}).get("phase") == "reaction":
                    recognize_command.append("--concealed-only")
                result = subprocess.run(
                    recognize_command,
                    cwd=self.root, env=self.evaluator_env, text=True,
                    encoding="utf-8", errors="strict", capture_output=True,
                    timeout=self.args.evaluation_timeout, check=False,
                )
                if result.returncode != 0:
                    raise RuntimeError("consensus recognition failed")
                fresh = json.loads(result.stdout)
                if not fresh.get("safe") or fresh.get("tiles") != recognition.get("tiles"):
                    raise RetryableSafetyAbort("fresh frame recognition disagrees with the evaluated hand")
        if not force_auto and (not recognition.get("safe") or recognition.get("confidence", 0) < self.layout.get("minimumTileConfidence", 0.98)):
            raise RuntimeError("Python recognition safety gate rejected click")
        if certified_auto:
            auto_certificate = self.layout.get("autoOperation")
            if not auto_certificate or auto_certificate.get("enabled") is not True:
                raise RuntimeError("layout has no passing Auto certificate")
        click_index = evaluation.get("clickIndex")
        dynamic_click_point = evaluation.get("clickPoint")
        points = self.layout["clickPoints"]
        if force_auto and selected_action == "discard" and selected_open_draw_is_ambiguous(evaluation):
            if verified_post_call_white_discard(
                evaluation, evaluated_full, self.layout, getattr(self, "cached_open_melds", 0),
                getattr(self, "pending_post_call_discard", False),
            ):
                self.log("post_call_white_discard_verified", tile="P", clickIndex=click_index,
                         verification="complete_compact_row_blank_ivory_face_and_felt_boundary")
            else:
                fallback = ambiguous_open_draw_fallback(evaluation)
                if fallback is None:
                    raise RetryableSafetyAbort("ambiguous independent draw-slot tile has no recognized fallback")
                fallback_tile, click_index = fallback
                selected = {"action": "discard", "tile": fallback_tile}
                dynamic_click_point = points[click_index]
                self.log("ambiguous_open_draw_fallback", rejectedTile=decision.get("selectedAction", {}).get("tile"),
                         fallbackTile=fallback_tile, fallbackClickIndex=click_index)
        needs_tile_click = selected_action in {"discard", "riichi"}
        has_dynamic_click_point = (
            isinstance(dynamic_click_point, dict)
            and isinstance(dynamic_click_point.get("x"), (int, float))
            and isinstance(dynamic_click_point.get("y"), (int, float))
        )
        if needs_tile_click and not has_dynamic_click_point and (
            not isinstance(click_index, int) or click_index < 0 or click_index >= len(points)
        ):
            raise RuntimeError("evaluator returned an invalid click index")

        # Evaluation can take long enough for Mahjong Soul to show its away
        # dialog. Re-check the full viewport immediately before touching a
        # hand coordinate; resume only, then discard this stale decision.
        screencast_session = getattr(self, "screencast_session", None)
        if force_auto and screencast_session is not None:
            # Dispatch frames queued while the resident recognizer was busy.
            page.wait_for_timeout(1)
        current_streamed_full = getattr(self, "latest_screencast_frame", None) \
            if force_auto and screencast_session is not None else None
        # Compare every pre-click region against the same immutable frame.
        # Decoding a 1920x1080 screencast separately for the hand, stable
        # faces and river costs several hundred milliseconds on the ranked
        # path but produces no extra state evidence.
        pre_click_full = current_streamed_full or page.screenshot(animations="disabled")
        if is_away_resume_dialog(pre_click_full, self.layout["viewport"]):
            self.resume_if_away(page, pre_click_full)
            raise RetryableSafetyAbort("decision canceled because away dialog appeared during evaluation")
        trusted_open_melds = getattr(self, "cached_open_melds", 0)
        stable_region = stable_hand_comparison_region(self.layout, trusted_open_melds)
        selected_region = None
        same_draw_generation = bool(
            evaluated_draw_generation is not None
            and getattr(self, "screencast_draw_generation", None) == evaluated_draw_generation
        )
        if (
            same_draw_generation
            and trusted_open_melds > 0
            and needs_tile_click
            and has_dynamic_click_point
            and evaluated_full is not None
            and current_streamed_full is not None
        ):
            selected_region = selected_tile_comparison_region(
                self.layout, dynamic_click_point, trusted_open_melds,
            )
        pre_click_regions = {"hand": self.hand_clip}
        # Some focused safety tests construct only the hand guard because
        # they must abort before discard confirmation.  Production operators
        # always have ``river_clip`` from their calibrated layout.
        if hasattr(self, "river_clip"):
            pre_click_regions["river"] = self.river_clip
        if stable_region is not None:
            pre_click_regions["stable"] = stable_region
        if selected_region is not None:
            pre_click_regions["selected"] = selected_region
        pre_click_crops = crop_screenshot_regions(pre_click_full, pre_click_regions)
        current_streamed_hand = pre_click_crops["hand"] if current_streamed_full is not None else None
        if evaluated_full is not None and stable_region is not None:
            evaluated_regions = {"stable": stable_region}
            if selected_region is not None:
                evaluated_regions["selected"] = selected_region
            evaluated_crops = crop_screenshot_regions(evaluated_full, evaluated_regions)
            focused_evaluated_hand = evaluated_crops["stable"]
        else:
            evaluated_crops = {}
            focused_evaluated_hand = evaluated_hand
        focused_streamed_hand = pre_click_crops.get("stable", current_streamed_hand)
        streamed_delta = stable_hand_delta(
            focused_evaluated_hand, focused_streamed_hand, trusted_open_melds,
        ) \
            if focused_evaluated_hand is not None and focused_streamed_hand is not None else None
        selected_tile_delta = None
        if selected_region is not None:
            selected_tile_delta = stable_hand_delta(
                evaluated_crops["selected"], pre_click_crops["selected"], trusted_open_melds,
            )
        streamed_turn_is_current = bool(
            same_draw_generation
            and streamed_delta is not None
            and (
                streamed_delta <= self.args.stability_pixel_delta
                or selected_tile_delta is not None
                and selected_tile_delta <= self.args.stability_pixel_delta
            )
        )
        if force_auto and needs_tile_click and self.refresh_discard_reconciliation_before_click():
            raise RetryableSafetyAbort("own discard reconciliation candidate arrived during evaluation")

        hand_before = current_streamed_hand or pre_click_crops["hand"]
        if force_auto:
            if evaluated_hand is None:
                raise RuntimeError("force-auto requires the stable evaluated hand image")
            if not streamed_turn_is_current:
                focused_hand_before = pre_click_crops.get("stable", hand_before)
                evaluated_delta = stable_hand_delta(
                    focused_evaluated_hand, focused_hand_before, trusted_open_melds,
                )
                if evaluated_delta > self.args.stability_pixel_delta:
                    identity_verified = same_draw_generation and trusted_open_melds == 0 \
                        and selected_action in {"discard", "riichi"} \
                        and self.verify_closed_hand_identity(
                            page, recognition.get("tiles", []), evaluated_full, pre_click_full,
                            evaluated_draw_generation,
                        )
                    if not identity_verified:
                        raise RetryableSafetyAbort(
                            f"hand changed since evaluation (pixel delta={evaluated_delta:.3f})"
                        )
        river_before = pre_click_crops.get("river") or crop_screenshot(pre_click_full, self.river_clip)
        if not (force_auto and screencast_session is not None):
            page.wait_for_timeout(120)
            stability_delta = mean_pixel_delta(hand_before, page.screenshot(clip=self.hand_clip, animations="disabled"))
            if stability_delta > self.args.stability_pixel_delta:
                raise RetryableSafetyAbort("hand changed during Python pre-click stability check")
        if selected_action != "discard":
            button_action = "kan" if selected_action in {"minkan", "ankan", "kakan"} else selected_action
            observed = evaluation.get("actionButton") if force_auto else self.validate_action_certificate(button_action, evaluation)
            if not observed or observed.get("action") != button_action:
                raise RuntimeError(f"evaluated frame has no {button_action} button candidate")
            region = observed if force_auto else self.layout["actionButtonRegions"][button_action]
            button_clip = {key: region[key] for key in ("x", "y", "width", "height")}
            # Reuse two temporally distinct stream observations only when
            # their hand/draw guard passed. Undated or reused frames retain
            # the synchronous 120ms stability check.
            streamed_captured_at = getattr(self, "latest_screencast_captured_at", None)
            stream_button_guard = bool(
                force_auto and streamed_turn_is_current
                and evaluated_full is not None and current_streamed_full is not None
                and evaluated_captured_at is not None and streamed_captured_at is not None
                and streamed_captured_at - evaluated_captured_at >= 0.120
            )
            button_before = crop_screenshot(evaluated_full, button_clip) if stream_button_guard \
                else page.screenshot(clip=button_clip, animations="disabled")
            meld_region = self.layout.get("publicTileRegions", {}).get("ownMelds")
            meld_clip = {key: meld_region[key] for key in ("x", "y", "width", "height")} if meld_region else None
            meld_before = None
            if button_action in {"chi", "pon", "kan"} and meld_clip:
                meld_before = crop_screenshot(pre_click_full, meld_clip) if stream_button_guard \
                    else page.screenshot(clip=meld_clip, animations="disabled")
            if stream_button_guard:
                button_current = crop_screenshot(pre_click_full, button_clip)
            else:
                page.wait_for_timeout(120)
                button_current = page.screenshot(clip=button_clip, animations="disabled")
            if mean_pixel_delta(button_before, button_current) > self.args.stability_pixel_delta:
                # Riichi and tsumo affordances can legitimately disappear
                # while their turn UI is being animated. Nothing has been
                # clicked yet, so retry from a fresh self-turn frame rather
                # than abandoning the whole live table (which triggers
                # auto-tsumogiri).
                if selected_action in {"riichi", "tsumo"}:
                    raise RetryableSafetyAbort(
                        f"{button_action} button changed during pre-click stability check"
                    )
                raise RuntimeError(f"{button_action} button changed during pre-click stability check")
            point = observed["center"]
            if force_auto:
                self.require_force_auto_click_budget(
                    evaluated_captured_at, phase="before_action_button_click",
                )
            self.require_action_deadline()
            self.log("action_click_sent", action=button_action, clickPoint=point)
            self.last_action_clicked_at = time.monotonic()
            page.mouse.click(point["x"], point["y"])
            riichi_stage_started = time.monotonic() if selected_action == "riichi" else None
            action_receipt = self.confirm_action_button(
                page, button_action, button_before, hand_before, meld_before,
                region_override=region if force_auto else None,
            )
            if selected_action != "riichi":
                if button_action in {"tsumo", "ron"}:
                    self.start_self_win_capture(button_action)
                    self.round_terminal_latched = True
                    self.round_terminal_result_observed = False
                return {"clicked": True, "policy": "certified_auto", "action": selected_action,
                        "clickPoint": point, **action_receipt}
            self.log("riichi_stage_timing", stage="action_confirmation",
                     durationMs=round((time.monotonic() - riichi_stage_started) * 1000))
            # A successful Riichi declaration enters a dimmed tile-selection
            # state before the actual discard.  Establish a new baseline so
            # its visual transition cannot be mistaken for confirmation of
            # the following tile click.
            riichi_stage_started = time.monotonic()
            post_riichi_full = page.screenshot(animations="disabled")
            post_riichi_captured_at = time.monotonic()
            self.log("riichi_stage_timing", stage="post_selection_capture",
                     durationMs=round((post_riichi_captured_at - riichi_stage_started) * 1000))
            riichi_stage_started = time.monotonic()
            post_riichi_hand = crop_screenshot(post_riichi_full, self.hand_clip)
            post_riichi_state, _ = classify_screen(
                post_riichi_full, getattr(self, "screen_references", {}),
            )
            self.log("riichi_stage_timing", stage="post_selection_classification",
                     durationMs=round((time.monotonic() - riichi_stage_started) * 1000))
            if post_riichi_state != "match" or not riichi_selection_is_visible(post_riichi_hand):
                raise RetryableSafetyAbort("riichi selection state disappeared before discard click")
            post_riichi_target = riichi_selection_target_region(
                self.layout, click_index,
                dynamic_click_point if has_dynamic_click_point else points[click_index],
            )
            if post_riichi_target is None:
                raise RetryableSafetyAbort("riichi selection target is outside its physical hand slot")
            # Confirmation only establishes that the selection UI appeared;
            # it does not establish that its settling animation retained the
            # evaluator's target slot.  Take a second, temporally separate
            # selection receipt and compare the exact chosen tile face before
            # issuing the discard click.  This specifically prevents a
            # pre-Riichi coordinate from selecting a neighbouring tile after
            # the dimmed row has relaid out.
            riichi_stage_started = time.monotonic()
            page.wait_for_timeout(120)
            self.log("riichi_stage_timing", stage="selection_settle_wait",
                     durationMs=round((time.monotonic() - riichi_stage_started) * 1000))
            riichi_stage_started = time.monotonic()
            settled_riichi_full = page.screenshot(animations="disabled")
            settled_riichi_captured_at = time.monotonic()
            self.log("riichi_stage_timing", stage="settled_selection_capture",
                     durationMs=round((settled_riichi_captured_at - riichi_stage_started) * 1000))
            riichi_stage_started = time.monotonic()
            settled_riichi_hand = crop_screenshot(settled_riichi_full, self.hand_clip)
            settled_riichi_state, _ = classify_screen(
                settled_riichi_full, getattr(self, "screen_references", {}),
            )
            self.log("riichi_stage_timing", stage="settled_selection_classification",
                     durationMs=round((time.monotonic() - riichi_stage_started) * 1000))
            if (settled_riichi_state != "match"
                    or not riichi_selection_is_visible(settled_riichi_hand)):
                raise RetryableSafetyAbort("riichi selection state changed while settling before discard click")
            target_before = crop_screenshot(post_riichi_full, post_riichi_target)
            target_settled = crop_screenshot(settled_riichi_full, post_riichi_target)
            target_delta = stable_hand_delta(target_before, target_settled, 0)
            if target_delta > self.args.stability_pixel_delta:
                evidence_stamp = utc_stamp()
                before_path = self.frames / f"{evidence_stamp}.riichi-settle-before.png"
                settled_path = self.frames / f"{evidence_stamp}.riichi-settle-after.png"
                before_path.write_bytes(post_riichi_full)
                settled_path.write_bytes(settled_riichi_full)
                before_path.chmod(0o600)
                settled_path.chmod(0o600)
                self.log("riichi_settle_mismatch_evidence", before=str(before_path),
                         after=str(settled_path), target=post_riichi_target,
                         pixelDelta=target_delta)
                raise RetryableSafetyAbort(
                    f"riichi selection target changed while settling (pixel delta={target_delta:.3f})"
                )
            # The declaration was confirmed and this full viewport was then
            # captured specifically to verify the dimmed discard-selection
            # UI.  That observation is the safety boundary for the second
            # (tile) click: retaining the pre-declaration evaluator receipt
            # would reject an otherwise current selection after its own
            # confirmation/classification work.  Do not do this for an
            # unconfirmed declaration or any other action path.
            if force_auto:
                selection_local_budget = (
                    not getattr(self.args, "ranked_loop", False)
                    and self.force_auto_click_budget_ms() is not None
                    and self.force_auto_click_budget_ms() > FORCE_AUTO_SHORT_CLICK_BUDGET_MAX_MS
                )
                evaluated_captured_at = (settled_riichi_captured_at if selection_local_budget
                                         else post_riichi_captured_at)
                if selection_local_budget:
                    self.log("riichi_selection_local_budget_started",
                             clickBudgetMs=self.force_auto_click_budget_ms(),
                             targetPixelDelta=round(target_delta, 3))
            hand_before = settled_riichi_hand
            river_before = crop_screenshot(settled_riichi_full, self.river_clip)
            # The lift receipt must be compared to the same confirmed
            # selection UI. The pre-declaration stream frame has different
            # tile illumination and cannot prove this physical face moved.
            pre_click_full = settled_riichi_full

        point = dynamic_click_point if has_dynamic_click_point else points[click_index]
        require_post_riichi_draw_click(evaluation, selected, self.layout,
                                      click_index, point, established_riichi)
        if force_auto and needs_tile_click:
            trusted_open_melds = getattr(self, "cached_open_melds", 0)
            evaluated_open_melds = evaluation.get("openMelds", 0)
            if trusted_open_melds > 0 and evaluated_open_melds != trusted_open_melds:
                # The generic live-layout proposal can collapse the compact
                # concealed row to two tiles and consequently infer four open
                # melds.  A call observed by this operator is stronger
                # evidence, but only anchor to it when recognition still
                # explains the *complete* compact self-turn row.  Thus a real
                # geometry/count change remains fail-closed.
                expected_concealed = 14 - trusted_open_melds * 3
                recognized_concealed = len(recognition.get("tiles", []))
                if recognized_concealed != expected_concealed:
                    raise RetryableSafetyAbort(
                        "evaluated hand geometry does not match confirmed open meld count "
                        f"{trusted_open_melds}: expected {expected_concealed} concealed tiles, "
                        f"recognized {recognized_concealed}"
                    )
                self.log(
                    "open_meld_revalidation_anchored",
                    confirmedOpenMelds=trusted_open_melds,
                    rejectedInferredOpenMelds=evaluated_open_melds,
                    recognizedConcealedTiles=recognized_concealed,
                )
            if not discard_point_in_hand_geometry(point, self.layout, trusted_open_melds):
                raise RetryableSafetyAbort(
                    f"discard click point is outside current hand geometry: {point}"
                )
        clicked_at = datetime.now(timezone.utc).isoformat()
        if force_auto:
            self.require_force_auto_click_budget(
                evaluated_captured_at, phase="before_discard_click",
                **({"include_action_evidence": False} if selection_local_budget else {}),
            )
            self.require_force_auto_discard_selection_window(evaluated_captured_at)
        self.require_action_deadline()
        self.log(
            "click_sent",
            policy="force_auto" if force_auto else "certified_auto" if certified_auto else "local_discard_only",
            tile=selected.get("tile", decision.get("tile")),
            clickIndex=click_index,
            clickPoint=point,
        )
        self.last_action_clicked_at = time.monotonic()
        selection_sequence_before = getattr(self, "screencast_sequence", None)

        selection_confirmation = send_discard_click(
            page.mouse,
            point,
            self.layout["viewport"],
            lambda milliseconds: page.wait_for_timeout(milliseconds),
            pre_click_full,
            lambda first_click_at: self.fresh_screencast_selection_receipt(
                selection_sequence_before, first_click_at,
            ),
            self.layout,
            click_index,
            self.args.stability_pixel_delta,
            (lambda: self.require_force_auto_click_budget(
                evaluated_captured_at, phase="before_discard_confirmation_click",
                **({"include_action_evidence": False} if selection_local_budget else {}),
            )) if force_auto else None,
            self.record_unverified_selection if force_auto else None,
        )
        if force_auto:
            # ``send_discard_click`` ends by moving onto inert table felt.
            # Do not reuse an already queued screencast frame: only a later
            # receipt can prove the next recognition crop has no raised tile.
            self.pointer_retreat_screencast_sequence = getattr(self, "screencast_sequence", None)
        receipt = self.confirm_discard(page, hand_before, river_before, recognition["tiles"], click_index)
        return {
            "clicked": True,
            "policy": "force_auto" if force_auto else "certified_auto" if certified_auto else "local_discard_only",
            # The physical discard can differ from the evaluator's selection
            # when an ambiguous independent draw slot is replaced with a
            # compact-row fallback.  Later reconciliation must use this one.
            "discardedTile": selected.get("tile") if selected_action in {"discard", "riichi"} else None,
            "clickIndex": click_index,
            "clickPoint": point,
            "selectionConfirmation": selection_confirmation,
            "clickedAt": clicked_at,
            **({"declaration": action_receipt} if selected_action == "riichi" else {}),
            **receipt,
        }

    def execute_reaction_pass(
        self, page: Page, evaluation: dict[str, Any], *,
        evaluated_captured_at: float | None = None,
    ) -> dict[str, Any]:
        """Dismiss any reaction prompt without guessing its discarded tile.

        The Python path does not yet construct a trusted pendingDiscard, so it
        must never choose among chi/pon/kan/ron candidates.  A certified pass
        is valid for every such prompt and prevents the match from timing out.
        """
        if self.args.mode not in {"auto", "force-auto"}:
            return {"clicked": False, "reason": "advisor_or_observer_reaction_prompt"}
        recognition = evaluation.get("recognition", {})
        if self.args.mode != "force-auto" and (not recognition.get("safe") or len(recognition.get("tiles", [])) != 13):
            raise RuntimeError("reaction prompt does not have a safe 13-tile concealed hand")
        observed = evaluation.get("actionButton") if self.args.mode == "force-auto" else self.validate_action_certificate("pass", evaluation)
        if not observed or observed.get("action") != "pass":
            raise RuntimeError("evaluated frame has no pass button candidate")
        region = self.layout["actionButtonRegions"]["pass"]
        button_clip = {key: region[key] for key in ("x", "y", "width", "height")}
        reaction_frame = evaluation.get("reactionFrame")
        evaluated_full = Path(reaction_frame).read_bytes() if reaction_frame else None
        if self.args.mode == "force-auto" and getattr(self, "screencast_session", None) is not None:
            page.wait_for_timeout(1)  # Drain queued screencast events after recognition.
        current_full = getattr(self, "latest_screencast_frame", None)
        current_at = getattr(self, "latest_screencast_captured_at", None)
        stream_guard = bool(
            self.args.mode == "force-auto"
            and getattr(self, "screencast_session", None) is not None
            and evaluated_full is not None and current_full is not None
            and evaluated_captured_at is not None and current_at is not None
            and current_at - evaluated_captured_at >= 0.120
            and 0 <= time.monotonic() - current_at <= 0.250
        )
        riichi_kan_pass = observed.get("source") == "force_auto_riichi_kan_pass"
        if riichi_kan_pass:
            # Revalidate the complete prompt twice. A stable skip-shaped clip
            # alone cannot prove that a newer tsumo opportunity is absent.
            first_full = page.screenshot(animations="disabled")
            page.wait_for_timeout(120)
            second_full = page.screenshot(animations="disabled")
            if (evaluated_full is None
                    or force_auto_riichi_kan_prompt(first_full, self.layout["viewport"], region) is None
                    or force_auto_riichi_kan_prompt(second_full, self.layout["viewport"], region) is None
                    or closed_hand_face_mismatches(evaluated_full, second_full, self.layout,
                                                   self.args.stability_pixel_delta)):
                raise RetryableSafetyAbort("riichi kan/skip prompt or concealed hand changed before pass")
            before = crop_screenshot(first_full, button_clip)
            confirmed = crop_screenshot(second_full, button_clip)
            stream_guard = False
        elif stream_guard:
            before = crop_screenshot(evaluated_full, button_clip)
            confirmed = crop_screenshot(current_full, button_clip)
            def verified_pass(frame, clip):
                if is_force_auto_pass_clip(clip):
                    return True
                viewport = self.layout.get("viewport")
                return bool(viewport and is_contextual_reaction_pass(
                    frame, region, len(force_auto_call_buttons(frame, viewport)),
                ))
            # Verify the affordance in both frames, including the stylized
            # skip variant only when a green call button is independently found.
            stream_guard = verified_pass(evaluated_full, before) and verified_pass(current_full, confirmed)
        if not stream_guard and not riichi_kan_pass:
            before = page.screenshot(clip=button_clip, animations="disabled")
            page.wait_for_timeout(120)
            confirmed = page.screenshot(clip=button_clip, animations="disabled")
        if mean_pixel_delta(before, confirmed) > self.args.stability_pixel_delta:
            # A reaction prompt can be withdrawn while its button is being
            # animated (for example when another player has already acted).
            # No mouse event has been sent at this point.  Do not treat that
            # benign UI transition as a terminal operator failure: return to
            # the turn gate, which captures a fresh full frame and verifies
            # the current hand/river before deciding whether a prompt remains.
            raise RetryableSafetyAbort(
                "pass button changed during pre-click stability check; reobserve reaction state"
            )
        # The evaluated full-table frame may be old after recognition.  Pass
        # is exceptional: unlike calls and ron, it cannot select a tile or a
        # reaction option, and the fixed pass affordance has just been
        # observed unchanged twice.  Anchor its short ranked budget to that
        # independent, current UI confirmation rather than to the stale
        # evaluator frame.  Calls and ron deliberately retain their strict
        # evaluated-frame budget checks.
        pass_confirmed_at = current_at if stream_guard else time.monotonic()
        point = observed["center"]
        if self.args.mode == "force-auto":
            self.require_force_auto_click_budget(
                pass_confirmed_at, phase="before_reaction_pass_click",
                include_action_evidence=False,
            )
        self.require_action_deadline()
        self.log("action_click_sent", action="pass", clickPoint=point,
                 availableUiActions=evaluation.get("availableUiActions", []))
        self.last_action_clicked_at = time.monotonic()
        page.mouse.click(point["x"], point["y"])
        reaction_frame = evaluation.get("reactionFrame")
        receipt = self.confirm_action_button(page, "pass", before,
                                            screen_before=Path(reaction_frame).read_bytes() if reaction_frame else None)
        return {"clicked": True, "policy": "force_auto" if self.args.mode == "force-auto" else "certified_auto", "action": "pass",
                "clickPoint": point, **receipt}

    def execute_force_auto_call(
        self, page: Page, screenshot: bytes, button: dict[str, Any],
        selected_action: dict[str, Any] | None = None,
        legal_actions: list[dict[str, Any]] | None = None,
        *, evaluated_captured_at: float | None = None,
    ) -> dict[str, Any]:
        """Accept one unambiguous green call and arm the compact-hand discard."""
        if self.args.mode != "force-auto" or not getattr(self.args, "accept_single_call", False):
            return {"clicked": False, "reason": "single_call_not_enabled"}
        buttons = force_auto_call_buttons(screenshot, self.layout["viewport"])
        if len(buttons) != 1:
            raise RetryableSafetyAbort(f"expected one stable call button, found {len(buttons)}")
        if abs(buttons[0]["center"]["x"] - button["center"]["x"]) > 12:
            raise RetryableSafetyAbort("call button moved before click")
        call_action = buttons[0].get("action")
        if call_action not in {"chi", "pon", "minkan"}:
            raise RetryableSafetyAbort(f"unclassified call button: {call_action}")
        point = buttons[0]["center"]
        hand_before = crop_screenshot(screenshot, self.hand_clip)
        meld_region = self.layout.get("publicTileRegions", {}).get("ownMelds")
        meld_before = crop_screenshot(screenshot, meld_region) if meld_region else None
        self.require_force_auto_click_budget(
            evaluated_captured_at, phase="before_reaction_call_click",
        )
        self.require_action_deadline()
        self.log("action_click_sent", action=call_action, clickPoint=point, source="single_call_button")
        sequence_before = self.screencast_sequence
        self.last_action_clicked_at = time.monotonic()
        page.mouse.click(point["x"], point["y"])
        deadline = time.monotonic() + min(3.0, self.args.confirmation_timeout)
        current = screenshot
        chi_choice_sent = False
        while time.monotonic() < deadline:
            page.wait_for_timeout(50)
            if self.screencast_sequence != sequence_before and self.latest_screencast_frame is not None:
                current = self.latest_screencast_frame
                sequence_before = self.screencast_sequence
            else:
                current = page.screenshot(animations="disabled")
            if call_action == "chi" and not chi_choice_sent:
                choices = force_auto_chi_choice_points(current, self.layout["viewport"])
                if choices:
                    choice = selected_chi_choice_point(choices, selected_action, legal_actions)
                    if choice is None:
                        raise RetryableSafetyAbort("chi choice variants did not match the selected legal action")
                    self.log("action_click_sent", action="chi_choice", clickPoint=choice,
                             choiceCount=len(choices), source="complete_two_tile_choice")
                    page.mouse.click(choice["x"], choice["y"])
                    chi_choice_sent = True
                    sequence_before = self.screencast_sequence
                    continue
            hand_delta = mean_pixel_delta(hand_before, crop_screenshot(current, self.hand_clip))
            meld_delta = mean_pixel_delta(meld_before, crop_screenshot(current, meld_region)) \
                if meld_before is not None and meld_region else 0
            if hand_delta >= self.args.action_pixel_delta \
                    and (not meld_region or meld_delta >= self.args.action_pixel_delta):
                transition = post_call_transition(call_action, self.cached_open_melds)
                self.cached_concealed_tiles = None
                self.cached_open_melds = transition["openMelds"]
                self.dynamic_layout_required = transition["dynamicLayoutRequired"]
                self.pending_post_call_discard = transition["pendingPostCallDiscard"]
                self.pending_post_call_started_at = time.monotonic() \
                    if self.pending_post_call_discard else None
                self.post_call_timeout_recovery = None
                public = getattr(self, "cached_public_observation", None) or {}
                public_captured = public_capture_seconds(public.get("capturedAt"))
                baseline = public.get("ownDiscards")
                candidate = getattr(self, "pending_own_river_confirmation", None)
                pending = getattr(self, "pending_own_discard", None)
                if (isinstance(baseline, list) and isinstance(candidate, list)
                        and len(candidate) == len(baseline) + 1
                        and candidate[:len(baseline)] == baseline
                        and pending and candidate[-1] == pending.get("tile")):
                    baseline = candidate
                elif pending:
                    # A previous own discard still in flight could otherwise
                    # look like the post-call timeout's new river tile.
                    baseline = None
                if (self.pending_post_call_discard and public.get("ownDiscardsObserved") is True
                        and isinstance(baseline, list) and public_captured is not None
                        and 0 <= time.time() - public_captured <= 3):
                    self.post_call_timeout_recovery = {
                        "baseline": list(baseline), "after": time.time(),
                        "startedMonotonic": self.pending_post_call_started_at,
                        "openMelds": self.cached_open_melds,
                    }
                self.closed_new_round_candidate_frames = set()
                self.last_processed_hand = None
                self.armed = True
                return {
                    "clicked": True, "policy": "force_auto", "action": call_action,
                    "clickPoint": point, "confirmation": "hand_and_own_meld_changed",
                    "handPixelDelta": hand_delta, "meldPixelDelta": meld_delta,
                    "openMelds": self.cached_open_melds,
                    "pendingPostCallDiscard": self.pending_post_call_discard,
                    "nextAction": "discard" if self.pending_post_call_discard else "rinshan_draw",
                }
        raise RetryableSafetyAbort("hand and own meld did not change after call click")

    def execute_force_auto_reaction_win(
        self, page: Page, screenshot: bytes, button: dict[str, Any],
        *, evaluated_captured_at: float | None = None,
    ) -> dict[str, Any]:
        """Accept an unambiguous ron button and verify that the prompt closes."""
        if self.args.mode != "force-auto":
            return {"clicked": False, "reason": "force_auto_only"}
        pass_region = self.layout.get("actionButtonRegions", {}).get("pass")
        current = force_auto_reaction_win_button(screenshot, self.layout["viewport"], pass_region)
        if current is None and button.get("source") == "contextual_reaction_prompt":
            contextual = force_auto_self_action_buttons(screenshot, self.layout["viewport"])
            current = contextual[0] if len(contextual) == 1 else None
        if not current:
            raise RetryableSafetyAbort("reaction win button was not stable before click")
        point = current["center"]
        self.require_force_auto_click_budget(
            evaluated_captured_at, phase="before_reaction_win_click",
        )
        self.require_action_deadline()
        self.log("action_click_sent", action="ron", clickPoint=point, source="reaction_win_color")
        self.last_action_clicked_at = time.monotonic()
        page.mouse.click(point["x"], point["y"])
        deadline = time.monotonic() + min(3.0, self.args.confirmation_timeout)
        while time.monotonic() < deadline:
            page.wait_for_timeout(50)
            after = page.screenshot(animations="disabled")
            if not force_auto_reaction_win_button(after, self.layout["viewport"], pass_region):
                self.last_processed_hand = None
                self.armed = True
                self.pending_post_call_discard = False
                self.pending_post_call_started_at = None
                self.round_terminal_latched = True
                self.round_terminal_result_observed = False
                self.start_self_win_capture("ron")
                return {
                    "clicked": True, "policy": "force_auto", "action": "ron",
                    "clickPoint": point, "confirmation": "reaction_win_button_disappeared",
                }
        raise RetryableSafetyAbort("reaction win button did not disappear after click")

    def warm_reviewed_friend_board_ocr(self) -> bool:
        """Initialize OCR only within the explicitly reviewed friend-start flow."""
        if not getattr(self.args, "board_metadata", False) \
                or not getattr(self.args, "start_reviewed_friend_room", None) \
                or getattr(self.args, "ranked_loop", False) \
                or self.args.mode != "force-auto":
            return False
        from board_metadata import ocr_engine
        with self.board_metadata_ocr_lock:
            ocr_engine()
        return True

    def bound_initial_action_from_dealing(self, page: Page, guard: StartupTurnGuard,
                                          gate_frame: bytes | None) -> bool:
        """Use a fresh direct capture, never a late screencast receipt, as a bound."""
        if (guard.ready or guard.quarantined or guard.start_click_at is None
                or not gate_frame or not initial_dealing_frame_visible(gate_frame, self.layout)):
            return False
        self.log("initial_action_dealing_candidate", source="verified_match_stream")
        request_started_at = time.monotonic()
        try:
            session = self.screencast_session
            if session is None:
                raise RuntimeError("screencast session unavailable")
            capture = session.send("Page.captureScreenshot", {
                "format": "jpeg", "quality": 50, "fromSurface": True,
            })
            frame = base64.b64decode(capture["data"], validate=True)
            observed_at = time.monotonic()
            duration_ms = round((observed_at - request_started_at) * 1000)
            self.log("initial_action_dealing_capture", screenshotDurationMs=duration_ms,
                     source="cdp_jpeg")
            state, _ = classify_screen(frame, self.screen_references)
            if state != "match":
                self.log("initial_action_dealing_rejected", reason="capture_not_match",
                         screenState=state, screenshotDurationMs=duration_ms)
                return False
            if not initial_dealing_frame_visible(frame, self.layout):
                self.log("initial_action_dealing_rejected", reason="capture_not_dealing",
                         screenshotDurationMs=duration_ms)
                return False
            pass_region = self.layout.get("actionButtonRegions", {}).get("pass")
            if ((pass_region and is_force_auto_pass_clip(crop_screenshot(frame, pass_region)))
                    or force_auto_call_buttons(frame, self.layout["viewport"])
                    or force_auto_self_action_buttons(frame, self.layout["viewport"])):
                self.log("initial_action_dealing_rejected", reason="action_button_visible",
                         screenshotDurationMs=duration_ms)
                return False
            if not guard.record_verified_dealing_bound(
                    request_started_at=request_started_at, observed_at=observed_at):
                self.log("initial_action_dealing_rejected", reason="start_guard_rejected",
                         screenshotDurationMs=duration_ms)
                return False
        except Exception as error:
            self.log("initial_action_dealing_rejected", reason="capture_or_validation_failed",
                     error=str(error))
            return False
        self.log("initial_action_dealing_bound", source="direct_screenshot_request_started",
                 screenshotDurationMs=duration_ms)
        return True

    def run(self, page: Page) -> None:
        self.ensure_viewport(page, force=True)
        startup_turn_guard = StartupTurnGuard()
        long_friend_initial_clock = False
        preflight_path = getattr(self.args, "start_reviewed_friend_room", None)
        if preflight_path:
            if self.args.mode != "force-auto" or getattr(self.args, "ranked_loop", False):
                raise RuntimeError("reviewed friend start requires non-ranked force-auto")
            reviewed = Path(preflight_path).read_bytes()
            long_friend_initial_clock = (
                self.configured_action_deadline_ms() == 300000
                and self.force_auto_click_budget_ms() == 8000
                and reviewed_friend_clock_is_300_plus_zero(reviewed)
            )
            def save_friend_start_capture(index: int, frame: bytes, matched: bool) -> None:
                path = self.frames / f"{utc_stamp()}.friend-start-{index}.png"
                path.write_bytes(frame)
                self.log("friend_start_capture", screenshot=str(path),
                         capture=index, matched=matched)

            # Transient animated particles can interrupt otherwise matching
            # room frames. More attempts do not weaken the two consecutive
            # complete matches required before the start click.
            captures = await_reviewed_friend_room(page, reviewed, attempts=32,
                                                   on_capture=save_friend_start_capture)
            if self.warm_reviewed_friend_board_ocr():
                # Initialization can take seconds: revalidate the room before
                # clicking because the reviewed state may have changed.
                # Animated room particles can intermittently obscure settings;
                # allow more observations without weakening the two-frame gate.
                captures += await_reviewed_friend_room(page, reviewed, attempts=16,
                                                       on_capture=save_friend_start_capture)
            started_at = time.monotonic()
            page.mouse.click(1140, 998)
            startup_turn_guard.record_verified_start_click(clicked_at=started_at)
            self.log("reviewed_friend_start_clicked", preflight=str(preflight_path),
                     captures=captures, point={"x": 1140, "y": 998})
        if self.args.mode == "force-auto":
            # Room-start clicks can leave the pointer over the initial hand.
            # Clear hover before starting the stream, so its first frame cannot
            # inherit a raised tile from the room screen.
            retreat_pointer_from_hand(page.mouse, self.layout["viewport"])
            self.pointer_retreat_screencast_sequence = getattr(self, "screencast_sequence", None)
            page.wait_for_timeout(100)
        self.start_screencast_gate(page)
        if self.args.mode == "force-auto":
            deadline = time.monotonic() + 2
            while self.latest_screencast_frame is None and time.monotonic() < deadline:
                page.wait_for_timeout(25)
            if self.latest_screencast_frame is None:
                self.seed_silent_screencast_gate(page)
        self.log("started", mode=self.args.mode, page=page.url,
                 **({"matchLength": self.public_state["matchLength"]}
                    if getattr(self, "public_state", {}).get("matchLength") is not None else {}),
                 turnGate="cdp_screencast" if self.screencast_session else "screenshot")
        iterations = 0
        last_gate_sequence = -1
        draw_gate_streak = 0
        pass_gate_streak = 0
        call_gate_streak = 0
        reaction_win_gate_streak = 0
        silent_gate_polls = 0
        unchanged_gate_content_polls = 0
        last_gate_content_hash: str | None = None
        startup_guard_last_state: str | None = None
        while True:
            iterations += 1
            if self.args.max_iterations and iterations > self.args.max_iterations:
                return
            try:
                if getattr(self, "screen_loss_stop_requested", False):
                    # The CDP callback has already established that the
                    # calibrated game viewport disappeared.  Return rather
                    # than allowing force-auto's unknown-screen bypass to
                    # run hand geometry on a different browser tab.
                    return
                if getattr(self, "ranked_click_budget_safety_stop_requested", False):
                    # Do not click an away dialog after repeated stale-frame
                    # aborts. The active ranked match is no longer a valid
                    # automation evaluation and needs human review.
                    return
                self.poll_public_recognition()
                if getattr(self.args, "board_metadata", False):
                    self.poll_board_metadata()
                # Force-auto quick/exact gates consume the newest completed
                # public snapshot. Establish it before either branch; the
                # non-force path captures synchronously later in the loop.
                public_observation = self.cached_public_observation \
                    if self.args.mode == "force-auto" else None
                self.ensure_viewport(page)
                if self.capture_self_win_result(page):
                    continue
                gate_frame = None
                gate_captured_at: float | None = None
                quick_draw = False
                quick_pass = False
                quick_calls: list[dict[str, Any]] = []
                quick_self_actions: list[dict[str, Any]] = []
                quick_reaction_win = False
                refreshed_stable_gate = False
                gate_screen_state: str | None = None
                gate_screen_confidence: float | None = None
                gate_timing: dict[str, int] | None = None
                if self.args.mode == "force-auto" and self.layout.get("drawSlot"):
                    if self.screencast_sequence == last_gate_sequence:
                        silent_gate_polls += 1
                        page.wait_for_timeout(max(20, min(100, round(self.args.poll * 1000))))
                        if silent_gate_polls >= 5 and self.refresh_silent_screencast_gate(page):
                            silent_gate_polls = 0
                            refreshed_stable_gate = True
                        # Never manufacture the two-frame stability gate by
                        # inspecting the same received pixels again.  On the
                        # ranked path that leaves the eventual recognition
                        # tied to a frame which can already be seconds old.
                        # Wait for a distinct stream frame, or for the
                        # bounded silent-stream refresh above to publish one.
                        if self.screencast_sequence == last_gate_sequence:
                            continue
                    else:
                        silent_gate_polls = 0
                    gate_frame = self.latest_screencast_frame
                    gate_captured_at = getattr(self, "latest_screencast_captured_at", None)
                    gate_processing_started_at = time.monotonic()
                    gate_content_hash = perceptual_hash(gate_frame) if gate_frame else None
                    if gate_content_hash is not None and gate_content_hash == last_gate_content_hash:
                        unchanged_gate_content_polls += 1
                    else:
                        unchanged_gate_content_polls = 0
                    last_gate_content_hash = gate_content_hash
                    if unchanged_gate_content_polls >= 5 \
                            and self.refresh_silent_screencast_gate(page):
                        gate_frame = self.latest_screencast_frame
                        gate_captured_at = getattr(self, "latest_screencast_captured_at", None)
                        last_gate_content_hash = perceptual_hash(gate_frame) if gate_frame else None
                        unchanged_gate_content_polls = 0
                        refreshed_stable_gate = True
                    last_gate_sequence = self.screencast_sequence
                    # Navigation screens can contain large colored panels that
                    # resemble action buttons. Classify them before *any*
                    # reaction/draw gate and never run gameplay clicks there.
                    early_state, early_confidence = classify_screen(gate_frame, self.screen_references) \
                        if gate_frame else ("unknown", 0.0)
                    early_state, early_confidence, verified_gate_frame, non_gameplay_rejected = \
                        self.verify_screencast_non_gameplay_state(
                            page, early_state, early_confidence, gate_frame,
                        )
                    if non_gameplay_rejected:
                        gate_frame = verified_gate_frame
                        gate_captured_at = time.monotonic()
                    gate_screen_state, gate_screen_confidence = early_state, early_confidence
                    if self.handle_early_non_gameplay_screen(
                        page, early_state, early_confidence, gate_frame,
                    ):
                        if (getattr(self, "ranked_terminal_transition_stop_requested", False)
                                or getattr(self, "match_completed_stop_requested", False)):
                            return
                        page.wait_for_timeout(max(20, round(self.args.poll * 1000)))
                        continue
                    # Capture a short-lived dealing frame before launching OCR
                    # workers or running the other gameplay signal scans.
                    if not startup_turn_guard.ready and early_state == "match":
                        self.bound_initial_action_from_dealing(page, startup_turn_guard, gate_frame)
                    gameplay_reactions_allowed = early_state == "match"
                    restart_open_melds = self.verified_visible_open_melds(
                        self.cached_public_observation,
                    )
                    geometric_open_melds = geometric_open_meld_count(gate_frame, self.layout) \
                        if gate_frame else None
                    if gate_frame and self.should_reset_open_hand_state(gate_frame):
                        previous_open_melds = self.cached_open_melds
                        self.cached_concealed_tiles = None
                        self.cached_open_melds = 0
                        self.dynamic_layout_required = False
                        self.pending_post_call_discard = False
                        self.pending_post_call_started_at = None
                        self.restart_open_hand_probe_hash = None
                        self.open_meld_candidate = None
                        self.open_meld_candidate_frames = set()
                        self.cached_public_observation = None
                        self.previous_public_observation = None
                        self.pending_own_river_confirmation = None
                        self.public_cache_generation += 1
                        self.public_cache_last_frame_hash = None
                        restart_open_melds = None
                        geometric_open_melds = None
                        self.log(
                            "new_round_hand_state_reset",
                            previousOpenMelds=previous_open_melds,
                            source="stable_closed_13_tile_row",
                        )
                    if self.cached_open_melds > 0:
                        # A call executed and confirmed by this process is
                        # stronger than asynchronously promoted public melds.
                        # Require current hand geometry to agree with it and
                        # ignore stale/over-promoted public counts.
                        candidate_open_melds = geometric_open_melds \
                            if geometric_open_melds == self.cached_open_melds else None
                    else:
                        candidate_open_melds = restart_open_melds or geometric_open_melds
                        if restart_open_melds is not None and geometric_open_melds is not None \
                                and restart_open_melds != geometric_open_melds:
                            candidate_open_melds = None
                    gate_open_melds = self.stable_open_meld_count(
                        candidate_open_melds, gate_frame,
                    ) if gate_frame else None
                    dynamic_draw_slot = open_hand_draw_slot(
                        self.layout, gate_open_melds or self.cached_open_melds,
                    )
                    dynamic_draw_occupied = bool(
                        gate_frame and dynamic_draw_slot
                        and is_draw_slot_occupied(gate_frame, dynamic_draw_slot)
                    )
                    if gate_frame and gate_open_melds is not None:
                        self.recover_post_call_timeout(
                            frame=gate_frame, captured_at=gate_captured_at,
                            open_melds=gate_open_melds, draw_occupied=dynamic_draw_occupied,
                        )
                    restart_probe_hash = perceptual_hash(crop_screenshot(gate_frame, self.hand_clip)) \
                        if gate_frame and restart_open_melds is not None else None
                    restart_open_hand_probe = self.restart_open_hand_probe_needed(
                        frame_hash=restart_probe_hash,
                        last_hash=self.restart_open_hand_probe_hash,
                        cached_open_melds=self.cached_open_melds,
                    )
                    # The fixed closed-hand draw slot overlaps our own melds.
                    # Once an open count is known it must not create a draw
                    # signal that persists throughout every opponent turn.
                    known_open_melds = gate_open_melds or self.cached_open_melds
                    quick_draw = self.quick_draw_occupied(
                        open_melds=known_open_melds,
                        closed_slot_occupied=self.screencast_draw_occupied is True,
                        open_slot_occupied=dynamic_draw_occupied,
                    ) \
                        or self.pending_post_call_discard or restart_open_hand_probe
                    pass_region = self.layout.get("actionButtonRegions", {}).get("pass")
                    if gate_frame and pass_region and gameplay_reactions_allowed \
                            and not self.pending_post_call_discard:
                        quick_calls = force_auto_call_buttons(gate_frame, self.layout["viewport"])
                        quick_self_actions = force_auto_self_action_buttons(
                            gate_frame, self.layout["viewport"],
                        )
                        quick_pass = is_force_auto_pass_clip(crop_screenshot(gate_frame, pass_region)) \
                            or is_contextual_reaction_pass(
                                gate_frame, pass_region, len(quick_calls) + len(quick_self_actions),
                            )
                    if quick_draw:
                        quick_pass = False
                        quick_calls = []
                    if gate_frame and quick_pass and not self.pending_post_call_discard:
                        # Reaction prompts are independent of the draw-slot
                        # gate and must be inspected on every streamed frame.
                        # The win detector can only return an element of the
                        # orange buttons already found on this exact frame.
                        # Its result OR any orange button is therefore exactly
                        # this predicate; do not decode and scan them again.
                        quick_reaction_win = bool(quick_self_actions)
                    if not startup_turn_guard.ready and self.resume_startup_away(page, gate_frame):
                        page.wait_for_timeout(max(20, round(self.args.poll * 1000)))
                        continue
                    if not startup_turn_guard.ready:
                        self.prewarm_startup_context(gate_frame, verified_match=early_state == "match")
                    startup_guard_state = startup_turn_guard.observe(
                        verified_match=early_state == "match",
                        action_visible=bool(quick_draw or quick_pass or quick_calls or quick_reaction_win),
                        now=time.monotonic(),
                    )
                    if startup_guard_state != startup_guard_last_state:
                        self.log("startup_turn_guard", state=startup_guard_state,
                                 quarantined=startup_turn_guard.quarantined)
                        startup_guard_last_state = startup_guard_state
                    if startup_guard_state != "ready":
                        # The first visible action may already be near the game
                        # deadline. Do not manufacture a new clock for it.
                        page.wait_for_timeout(max(20, round(self.args.poll * 1000)))
                        continue
                    initial_anchor = startup_turn_guard.initial_action_anchor
                    startup_turn_guard.initial_action_anchor = None
                    initial_budget_observed = (
                        gate_captured_at
                        if long_friend_initial_clock and initial_anchor is not None
                        and gate_captured_at is not None
                        and initial_anchor <= gate_captured_at <= time.monotonic()
                        else None
                    )
                    if initial_budget_observed is not None:
                        self.log("friend_initial_budget_clock_separated",
                                 elapsedSinceStartMs=round((initial_budget_observed - initial_anchor) * 1000),
                                 deadlineMs=self.configured_action_deadline_ms(),
                                 clickBudgetMs=self.force_auto_click_budget_ms())
                    draw_gate_streak = draw_gate_streak + 1 if quick_draw else 0
                    pass_gate_streak = pass_gate_streak + 1 if quick_pass else 0
                    call_gate_streak = call_gate_streak + 1 if quick_calls else 0
                    reaction_win_gate_streak = reaction_win_gate_streak + 1 if quick_reaction_win else 0
                    if quick_reaction_win:
                        self.mark_action_evidence(
                            "win", observed_at=initial_anchor, budget_observed_at=initial_budget_observed,
                            gate_generation=self.screencast_sequence,
                        )
                    elif quick_pass or quick_calls:
                        self.mark_action_evidence(
                            "reaction", observed_at=initial_anchor, budget_observed_at=initial_budget_observed,
                            gate_generation=self.screencast_sequence,
                        )
                    elif quick_draw:
                        prior_kind = getattr(self, "action_evidence_kind", None)
                        reaction_vanished_for = time.monotonic() - (
                            getattr(self, "action_evidence_last_seen_at", None) or time.monotonic()
                        )
                        verified_later_draw = draw_gate_streak >= 2 \
                            and prior_kind in {"reaction", "win"} \
                            and reaction_vanished_for > 0.75
                        self.mark_action_evidence(
                            "discard",
                            observed_at=initial_anchor,
                            budget_observed_at=initial_budget_observed,
                            gate_generation=self.screencast_sequence,
                            supersede=verified_later_draw,
                        )
                        if prior_kind in {"reaction", "win"} and not verified_later_draw:
                            # Preserve the short frame-drop grace: a single
                            # missing prompt frame must not become a new turn.
                            page.wait_for_timeout(20)
                            continue
                    elif getattr(self, "action_evidence_started_at", None) is not None \
                            and time.monotonic() - (getattr(self, "action_evidence_last_seen_at", None) or 0) > 0.75:
                        self.action_evidence_started_at = None
                        self.action_budget_started_at = None
                        self.action_evidence_kind = None
                        self.action_evidence_generation = None
                        self.action_evidence_last_seen_at = None
                    if quick_pass and pass_gate_streak == 1:
                        self.log(
                            "reaction_gate_candidate",
                            callButtonCount=len(quick_calls),
                            orangeButtonCount=len(quick_self_actions),
                            contextual=not is_force_auto_pass_clip(crop_screenshot(gate_frame, pass_region)),
                        )
                    if refreshed_stable_gate:
                        if quick_pass:
                            pass_gate_streak = max(pass_gate_streak, 2)
                        if quick_calls:
                            call_gate_streak = max(call_gate_streak, 2)
                        if quick_reaction_win:
                            reaction_win_gate_streak = max(reaction_win_gate_streak, 2)
                    if ((quick_draw and draw_gate_streak < 2)
                            or (quick_pass and pass_gate_streak < 2)
                            or (quick_calls and call_gate_streak < 2)
                            or (quick_reaction_win and reaction_win_gate_streak < 2)):
                        page.wait_for_timeout(20)
                        continue
                    gate_timing = {
                        "frameReceiptAgeAtGateMs": self.force_auto_capture_age_ms(gate_captured_at),
                        "screenAndSignalScanMs": round((time.monotonic() - gate_processing_started_at) * 1000),
                    }
                    # The small regions are the latency-critical turn gate.
                    # Keep a periodic full frame for away/result handling.
                    if not quick_draw and not quick_pass and not quick_calls and not quick_reaction_win and iterations % 10:
                        page.wait_for_timeout(max(20, round(self.args.poll * 1000)))
                        continue
                if quick_draw and self.args.mode == "force-auto":
                    # A room-start click or stale hover can lift one tile into
                    # the fixed recognition crop. Retreat before the first
                    # full hand image, including when the room was started
                    # after this operator attached.
                    if screencast_frame_follows_pointer_retreat(
                        getattr(self, "screencast_sequence", None),
                        getattr(self, "pointer_retreat_screencast_sequence", None),
                    ):
                        # This gate receipt is after our own inert-table move;
                        # its two-frame gate has already supplied the same
                        # hover-free evidence as a fresh PNG capture.
                        full_screen = gate_frame
                        full_screen_captured_at = gate_captured_at
                    else:
                        retreat_pointer_from_hand(page.mouse, self.layout["viewport"])
                        self.pointer_retreat_screencast_sequence = getattr(self, "screencast_sequence", None)
                        page.wait_for_timeout(100)
                        full_screen = page.screenshot(animations="disabled")
                        full_screen_captured_at = time.monotonic()
                else:
                    full_screen = gate_frame or page.screenshot(animations="disabled")
                    # A missing stream frame falls back to a synchronous
                    # screenshot.  It is still reaction evidence and must
                    # carry a receipt time for the short ranked click guard.
                    full_screen_captured_at = gate_captured_at if gate_frame else time.monotonic()
                draw_slot_heuristic_occupied = False
                # The low-latency gate above has already classified this exact
                # streamed frame and found its action buttons.  Re-running the
                # full-image classifier and colour scans here consumed about
                # 0.6s before recognition on the ranked 2600ms path.  Reuse
                # only identical bytes from that gate; synchronous snapshots
                # and any changed frame retain the independent checks.
                reused_gate_frame = (
                    self.args.mode == "force-auto"
                    and full_screen is gate_frame
                    and gate_screen_state is not None
                    and gate_screen_confidence is not None
                )
                if reused_gate_frame:
                    screen_state, screen_confidence = gate_screen_state, gate_screen_confidence
                else:
                    screen_state, screen_confidence = classify_screen(full_screen, self.screen_references)
                if screen_state == "round_result":
                    live_evidence = round_result_conflicts_with_live_table(full_screen, self.layout)
                    if live_evidence is not None:
                        self.log("round_result_rejected_live_table", confidence=screen_confidence,
                                 liveTableEvidence=live_evidence)
                        screen_state, screen_confidence = "match", 1.0
                if screen_state == "away":
                    if self.resume_if_away(page, full_screen):
                        time.sleep(self.args.poll)
                        continue
                    # Match and away references share almost the entire table.
                    # The stricter popup/button geometry remains authoritative.
                    screen_state = "match"
                self.observe_ranked_match_screen(screen_state)
                if screen_state in {"round_result", "match_result", "rank_progress", "post_match_reward"}:
                    self.ranked_terminal_matchmaking_seen_at = None
                    if getattr(self, "round_terminal_latched", False):
                        self.round_terminal_result_observed = True
                    # A new hand (or a new match) must never inherit tiles or
                    # reaction state from the hand whose result is displayed.
                    self.cached_concealed_tiles = None
                    self.cached_open_melds = 0
                    self.dynamic_layout_required = False
                    self.pending_post_call_discard = False
                    self.pending_post_call_started_at = None
                    self.restart_open_hand_probe_hash = None
                    self.open_meld_candidate = None
                    self.open_meld_candidate_frames = set()
                    self.closed_new_round_candidate_frames = set()
                    self.public_cache_generation += 1
                    self.public_cache_last_frame_hash = None
                    self.cached_public_observation = None
                    self.previous_public_observation = None
                    self.pending_own_river_confirmation = None
                    self.riichi_metadata_history = None
                    self.reset_post_riichi_safety()
                    self.last_shanten = None
                    self.last_processed_hand = None
                    self.armed = True
                    if self.args.ranked_loop:
                        # Do not arm a ranked terminal-transition stop for a
                        # round summary.  A verified match-end result is
                        # required before matchmaking can be considered an
                        # unsafe, unverified navigation transition.
                        self.ranked_terminal_transition_pending = screen_state in {
                            "match_result", "rank_progress", "post_match_reward",
                        }
                    if screen_state not in {"rank_progress", "post_match_reward"}:
                        self.attach_outcome("match" if screen_state == "match_result" else "round", full_screen, screen_confidence)
                    # Confirm at most once after preserving the result, then
                    # stop without navigating or starting another match.
                    if self.should_stop_after_match_result(screen_state):
                        self.confirm_friend_match_result(page, screen_state, screen_confidence, full_screen)
                        self.log("match_completed_stop", confidence=screen_confidence)
                        return
                    if self.args.advance_screens or self.args.ranked_loop:
                        self.advance_result_screen_once(page, screen_state, screen_confidence)
                        time.sleep(self.args.poll)
                        continue
                else:
                    self.result_screen_advanced = None
                if self.ranked_terminal_transition_requires_stop(screen_state):
                    self.log_ranked_terminal_transition_stop(screen_state, screen_confidence, full_screen)
                    return
                if screen_state == "black_screen":
                    if self.args.mode == "force-auto":
                        self.recover_black_screen(page)
                    else:
                        self.log("screen_state_bypassed", state=screen_state,
                                 confidence=screen_confidence, gameplayClicks=0)
                    time.sleep(self.args.poll)
                    continue
                self.black_screen_seen_since = None
                if self.guard_black_recovery_outcome(page, screen_state):
                    time.sleep(self.args.poll)
                    continue
                if screen_state == "loading":
                    self.log("screen_state_bypassed", state=screen_state,
                             confidence=screen_confidence, gameplayClicks=0)
                    time.sleep(self.args.poll)
                    continue
                if self.wait_for_round_terminal(page, full_screen, screen_state):
                    page.wait_for_timeout(max(20, round(self.args.poll * 1000)))
                    continue
                if self.args.mode == "force-auto" and screen_state == "login" and screen_confidence >= .95:
                    if self.login_button_clicked_at is None:
                        point = {"x": self.layout["viewport"]["width"] * .779,
                                 "y": self.layout["viewport"]["height"] * .435}
                        page.mouse.click(point["x"], point["y"])
                        self.login_button_clicked_at = time.monotonic()
                        self.log("login_button_clicked", clickPoint=point, confidence=screen_confidence)
                    elif time.monotonic() - self.login_button_clicked_at > 5:
                        self.log("login_required_stop", state=screen_state, confidence=screen_confidence)
                        return
                    page.wait_for_timeout(max(100, round(self.args.poll * 1000)))
                    continue
                if self.login_button_clicked_at is not None:
                    if screen_state == "lobby":
                        self.log("login_session_restored", state=screen_state, confidence=screen_confidence)
                        self.login_button_clicked_at = None
                        if not self.args.ranked_loop:
                            return
                    elif screen_state in {"account_modal", "unknown"} \
                            or time.monotonic() - self.login_button_clicked_at > 5:
                        snapshot = self.frames / f"{utc_stamp()}.login-after-click.png"
                        snapshot.write_bytes(full_screen)
                        snapshot.chmod(0o600)
                        self.log("login_required_stop", state=screen_state,
                                 confidence=screen_confidence, screenshot=str(snapshot))
                        return
                if self.args.mode == "force-auto" and screen_state == "account_modal":
                    self.log("login_required_stop", state=screen_state, confidence=screen_confidence)
                    return
                if self.advance_ranked_loop(page, screen_state, screen_confidence, screenshot=full_screen):
                    page.wait_for_timeout(max(100, round(self.args.poll * 1000)))
                    continue
                if screen_state != "match" and self.args.mode != "force-auto":
                    if self.args.mode == "observer" and (screen_state == "login" or getattr(self.args, "snapshot_nonmatch", False)) \
                            and getattr(self, "last_observer_screen_state", None) != screen_state:
                        snapshot = self.frames / f"{utc_stamp()}.{screen_state}.png"
                        snapshot.write_bytes(full_screen)
                        self.last_observer_screen_state = screen_state
                        self.log("observer_screen_snapshot", state=screen_state, screenshot=str(snapshot))
                    self.log("screen_state", state=screen_state, confidence=screen_confidence)
                    time.sleep(self.args.poll)
                    continue
                if screen_state != "match":
                    # Loading animation frames are frequently closest to the
                    # login/account references for several seconds after the
                    # table is already interactive.  Force-auto remains safe
                    # here because the exact evaluated frame must still have
                    # a recognized draw tile and a complete legal hand before
                    # any click is possible.
                    self.log("screen_state_bypassed", state=screen_state, confidence=screen_confidence)
                if self.resume_if_away(page, full_screen):
                    time.sleep(self.args.poll)
                    continue
                # Dora can change after any kan and must not depend on whether
                # this is currently classified as our turn or an opponent's.
                self.schedule_periodic_public_recognition(full_screen, verified_match=screen_state == "match")
                if self.args.mode == "force-auto":
                    pass_region = self.layout.get("actionButtonRegions", {}).get("pass")
                    if reused_gate_frame:
                        call_buttons = quick_calls
                        orange_buttons = quick_self_actions
                    else:
                        call_buttons = force_auto_call_buttons(full_screen, self.layout["viewport"]) \
                            if should_process_reaction_prompt(self.pending_post_call_discard) else []
                        orange_buttons = force_auto_self_action_buttons(full_screen, self.layout["viewport"])
                    pass_prompt_present = bool(pass_region and (
                        is_force_auto_pass_prompt(full_screen, pass_region)
                        or is_contextual_reaction_pass(
                            full_screen, pass_region, len(call_buttons) + len(orange_buttons),
                        )
                    ))
                    has_reaction_prompt = bool(
                        should_process_reaction_prompt(self.pending_post_call_discard)
                        and pass_prompt_present
                        and not self_turn_draw_visible(full_screen, self.layout, self.cached_open_melds)
                    )
                    if has_reaction_prompt:
                        decision_started_at = time.monotonic()
                        screenshot_path = self.frames / f"{utc_stamp()}.png"
                        screenshot_path.write_bytes(full_screen)
                        reaction_win = force_auto_reaction_win_button(
                            full_screen, self.layout["viewport"], pass_region,
                        )
                        if reaction_win is None and len(orange_buttons) == 1:
                            reaction_win = {**orange_buttons[0], "source": "contextual_reaction_prompt"}
                        if reaction_win:
                            receipt = self.execute_force_auto_reaction_win(
                                page, full_screen, reaction_win,
                                evaluated_captured_at=full_screen_captured_at,
                            )
                            receipt["actionTiming"] = self.action_timing(decision_started_at, clear=True)
                            self.log("reaction_win", screenshot=str(screenshot_path), execution=receipt)
                            time.sleep(self.args.poll)
                            continue
                        if getattr(self.args, "accept_single_call", False) and len(call_buttons) == 1:
                            call_action = call_buttons[0].get("action")
                            try:
                                policy = self.evaluate_force_auto_call_policy(
                                    screenshot_path, call_action, captured_at=full_screen_captured_at,
                                )
                            except RetryableSafetyAbort as error:
                                self.log("reaction_call_policy_deferred", screenshot=str(screenshot_path), error=str(error))
                                elapsed_ms = self.configured_action_deadline_ms() - self.action_deadline_remaining_ms()
                                if should_retry_call_policy(error, elapsed_ms):
                                    page.wait_for_timeout(max(100, round(self.args.poll * 1000)))
                                    continue
                                self.log("reaction_call_policy_rejected", action=call_action,
                                         reason="persistent_tile_count_conflict_safe_pass",
                                         elapsedMs=elapsed_ms)
                                policy = None
                            if policy:
                                decision = policy.get("decision", {})
                                try:
                                    receipt = self.execute_force_auto_call(
                                        page, full_screen, call_buttons[0],
                                        decision.get("selectedAction"), decision.get("legalActions"),
                                        evaluated_captured_at=full_screen_captured_at,
                                    )
                                except RetryableSafetyAbort as error:
                                    self.log(
                                        "reaction_call_unconfirmed", screenshot=str(screenshot_path), error=str(error),
                                        selectedAction=decision.get("selectedAction"),
                                        legalActions=decision.get("legalActions"),
                                    )
                                    page.wait_for_timeout(max(100, round(self.args.poll * 1000)))
                                    continue
                                if receipt.get("confirmation") == "hand_and_own_meld_changed" \
                                        and policy.get("verifiedCallDiscard"):
                                    self.reconcile_confirmed_call_discard(
                                        policy["verifiedCallDiscard"], decision.get("selectedAction"),
                                    )
                                receipt["actionTiming"] = self.action_timing(decision_started_at, clear=True)
                                self.log("reaction_call", screenshot=str(screenshot_path), evaluation=policy,
                                         execution=receipt)
                                time.sleep(self.args.poll)
                                continue
                        if len(call_buttons) > 1:
                            self.log("reaction_call_ambiguous", screenshot=str(screenshot_path),
                                     buttonCount=len(call_buttons))
                        if should_guard_tenpai_reaction(self.last_shanten, call_buttons):
                            self.log("tenpai_reaction_guard", screenshot=str(screenshot_path),
                                     reason="reaction may contain ron; refusing blind pass")
                            time.sleep(max(self.args.poll, 1))
                            continue
                        reaction = self.force_auto_reaction_fallback(
                            screenshot_path, contextual_prompt_verified=pass_prompt_present,
                        )
                        if reaction:
                            try:
                                receipt = self.execute_reaction_pass(
                                    page, reaction, evaluated_captured_at=full_screen_captured_at,
                                )
                            except RetryableSafetyAbort as error:
                                self.log("reaction_pass_deferred", screenshot=str(screenshot_path), error=str(error))
                                page.wait_for_timeout(max(100, round(self.args.poll * 1000)))
                                continue
                            receipt["actionTiming"] = self.action_timing(decision_started_at, clear=True)
                            self.log("reaction_prompt", screenshot=str(screenshot_path), evaluation=reaction, execution=receipt)
                            self.last_processed_hand = None
                            self.armed = True
                            time.sleep(self.args.poll)
                            continue
                    draw_slot = self.layout.get("drawSlot")
                    if draw_slot:
                        draw_slot_heuristic_occupied = is_draw_slot_occupied(full_screen, draw_slot)
                    if not quick_draw and not quick_pass:
                        # Periodic streamed frames above are sufficient for
                        # away/result handling. Public tiles are classified by
                        # a separate resident worker so this turn gate remains
                        # responsive while opponents are acting.
                        self.schedule_periodic_public_recognition(full_screen, verified_match=screen_state == "match")
                        if getattr(self.args, "board_metadata", False):
                            self.schedule_board_metadata(full_screen)
                        page.wait_for_timeout(max(20, round(self.args.poll * 1000)))
                        continue
                if self.args.mode == "force-auto" and self.screencast_session is not None:
                    # Two consecutive streamed gate frames already established
                    # stability. Reuse that exact frame for recognition instead
                    # of issuing a blocking PNG capture on the three-second
                    # clock. The calibrated matcher tolerates the screencast's
                    # JPEG encoding, while the generation check in execute()
                    # still rejects a frame after the turn has rolled over.
                    if gate_frame is None:
                        page.wait_for_timeout(20)
                        continue
                    decision_started_at = time.monotonic()
                    evaluation_frame = gate_frame
                    # ``gate_frame`` is the frame that feeds recognition, not
                    # necessarily the newest frame when execute() eventually
                    # runs.  Bind its receipt time here so the short ranked
                    # budget measures the decision's actual visual evidence.
                    evaluation_captured_at = gate_captured_at
                    hand = crop_screenshot(evaluation_frame, self.hand_clip)
                    action_image = crop_screenshot(evaluation_frame, self.action_clip) if self.action_clip else b""
                else:
                    decision_started_at = time.monotonic()
                    hand = page.screenshot(clip=self.hand_clip, animations="disabled")
                    page.wait_for_timeout(self.args.stability_ms)
                    hand_second = page.screenshot(clip=self.hand_clip, animations="disabled")
                    if mean_pixel_delta(hand, hand_second) > self.args.stability_pixel_delta:
                        self.armed = True
                        time.sleep(self.args.poll)
                        continue
                    action_image = page.screenshot(clip=self.action_clip, animations="disabled") if self.action_clip else b""
                    evaluation_frame = page.screenshot(animations="disabled")
                    evaluation_captured_at = time.monotonic()
                evaluation_draw_generation = self.screencast_draw_generation if self.screencast_session else None
                hand_identity = perceptual_hash(hand) + (perceptual_hash(action_image) if action_image else "")
                # Discarding the draw and drawing the same tile next turn can
                # reproduce both crops exactly. Keep duplicate suppression
                # within a streamed draw, but let a new draw reach river
                # reconciliation and recognition even when its pixels match.
                if evaluation_draw_generation is not None:
                    hand_identity += f":draw:{evaluation_draw_generation}"
                hand_hash = hashlib.sha256(hand_identity.encode()).hexdigest()
                uncertainty_rearm = self.selection_uncertainty_rearm_reason(
                    evaluation_draw_generation, public_observation,
                )
                if getattr(self, "selection_uncertainty_latch", None):
                    clock_rearmed = self.rearm_uncertain_selection_clock(
                        evaluation_draw_generation,
                        getattr(self, "screencast_draw_generation_at", None),
                    )
                    if uncertainty_rearm is None or not clock_rearmed:
                        # Do not fall through to the generic hand-hash
                        # re-arm below.  A raised tile alters that hash while
                        # remaining the same selectable tile, and a retry
                        # would be an unproven deselect operation.
                        if self.args.mode == "force-auto":
                            self.schedule_public_recognition(evaluation_frame, force=True)
                        self.last_processed_hand = hand_hash
                        self.armed = False
                        self.log(
                            "selection_uncertainty_wait",
                            drawGeneration=evaluation_draw_generation,
                            baselineDrawGeneration=self.selection_uncertainty_latch.get("drawGeneration"),
                            baselineOwnDiscards=self.selection_uncertainty_latch.get("ownDiscards"),
                        )
                        uncertainty_now = time.monotonic()
                        # Normally rearm_uncertain_selection_clock records
                        # the screencast receipt.  If that timestamp is
                        # absent, start a no-click grace from this verified
                        # evaluation instead of waiting forever.
                        if uncertainty_rearm is not None and \
                                self.selection_uncertainty_latch.get("firstNewDrawObservedAt") is None:
                            self.selection_uncertainty_latch["firstNewDrawObservedAt"] = uncertainty_now
                        if self.selection_uncertainty_stop_due(uncertainty_now):
                            self.log(
                                "selection_uncertainty_safety_stop",
                                drawGeneration=evaluation_draw_generation,
                                baselineDrawGeneration=self.selection_uncertainty_latch.get("drawGeneration"),
                                reason="later_draw_without_confirmed_own_river",
                                gameplayClicks=0,
                            )
                            return
                        page.wait_for_timeout(max(100, round(self.args.poll * 1000)))
                        continue
                    self.log("selection_uncertainty_rearmed", reason=uncertainty_rearm)
                    self.selection_uncertainty_latch = None
                    self.last_processed_hand = None
                    self.armed = True
                if not self.armed:
                    if hand_hash == self.last_processed_hand:
                        time.sleep(self.args.poll)
                        continue
                    self.armed = True
                    self.log("rearmed", reason="hand_region_or_draw_generation_changed")
                if hand_hash == self.last_processed_hand:
                    time.sleep(self.args.poll)
                    continue
                if self.args.mode == "force-auto":
                    # Do not write and synchronously recognize a streamed
                    # frame whose *receipt* already consumed the entire
                    # ranked decision-to-click budget.  The later guard in
                    # execute() protects the click; this earlier guard avoids
                    # spending several seconds evaluating a decision that can
                    # only be discarded as stale.  Keep 300+0 runs unchanged
                    # unless they explicitly opt into a click budget.
                    try:
                        self.require_force_auto_click_budget(
                            evaluation_captured_at, phase="before_recognition",
                        )
                    except RetryableSafetyAbort as error:
                        self.last_processed_hand = None
                        self.armed = True
                        self.log(
                            "recognition_deferred_stale_capture",
                            captureAgeMs=self.force_auto_capture_age_ms(evaluation_captured_at),
                            clickBudgetMs=self.force_auto_click_budget_ms(),
                            **({
                                "gateTiming": {
                                    **gate_timing,
                                    "gateToRecognitionMs": round((time.monotonic() - gate_processing_started_at) * 1000),
                                },
                            } if gate_timing is not None else {}),
                            error=str(error),
                        )
                        page.wait_for_timeout(max(20, round(self.args.poll * 1000)))
                        continue
                frame_suffix = ".jpg" if evaluation_frame.startswith(b"\xff\xd8\xff") else ".png"
                screenshot_path = self.frames / f"{utc_stamp()}{frame_suffix}"
                screenshot_path.write_bytes(evaluation_frame)
                if self.args.mode == "force-auto" and self.layout.get("drawSlot"):
                    # Re-check the exact frame that will be evaluated.  On a
                    # short clock the turn can expire between the earlier
                    # full-screen gate and this stable screenshot, leaving a
                    # stale "occupied" result for a now 13-tile hand. Inspect
                    # the lossless evaluation frame directly; template
                    # classification belongs only to frames that still have
                    # an occupied draw slot.
                    verified_open_melds = self.verified_visible_open_melds(public_observation)
                    geometric_open_melds = geometric_open_meld_count(evaluation_frame, self.layout)
                    if self.cached_open_melds > 0:
                        exact_open_melds = geometric_open_melds \
                            if geometric_open_melds == self.cached_open_melds else None
                    else:
                        exact_open_melds = verified_open_melds or geometric_open_melds
                        if verified_open_melds is not None and geometric_open_melds is not None \
                                and verified_open_melds != geometric_open_melds:
                            exact_open_melds = None
                    if gate_open_melds is not None and exact_open_melds != gate_open_melds:
                        exact_open_melds = None
                    # Use the confirmed count to locate an empty compact draw
                    # even when no *self-turn* geometry can be established.
                    # Falling back to the closed slot would read our melds.
                    exact_draw_slot = open_hand_draw_slot(
                        self.layout, exact_open_melds or self.cached_open_melds,
                    ) \
                        or self.layout["drawSlot"]
                    exact_draw_occupied = is_draw_slot_occupied(evaluation_frame, exact_draw_slot)
                    self.supersede_reaction_on_verified_draw(
                        draw_occupied=exact_draw_occupied,
                        exact_open_melds=exact_open_melds,
                        geometric_open_melds=geometric_open_melds,
                    )
                    if exact_draw_occupied and geometric_open_melds is not None \
                            and exact_open_melds == geometric_open_melds:
                        self.cached_open_melds = geometric_open_melds
                        self.dynamic_layout_required = True
                        self.log(
                            "open_hand_geometry_gate",
                            screenshot=str(screenshot_path),
                            openMelds=geometric_open_melds,
                            evidence={
                                "compactConcealedTiles": 13 - geometric_open_melds * 3,
                                "shiftedDrawSlot": exact_draw_slot,
                                "ownMeldRegion": "lower_right_ivory_surface",
                            },
                        )
                    if not exact_draw_occupied and not self.pending_post_call_discard:
                        concealed = self.recognize_resident(
                            screenshot_path, concealed_only=True,
                            dynamic_layout=self.cached_open_melds > 0,
                            open_melds=self.cached_open_melds if self.cached_open_melds > 0 else None,
                        )
                        concealed_tiles = concealed.get("tiles", [])
                        recovered_open_melds = self.restart_open_discard_meld_count(
                            len(concealed_tiles), public_observation,
                        )
                        if self.cached_open_melds > 0 \
                                and recovered_open_melds != self.cached_open_melds:
                            recovered_open_melds = None
                        if recovered_open_melds is not None:
                            self.cached_open_melds = recovered_open_melds
                            self.dynamic_layout_required = True
                            self.pending_post_call_discard = True
                            self.pending_post_call_started_at = time.monotonic()
                            self.log(
                                "open_hand_discard_gate_recovered",
                                screenshot=str(screenshot_path),
                                concealedTileCount=len(concealed_tiles),
                                openMelds=recovered_open_melds,
                                source="verified_visible_own_melds",
                            )
                        else:
                            self.restart_open_hand_probe_hash = perceptual_hash(hand)
                            if self.cached_concealed_tiles is None and len(concealed_tiles) == 13:
                                self.cached_concealed_tiles = concealed_tiles
                                self.cached_open_melds = 0
                                self.dynamic_layout_required = False
                                self.log("concealed_hand_cached", screenshot=str(screenshot_path),
                                         tileCount=len(concealed_tiles))
                            self.last_processed_hand = hand_hash
                            self.armed = False
                            self.log("opponent_turn_confirmed", screenshot=str(screenshot_path),
                                     source="evaluated_frame_draw_slot_pixels",
                                     priorHeuristicOccupied=draw_slot_heuristic_occupied)
                            self.clear_discard_evidence_on_confirmed_opponent_turn()
                            time.sleep(self.args.poll)
                            continue
                    if not draw_slot_heuristic_occupied:
                        self.log("self_turn_detected", screenshot=str(screenshot_path),
                                 source="evaluated_frame_draw_slot_pixels")
                self.poll_public_recognition()
                self.reconcile_own_discard()
                # Force-auto never waits for public recognition on our turn;
                # it consumes the newest completed opponent-turn snapshot.
                if self.args.mode == "force-auto":
                    public_observation = self.cached_public_observation
                else:
                    public_observation = self.observe_public_board(screenshot_path)
                pending_discard = None if self.args.mode == "force-auto" \
                    else self.infer_pending_discard(self.previous_public_observation, public_observation)
                if public_observation and self.args.mode != "force-auto":
                    self.previous_public_observation = public_observation
                staged_reconciliation_hand = None
                if self.args.mode == "force-auto" and self.own_discard_reconciliation_pending():
                    # A candidate post-click river snapshot is independent
                    # evidence for the concealed-hand cache.  Require its
                    # second observation before a subsequent discard, so two
                    # self turns cannot be folded into one append.  Do not
                    # block merely for a pending click with no observed
                    # candidate: a false confirmation otherwise waits through
                    # the game's entire 300-second timer.
                    pending = self.pending_own_discard
                    self.schedule_public_recognition(evaluation_frame, force=True)
                    if not pending.get("reconciliationWaitLogged"):
                        pending["reconciliationWaitLogged"] = True
                        self.log(
                            "own_discard_reconciliation_wait",
                            expected=pending.get("tile"),
                            before=pending.get("before"),
                            confirmationCandidate=self.pending_own_river_confirmation,
                        )
                    staged_reconciliation_hand = self.stage_hand_during_discard_reconciliation(
                        screenshot_path, evaluation_captured_at,
                    )
                    if staged_reconciliation_hand is None:
                        self.last_processed_hand = None
                        self.armed = True
                        page.wait_for_timeout(max(100, round(self.args.poll * 1000)))
                        continue
                    public_observation = self.cached_public_observation
                if self.args.mode == "force-auto" and not pending_discard:
                    self_action_buttons = force_auto_self_action_buttons(
                        evaluation_frame, self.layout["viewport"],
                    )
                    dynamic_layout_was_required = self.dynamic_layout_required
                    try:
                        recognition_kwargs = {
                            "dynamic_layout": self.dynamic_layout_required,
                            "open_melds": self.cached_open_melds if self.cached_open_melds > 0 else None,
                            "public_observation": public_observation,
                            "force_auto_action_buttons": self_action_buttons,
                            "captured_at": evaluation_captured_at,
                        }
                        if staged_reconciliation_hand is not None:
                            recognition_kwargs["staged_recognition"] = staged_reconciliation_hand
                        # Cached tiles are not guaranteed to match the newly
                        # sorted physical row after the last discard.  With
                        # board metadata enabled, recognize that complete row
                        # concurrently with OCR from this exact screenshot.
                        evaluation = self.recognize_force_auto_or_defer(screenshot_path, **recognition_kwargs)
                        if evaluation is None:
                            page.wait_for_timeout(max(20, round(self.args.poll * 1000)))
                            continue
                    except RuntimeError as initial_error:
                        self.cached_concealed_tiles = None
                        # A prompt can arrive while the resident recognizer is
                        # synchronously evaluating a draw. Never start another
                        # blocking recognition retry ahead of that reaction.
                        latest = self.latest_screencast_frame
                        latest_pass_region = self.layout.get("actionButtonRegions", {}).get("pass")
                        if latest is not None and latest_pass_region is not None \
                                and not self.pending_post_call_discard:
                            latest_calls = force_auto_call_buttons(latest, self.layout["viewport"])
                            latest_actions = force_auto_self_action_buttons(latest, self.layout["viewport"])
                            latest_pass = is_force_auto_pass_clip(crop_screenshot(latest, latest_pass_region)) \
                                or is_contextual_reaction_pass(
                                    latest, latest_pass_region, len(latest_calls) + len(latest_actions),
                                )
                            if latest_pass:
                                self.mark_action_evidence(
                                    "win" if latest_actions else "reaction",
                                )
                                self.log(
                                    "recognition_retry_preempted_by_reaction",
                                    screenshot=str(screenshot_path),
                                    initialError=str(initial_error),
                                )
                                self.last_processed_hand = None
                                self.armed = True
                                continue
                        try:
                            evaluation = self.recognize_resident(
                                screenshot_path, evaluate_force_auto=True, dynamic_layout=True,
                                open_melds=self.cached_open_melds if self.cached_open_melds > 0 else None,
                                public_observation=public_observation,
                                force_auto_action_buttons=self_action_buttons,
                                captured_at=evaluation_captured_at,
                            )
                        except RuntimeError as retry_error:
                            # Deal animations can briefly place 15-20 bright
                            # tile-like components across the hand row. This is
                            # not an operator fault and becomes valid on a later
                            # streamed frame, so keep the click gate armed and
                            # retry instead of terminating the whole session.
                            self.last_processed_hand = None
                            self.armed = True
                            self.log(
                                "recognition_retry", screenshot=str(screenshot_path),
                                error=str(retry_error), initialError=str(initial_error),
                            )
                            page.wait_for_timeout(max(20, round(self.args.poll * 1000)))
                            continue
                    if self.defer_missing_public_context(evaluation, evaluation_frame):
                        self.last_processed_hand = None
                        self.armed = True
                        page.wait_for_timeout(max(100, round(self.args.poll * 1000)))
                        continue
                    inferred_open_melds = evaluation.get("openMelds", 0)
                    verified_visible_open_melds = self.verified_visible_open_meld_count(
                        inferred_open_melds, public_observation,
                    )
                    recognized_tiles = evaluation.get("recognition", {}).get("tiles", [])
                    evaluated_point = evaluation.get("clickPoint")
                    compact_row_matches = bool(
                        inferred_open_melds > 0
                        and len(recognized_tiles) == 14 - inferred_open_melds * 3
                        and isinstance(evaluated_point, dict)
                        and discard_point_in_hand_geometry(evaluated_point, self.layout, inferred_open_melds)
                        and own_meld_surface_visible(evaluation_frame, self.layout)
                    )
                    if evaluation.get("status") == "decision" and compact_row_matches \
                            and not dynamic_layout_was_required:
                        recovered = self.stable_open_meld_count(inferred_open_melds, evaluation_frame)
                        latest_frame = self.latest_screencast_frame
                        compact_region = stable_hand_comparison_region(self.layout, inferred_open_melds)
                        if latest_frame is not None and latest_frame != evaluation_frame \
                                and compact_region is not None \
                                and own_meld_surface_visible(latest_frame, self.layout) \
                                and mean_pixel_delta(
                                    crop_screenshot(evaluation_frame, compact_region),
                                    crop_screenshot(latest_frame, compact_region),
                                ) <= self.args.stability_pixel_delta:
                            recovered = self.stable_open_meld_count(inferred_open_melds, latest_frame) or recovered
                        if recovered is not None:
                            self.cached_open_melds = recovered
                            self.dynamic_layout_required = True
                            dynamic_layout_was_required = True
                            self.log(
                                "open_hand_recovered",
                                openMelds=recovered,
                                source="stable_compact_row_and_own_meld_surface",
                            )
                    if evaluation.get("status") == "decision" and not self.compact_hand_is_proven(
                        inferred_open_melds, dynamic_layout_was_required, public_observation,
                    ):
                        # During the opening deal, a temporary 11/8/5/2-tile
                        # row can look exactly like a compact post-call hand.
                        # A compact layout is valid only after this operator
                        # has already observed/executed a call in the round.
                        self.cached_concealed_tiles = None
                        self.cached_open_melds = 0
                        self.dynamic_layout_required = False
                        self.last_processed_hand = None
                        self.armed = True
                        self.log(
                            "recognition_retry", screenshot=str(screenshot_path),
                            error="compact hand appeared before any observed call",
                            inferredOpenMelds=evaluation.get("openMelds"),
                        )
                        page.wait_for_timeout(max(20, round(self.args.poll * 1000)))
                        continue
                    if evaluation.get("status") == "decision" \
                            and verified_visible_open_melds is not None \
                            and not dynamic_layout_was_required:
                        self.cached_open_melds = verified_visible_open_melds
                        self.dynamic_layout_required = True
                        self.log(
                            "open_hand_recovered",
                            openMelds=verified_visible_open_melds,
                            source="verified_visible_own_melds",
                        )
                elif self.cached_concealed_tiles is not None \
                        and getattr(self, "pending_own_discard", None) is None and not pending_discard:
                    draw_recognition = self.recognize_resident(screenshot_path, draw_only=True)
                    if len(draw_recognition.get("tiles", [])) == 1:
                        recognition = {
                            **draw_recognition,
                            "tiles": [*self.cached_concealed_tiles, draw_recognition["tiles"][0]],
                            "turnReady": True,
                        }
                    else:
                        self.cached_concealed_tiles = None
                        recognition = self.recognize_resident(screenshot_path)
                    evaluation = self.evaluate(
                        screenshot_path, pending_discard, public_observation, recognition,
                        captured_at=evaluation_captured_at,
                    )
                else:
                    recognition = self.recognize_resident(
                        screenshot_path, concealed_only=bool(pending_discard),
                    )
                    evaluation = self.evaluate(
                        screenshot_path, pending_discard, public_observation, recognition,
                        captured_at=evaluation_captured_at,
                    )
                if evaluation.get("status") != "reaction_prompt":
                    reaction_fallback = self.force_auto_riichi_kan_fallback(screenshot_path, evaluation) \
                        or self.force_auto_reaction_fallback(screenshot_path)
                    if reaction_fallback:
                        evaluation = reaction_fallback
                if evaluation.get("status") == "reaction_prompt":
                    try:
                        receipt = self.execute_reaction_pass(
                            page, evaluation, evaluated_captured_at=evaluation_captured_at,
                        )
                    except RetryableSafetyAbort as error:
                        # The pass affordance can disappear before any click.
                        # Re-arm the turn gate so it re-observes the full
                        # hand/river rather than treating the old prompt as a
                        # completed (or failed) action.
                        self.last_processed_hand = None
                        self.armed = True
                        self.log("reaction_pass_deferred", screenshot=str(screenshot_path), error=str(error))
                        time.sleep(self.args.poll)
                        continue
                    except Exception as error:
                        self.last_processed_hand = hand_hash
                        self.armed = False
                        self.log("reaction_pass_failed", screenshot=str(screenshot_path), error=str(error))
                        raise
                    self.log("reaction_prompt", screenshot=str(screenshot_path), evaluation=evaluation, execution=receipt)
                    self.last_processed_hand = hand_hash
                    self.armed = False
                    time.sleep(self.args.poll)
                    continue
                if evaluation.get("status") != "decision":
                    self.last_processed_hand = hand_hash
                    self.log("not_ready", screenshot=str(screenshot_path), evaluation=evaluation)
                    if self.args.max_iterations and iterations >= self.args.max_iterations:
                        return
                    time.sleep(self.args.poll)
                    continue
                try:
                    receipt = self.execute(
                        page, evaluation, evaluated_hand=hand, evaluated_full=evaluation_frame,
                        evaluated_draw_generation=evaluation_draw_generation,
                        evaluated_captured_at=evaluation_captured_at,
                    )
                except SelectionStateUncertainAbort as error:
                    # The first click can have left the evaluated tile raised.
                    # Replaying this hand would make the next click an
                    # unverified deselect, so wait for a separately observed
                    # table transition instead.
                    self.record_replay(evaluation, screenshot_path, execution_error=str(error))
                    self.log(
                        "action_aborted", screenshot=str(screenshot_path), error=str(error),
                        retryable=False, selectionMayRemain=True,
                    )
                    self.selection_uncertainty_latch = {
                        "drawGeneration": evaluation_draw_generation,
                        "ownDiscards": list((public_observation or {}).get("ownDiscards", [])),
                        "abortedAt": datetime.now(timezone.utc).isoformat(),
                    }
                    self.last_processed_hand = hand_hash
                    self.armed = False
                    time.sleep(self.args.poll)
                    continue
                except RetryableSafetyAbort as error:
                    self.record_replay(evaluation, screenshot_path, execution_error=str(error))
                    self.log("action_aborted", screenshot=str(screenshot_path), error=str(error), retryable=True)
                    self.last_processed_hand = None
                    self.armed = True
                    time.sleep(self.args.poll)
                    continue
                except Exception as error:
                    # A click may already have reached the game even if visual
                    # confirmation failed. Disarm this exact hand so the loop
                    # can never retry the action.
                    self.last_processed_hand = hand_hash
                    self.armed = False
                    self.record_replay(evaluation, screenshot_path, execution_error=str(error))
                    raise
                receipt["actionTiming"] = self.action_timing(decision_started_at, clear=True)
                if receipt.get("clicked"):
                    self.reset_ranked_click_budget_expiry_streak()
                evaluation["actionTiming"] = receipt["actionTiming"]
                replay_path = self.record_replay(evaluation, screenshot_path, execution=receipt)
                self.log("decision", screenshot=str(screenshot_path), evaluation=evaluation, execution=receipt)
                self.log("replay_saved", replay=str(replay_path))
                selected_id = evaluation.get("decision", {}).get("selectedActionId")
                selected_action = evaluation.get("decision", {}).get("selectedAction", {}).get("action")
                selected_candidate = next((item for item in evaluation.get("decision", {}).get("candidates", [])
                                           if item.get("actionId") == selected_id), None)
                self.last_shanten = selected_candidate.get("shanten") if selected_candidate else None
                if receipt.get("clicked") and receipt.get("confirmation") == "hand_and_own_river_changed":
                    self.pending_post_call_discard = False
                    self.pending_post_call_started_at = None
                    recognized_tiles = evaluation.get("recognition", {}).get("tiles", [])
                    # A force-auto open-draw fallback can change both the tile
                    # and its physical index after evaluation.
                    click_index = receipt.get("clickIndex", evaluation.get("clickIndex"))
                    discarded_tile = receipt.get("discardedTile") or evaluation.get("decision", {}).get("selectedAction", {}).get("tile")
                    if discarded_tile:
                        self.register_pending_own_discard({
                            "tile": discarded_tile,
                            "opponentMeldsBefore": self.own_discard_meld_snapshot(evaluation),
                            "riichiContext": self.own_discard_riichi_context(evaluation),
                            "riichiDeclaration": selected_action == "riichi" and bool(receipt.get("declaration")),
                            "before": self.own_discard_baseline(evaluation),
                            "evidenceToClickMs": receipt.get("actionTiming", {}).get("evidenceToClickMs"),
                            "clickIndex": click_index,
                            "clickPoint": receipt.get("clickPoint"),
                            "clickedAt": receipt.get("clickedAt"),
                            "confirmation": receipt.get("confirmation"),
                        })
                    if isinstance(click_index, int) and len(recognized_tiles) == 14:
                        self.cached_concealed_tiles = [
                            tile for index, tile in enumerate(recognized_tiles) if index != click_index
                        ]
                        self.cached_open_melds = evaluation.get("openMelds", 0)
                        self.dynamic_layout_required = self.cached_open_melds > 0
                    elif isinstance(click_index, int) and len(recognized_tiles) in {11, 8, 5, 2}:
                        self.cached_concealed_tiles = [
                            tile for index, tile in enumerate(recognized_tiles) if index != click_index
                        ]
                        recognized_open_melds = (14 - len(recognized_tiles)) // 3
                        # Never let a dynamic proposal overwrite the count
                        # established by confirmed call receipts.  That was
                        # how an opponent-turn exposed meld row became the
                        # next two-tile "hand" after a valid two-meld discard.
                        if self.cached_open_melds <= 0:
                            self.cached_open_melds = recognized_open_melds
                        elif recognized_open_melds != self.cached_open_melds:
                            raise RuntimeError(
                                "post-discard recognition changed confirmed open meld count "
                                f"from {self.cached_open_melds} to {recognized_open_melds}"
                            )
                        self.dynamic_layout_required = True
                elif receipt.get("clicked") and selected_action in {"chi", "pon", "minkan", "ankan", "kakan"}:
                    self.cached_concealed_tiles = None
                    self.cached_open_melds = 0
                    self.dynamic_layout_required = True
                self.last_processed_hand = hand_hash
                self.armed = False
            except KeyboardInterrupt:
                raise
            except Exception as error:
                self.log("safety_stop", error=str(error))
                if self.args.stop_on_error:
                    raise
            if self.args.max_iterations and iterations >= self.args.max_iterations:
                return
            time.sleep(self.args.poll)


def find_mahjong_page(browser: Browser) -> Page:
    for context in browser.contexts:
        for page in context.pages:
            if "mahjongsoul.com" in page.url:
                return page
    raise RuntimeError("No Mahjong Soul page found on the CDP browser")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Python-owned Mahjong Soul advisor/Auto operator")
    parser.add_argument("--project", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--screen-references", type=Path,
                        help="calibrated screen-state PNG directory (default: PROJECT/artifacts/live)")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--layout", required=True)
    parser.add_argument("--templates", required=True)
    parser.add_argument("--action-templates", default="", help="calibrated riichi/call/win/pass button templates")
    parser.add_argument("--state", required=True)
    parser.add_argument("--match-length", choices=("east", "south"), default=None,
                        help="explicit verified room format; omit when unknown (not inferred from the current wind)")
    parser.add_argument("--board-metadata", action="store_true",
                        help="require current-frame OCR metadata for evaluation; install requirements-ocr.txt")
    parser.add_argument("--force-auto-click-budget-ms", type=int, default=None,
                        help="explicit recognition+decision budget; 8000 for OCR in 300+0 tests, must fit action deadline")
    parser.add_argument("--env-file", default=".env.local", help="private Jev environment file; use an empty value to disable")
    parser.add_argument("--artifacts", default="artifacts/python-auto")
    parser.add_argument("--snapshot-nonmatch", action="store_true",
                        help="Save one local screenshot per observed non-match state for diagnosis")
    parser.add_argument("--screencast-diagnostic", default=None, metavar="DIRECTORY",
                        help="opt-in asynchronous recording of the first 30 seconds of screencast receipts")
    parser.add_argument("--mode", choices=("observer", "advisor", "auto", "force-auto"), default="advisor",
                        help="force-auto ignores confidence and calibration gates but keeps stability and post-click checks")
    parser.add_argument("--poll", type=float, default=0.1)
    parser.add_argument("--action-deadline-ms", type=int, default=ACTION_DEADLINE_MS,
                        help="verified action deadline; use 300000 only for 300+0 friend-match testing")
    parser.add_argument("--stability-ms", type=int, default=120)
    parser.add_argument("--stability-pixel-delta", type=float, default=1.5)
    parser.add_argument("--action-pixel-delta", type=float, default=3.0)
    parser.add_argument("--river-pixel-delta", type=float, default=1.0)
    parser.add_argument("--confirmation-timeout", type=float, default=8.0)
    parser.add_argument("--terminal-transition-timeout", type=float, default=20.0,
                        help="extra time to confirm a result screen after a terminal discard reveal")
    parser.add_argument("--evaluation-timeout", type=float, default=30.0)
    parser.add_argument("--consensus-frames", type=int, choices=range(2, 6), default=3,
                        help="number of matching fresh hand observations required before clicking")
    parser.add_argument("--max-iterations", type=int, default=0, help="0 keeps watching until interrupted")
    parser.add_argument("--stop-on-error", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--resume-away", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--advance-screens", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--start-reviewed-friend-room", default=None, metavar="PREFLIGHT_PNG",
                        help="start only the friend room matching this manually reviewed preflight")
    parser.add_argument(
        "--public-cache", action=argparse.BooleanOptionalAction, default=True,
        help="recognize dora/rivers/melds asynchronously during opponent turns",
    )
    parser.add_argument(
        "--public-scan-interval", type=float, default=2.0,
        help="seconds between asynchronous dora/public-board refresh attempts",
    )
    parser.add_argument(
        "--ranked-loop", action=argparse.BooleanOptionalAction, default=False,
        help="continuously enter Bronze Room four-player East from lobby/result screens",
    )
    parser.add_argument(
        "--accept-single-call", action=argparse.BooleanOptionalAction, default=True,
        help="in force-auto, accept one unambiguous green chi/pon/kan button and then discard",
    )
    parser.add_argument(
        "--allow-local-discard",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="explicitly allow confidence-gated deterministic discards in advisor mode; no defense/Jev",
    )
    args = parser.parse_args()
    if args.action_templates and not Path(args.action_templates).exists():
        parser.error(f"--action-templates path does not exist: {args.action_templates}")
    if args.ranked_loop and args.match_length == "south":
        parser.error("--ranked-loop selects East rooms; --match-length=south is incompatible")
    if args.action_deadline_ms <= 0:
        parser.error("--action-deadline-ms must be positive")
    return args


def main() -> int:
    args = parse_args()
    try:
        with operator_lease(args.cdp):
            # Acquire before resident recognizers or any Playwright connection.
            operator = PythonAutoOperator(args)
            operator_closed = False
            try:
                with sync_playwright() as playwright:
                    try:
                        browser = playwright.chromium.connect_over_cdp(args.cdp)
                        operator.run(find_mahjong_page(browser))
                    finally:
                        # Stop the screencast while its CDP transport is still
                        # alive, before Playwright tears down its driver.
                        operator_closed = True
                        operator.close()
            except KeyboardInterrupt:
                operator.log("stopped", reason="keyboard_interrupt")
            finally:
                # Entering the Playwright context itself can fail.
                if not operator_closed:
                    operator.close()
    except OperatorAlreadyRunning as error:
        evidence = {"timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": "duplicate_operator_stop", "pid": os.getpid(),
                    "endpoint": endpoint_key(args.cdp), "error": str(error)}
        artifacts = Path(args.artifacts)
        if not artifacts.is_absolute():
            artifacts = Path(args.project).resolve() / artifacts
        artifacts.mkdir(parents=True, exist_ok=True)
        # Keep a rejected startup out of the active operator's game log.
        with (artifacts / "operator-startup.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(evidence) + "\n")
        print(json.dumps(evidence), flush=True)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
