#!/usr/bin/env python3
"""Fail-closed Mahjong Soul browser operator.

Python owns the browser and all mouse input. The TypeScript process is a pure
frame evaluator: it receives a screenshot and returns structured JSON without
touching the page.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, CDPSession, Page, sync_playwright
from PIL import Image, ImageChops, ImageStat
from screen_state import classify_screen, load_references


class RetryableSafetyAbort(RuntimeError):
    """A stale pre-click observation that is safe to reevaluate."""


def utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace(":", "-")


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
        gold = fraction_matching(button_image, lambda red, green, blue: red > 180 and green > 110 and blue < 130)
        dark = fraction_matching(popup_image, lambda red, green, blue: red < 70 and green < 90 and blue < 120)
    return gold >= 0.65 and dark >= 0.75


def is_force_auto_pass_prompt(screenshot: bytes, region: dict[str, float]) -> bool:
    """Recognize the fixed Mahjong Soul skip button without a template set.

    This fallback is restricted to force-auto and is combined with an
    independently recognized 13-tile concealed hand before it can click.
    """
    with Image.open(io.BytesIO(screenshot)) as image:
        button = image.convert("RGB").crop((
            region["x"], region["y"],
            region["x"] + region["width"], region["y"] + region["height"],
        ))
        dark = fraction_matching(button, lambda red, green, blue: red < 80 and green < 90 and blue < 100)
        warm = fraction_matching(button, lambda red, green, blue: red > 120 and green > 95 and blue < 100)
        neutral = fraction_matching(
            button, lambda red, green, blue: abs(red - green) < 25 and red > 110 and blue < 120,
        )
    return dark >= 0.25 and warm >= 0.005 and neutral >= 0.02


def is_force_auto_pass_clip(screenshot: bytes) -> bool:
    with Image.open(io.BytesIO(screenshot)) as image:
        button = image.convert("RGB")
        dark = fraction_matching(button, lambda red, green, blue: red < 80 and green < 90 and blue < 100)
        warm = fraction_matching(button, lambda red, green, blue: red > 120 and green > 95 and blue < 100)
        neutral = fraction_matching(
            button, lambda red, green, blue: abs(red - green) < 25 and red > 110 and blue < 120,
        )
    return dark >= 0.25 and warm >= 0.005 and neutral >= 0.02


def is_contextual_reaction_pass(
    screenshot: bytes, region: dict[str, float], action_button_count: int,
) -> bool:
    """Accept the stylized skip button only beside an independently found action."""
    if action_button_count <= 0:
        return False
    with Image.open(io.BytesIO(screenshot)) as image:
        button = image.convert("RGB").crop((
            region["x"], region["y"],
            region["x"] + region["width"], region["y"] + region["height"],
        ))
        dark = fraction_matching(button, lambda red, green, blue: red < 80 and green < 90 and blue < 100)
        neutral = fraction_matching(
            button, lambda red, green, blue: abs(red - green) < 30 and red > 110 and blue < 125,
        )
    return dark >= 0.25 and neutral >= 0.02


def force_auto_call_buttons(screenshot: bytes, viewport: dict[str, int]) -> list[dict[str, Any]]:
    """Locate green/cyan chi/pon/kan buttons without confusing the hand row."""
    left = round(viewport["width"] * 0.35)
    top = round(viewport["height"] * 0.68)
    right = round(viewport["width"] * 0.75)
    # Reaction buttons end above the concealed hand. Keeping this ROI out of
    # the hand row prevents a cyan pon button from joining bamboo tile ink
    # into one oversized component.
    bottom = round(viewport["height"] * 0.85)
    with Image.open(io.BytesIO(screenshot)) as image:
        pixels = image.convert("RGB")
        groups: list[tuple[str, list[tuple[int, int, int]]]] = []
        # Scan the two button palettes separately. Their glow regions can
        # touch, so a combined color mask would fuse adjacent chi and pon
        # buttons into one apparently unambiguous component.
        for palette in ("green", "cyan"):
            active_columns: list[tuple[int, int, int]] = []
            for x in range(left, right):
                matching_y = []
                for y in range(top, bottom):
                    red, green, blue = pixels.getpixel((x, y))
                    matches = (green > 80 and green - red > 15 and green - blue > 10) \
                        if palette == "green" \
                        else (blue > 80 and green > 80 and min(green, blue) - red > 15 and blue - green > 25)
                    if matches:
                        matching_y.append(y)
                if len(matching_y) >= 5:
                    active_columns.append((x, min(matching_y), max(matching_y)))
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
        if x2 - x1 < viewport["width"] * 0.07 or y2 - y1 < viewport["height"] * 0.04:
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
    return [button for button in buttons if button["width"] >= viewport["width"] * 0.07]


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


def should_process_reaction_prompt(pending_post_call_discard: bool) -> bool:
    """A verified chi/pon must discard before any new reaction is considered."""
    return not pending_post_call_discard


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
    bottom = round(viewport["height"] * 0.875)
    with Image.open(io.BytesIO(screenshot)) as image:
        pixels = image.convert("RGB")
        active_columns: list[tuple[int, int, int]] = []
        for x in range(left, right):
            matching_y = []
            for y in range(top, bottom):
                red, green, blue = pixels.getpixel((x, y))
                if red > 120 and red - green > 25 and green > 55 and green - blue > 15:
                    matching_y.append(y)
            if len(matching_y) >= 5:
                active_columns.append((x, min(matching_y), max(matching_y)))

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
    if not pass_region or not is_force_auto_pass_prompt(screenshot, pass_region):
        return None
    buttons = force_auto_self_action_buttons(screenshot, viewport)
    return buttons[0] if len(buttons) == 1 else None


def is_draw_slot_occupied(screenshot: bytes, region: dict[str, float]) -> bool:
    """Cheaply distinguish our 14-tile turn from an opponent's turn.

    The calibrated draw slot is blue felt while empty and mostly ivory when a
    tile is present.  This guard runs before the expensive tile recognizer.
    """
    with Image.open(io.BytesIO(screenshot)) as image:
        slot = image.convert("RGB").crop((
            region["x"], region["y"],
            region["x"] + region["width"], region["y"] + region["height"],
        ))
        light = fraction_matching(slot, lambda red, green, blue: red > 145 and green > 145 and blue > 135)
    return light >= 0.20


def is_draw_slot_clip_occupied(screenshot: bytes) -> bool:
    with Image.open(io.BytesIO(screenshot)) as image:
        light = fraction_matching(
            image.convert("RGB"), lambda red, green, blue: red > 145 and green > 145 and blue > 135,
        )
    return light >= 0.20


def open_hand_draw_slot(layout: dict[str, Any], open_melds: int) -> dict[str, float] | None:
    """Shift the calibrated closed-hand draw slot by three tiles per open meld."""
    draw_slot = layout.get("drawSlot")
    hand_slots = layout.get("handSlots", [])
    if not draw_slot or open_melds <= 0 or len(hand_slots) < 2:
        return None
    pitches = sorted(
        float(right["x"]) - float(left["x"])
        for left, right in zip(hand_slots, hand_slots[1:])
    )
    pitch = pitches[len(pitches) // 2]
    shifted = {key: float(draw_slot[key]) for key in ("x", "y", "width", "height")}
    shifted["x"] -= open_melds * 3 * pitch
    viewport_width = float(layout.get("viewport", {}).get("width", 0))
    if shifted["x"] < 0 or shifted["x"] + shifted["width"] > viewport_width:
        return None
    return shifted


def geometric_open_meld_count(screenshot: bytes, layout: dict[str, Any]) -> int | None:
    """Infer compact open-hand geometry without trusting tile classifications."""
    hand_slots = layout.get("handSlots", [])
    viewport = layout.get("viewport", {})
    if len(hand_slots) < 13 or not viewport:
        return None
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
        meld_light = fraction_matching(
            meld_image, lambda red, green, blue: red > 145 and green > 145 and blue > 135,
        )
    if meld_light < 0.12:
        return None
    occupied = [is_draw_slot_occupied(screenshot, slot) for slot in hand_slots]
    # Prefer the smallest count: a longer one-meld row is also a prefix of
    # shorter multi-meld layouts. Closed 13-tile rows are rejected by the
    # required empty final calibrated slot.
    for open_melds in range(1, 5):
        concealed_before_draw = 13 - open_melds * 3
        dynamic_slot = open_hand_draw_slot(layout, open_melds)
        if concealed_before_draw < 1 or dynamic_slot is None:
            continue
        if all(occupied[:concealed_before_draw]) \
                and not occupied[-1] \
                and is_draw_slot_occupied(screenshot, dynamic_slot):
            return open_melds
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


def local_discard_allowed(args: argparse.Namespace, evaluation: dict[str, Any]) -> bool:
    decision = evaluation.get("decision", {})
    return bool(
        args.allow_local_discard
        and args.mode == "advisor"
        and decision.get("recommendedAction") == "discard"
        and decision.get("safety", {}).get("allowed") is True
        and decision.get("confidence", 0) >= 0.55
    )


def send_discard_click(mouse: Any, point: dict[str, float], viewport: dict[str, int]) -> None:
    """Select and confirm a Mahjong Soul tile at one guarded coordinate."""
    mouse.click(point["x"], point["y"], click_count=2, delay=80)
    # Once the row closes, the next tile can slide under the pointer and stay
    # raised. Move to inert table felt before post-action recognition.
    mouse.move(viewport["width"] / 2, viewport["height"] * 0.72)


def merge_public_observations(
    previous: dict[str, Any] | None, current: dict[str, Any],
) -> dict[str, Any]:
    """Keep only monotonic river/dora growth across asynchronous snapshots."""
    if previous is None:
        return current

    def growing(prior: list[Any], latest: list[Any]) -> list[Any]:
        return latest if len(latest) >= len(prior) and latest[:len(prior)] == prior else prior

    own_discards = growing(previous.get("ownDiscards", []), current.get("ownDiscards", []))
    dora = growing(previous.get("doraIndicators", []), current.get("doraIndicators", []))
    opponents = []
    for latest in current.get("opponentDiscards", []):
        prior = next((item for item in previous.get("opponentDiscards", [])
                      if item.get("seat") == latest.get("seat")), {})
        opponents.append({
            **latest,
            "discards": growing(prior.get("discards", []), latest.get("discards", [])),
            "riichiDeclared": bool(prior.get("riichiDeclared") or latest.get("riichiDeclared")),
            "melds": latest.get("melds", []) if len(latest.get("melds", [])) >= len(prior.get("melds", []))
            else prior.get("melds", []),
        })
    own_meld_tiles = growing(previous.get("ownMeldTiles", []), current.get("ownMeldTiles", []))
    own_melds = current.get("ownMelds", []) if len(current.get("ownMelds", [])) >= len(previous.get("ownMelds", [])) \
        else previous.get("ownMelds", [])
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
        "ownRiichiDeclared": bool(previous.get("ownRiichiDeclared") or current.get("ownRiichiDeclared")),
        "ownMelds": own_melds,
        "opponentDiscards": opponents,
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
        self.layout_path = Path(args.layout).resolve()
        self.templates = Path(args.templates).resolve()
        self.state_path = Path(args.state).resolve()
        self.public_state = load_json(self.state_path)
        self.layout = load_json(self.layout_path)
        # Live calibration files focus on tiles and may omit static action
        # buttons. Reuse those fixed screen-space regions from the base layout.
        base_layout_path = self.root / "config" / "layout.json"
        if not self.layout.get("actionButtonRegions") and base_layout_path.exists():
            base_layout = load_json(base_layout_path)
            self.layout["actionButtonRegions"] = base_layout.get("actionButtonRegions", {})
        self.evaluator_env = load_secret_environment(self.root, args.env_file)
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
        self.screen_references = load_references(self.root / "artifacts" / "live")
        self.recognition_request_id = 0
        self.recognition_server = subprocess.Popen(
            ["node", "dist/src/recognition/recognitionServer.js", str(self.layout_path), str(self.templates), str(self.state_path)],
            cwd=self.root,
            env=self.evaluator_env,
            text=True,
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
        self.public_recognition_request_id = 0
        self.public_cache_generation = 0
        self.public_cache_last_frame_hash: str | None = None
        self.last_public_scan_at = 0.0
        self.cached_public_observation: dict[str, Any] | None = None
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
        self.previous_public_observation: dict[str, Any] | None = None
        self.cached_concealed_tiles: list[str] | None = None
        self.cached_open_melds = 0
        self.dynamic_layout_required = False
        self.last_shanten: int | None = None
        self.screencast_session: CDPSession | None = None
        self.latest_screencast_frame: bytes | None = None
        self.screencast_sequence = 0
        self.screencast_draw_occupied: bool | None = None
        self.screencast_draw_generation = 0
        self.rejected_screencast_size: tuple[int, int] | None = None
        self.pending_post_call_discard = False
        self.pending_post_call_started_at: float | None = None
        self.restart_open_hand_probe_hash: str | None = None
        self.open_meld_candidate: int | None = None
        self.open_meld_candidate_frames: set[str] = set()
        self.last_ranked_loop_state: str | None = None
        self.last_ranked_loop_click_at = 0.0
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

    def close(self) -> None:
        if self.screencast_session is not None:
            try:
                self.screencast_session.send("Page.stopScreencast")
                self.screencast_session.detach()
            except Exception:
                pass
            self.screencast_session = None
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

    def schedule_public_recognition(self, screenshot: bytes) -> None:
        server = self.public_recognition_server
        if not server or server.poll() is not None:
            return
        if self.public_recognition_thread and self.public_recognition_thread.is_alive():
            return
        frame_hash = perceptual_hash(screenshot)
        if frame_hash == self.public_cache_last_frame_hash:
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
                if not server.stdin or not server.stdout:
                    raise RuntimeError("public recognition server pipes are unavailable")
                server.stdin.write(json.dumps({
                    "id": request_id, "screenshot": str(frame_path), "capturedAt": captured_at,
                    "concealedTiles": self.cached_concealed_tiles,
                    "openMelds": self.cached_open_melds,
                    "seat": self.public_state.get("seat", "east"),
                    "round": self.public_state.get("round", "unknown"),
                }) + "\n")
                server.stdin.flush()
                line = server.stdout.readline()
                if not line:
                    raise RuntimeError("public recognition server closed its output")
                response = json.loads(line)
                if response.get("id") != request_id:
                    raise RuntimeError(f"public recognition response id mismatch: {response}")
                if response.get("error"):
                    raise RuntimeError(response["error"])
                envelope = {"generation": generation, "result": response["result"]}
            except Exception as error:
                envelope = {"generation": generation, "error": str(error)}
            with self.public_recognition_lock:
                self.public_recognition_result = envelope

        self.public_recognition_thread = threading.Thread(target=recognize, daemon=True)
        self.public_recognition_thread.start()

    def schedule_periodic_public_recognition(
        self, screenshot: bytes, *, now: float | None = None,
    ) -> bool:
        """Refresh dora and other public tiles independently of turn state."""
        if not getattr(self.args, "public_cache", False) or not self.public_recognition_server:
            return False
        observed_at = time.monotonic() if now is None else now
        interval = max(0.1, float(getattr(self.args, "public_scan_interval", 2.0)))
        if observed_at - self.last_public_scan_at < interval:
            return False
        self.last_public_scan_at = observed_at
        self.schedule_public_recognition(screenshot)
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
        current = envelope["result"]
        self.cached_public_observation = merge_public_observations(self.cached_public_observation, current)
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

    def start_screencast_gate(self, page: Page) -> None:
        """Stream low-latency frames for the turn gate without CDP screenshots."""
        if self.args.mode != "force-auto" or self.screencast_session is not None:
            return
        session = page.context.new_cdp_session(page)

        def receive_frame(event: dict[str, Any]) -> None:
            try:
                frame = base64.b64decode(event["data"])
                self.accept_screencast_frame(frame)
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
            self.screencast_draw_occupied = None
            if actual != self.rejected_screencast_size:
                self.log("screencast_frame_rejected", expected=list(expected), actual=list(actual))
                self.rejected_screencast_size = actual
            return False
        self.rejected_screencast_size = None
        self.latest_screencast_frame = frame
        draw_slot = self.layout.get("drawSlot")
        if draw_slot:
            occupied = is_draw_slot_clip_occupied(crop_screenshot(frame, draw_slot))
            if occupied and self.screencast_draw_occupied is not True:
                self.screencast_draw_generation += 1
            self.screencast_draw_occupied = occupied
        return True

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

    def restart_screencast_gate(self, page: Page) -> None:
        """Re-subscribe after a viewport override invalidates Chrome's stream."""
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
        self.start_screencast_gate(page)

    def recognize_resident(
        self, screenshot: Path, *, concealed_only: bool = False, draw_only: bool = False,
        concealed_tiles: list[str] | None = None, evaluate_force_auto: bool = False,
        dynamic_layout: bool = False, open_melds: int | None = None,
        public_observation: dict[str, Any] | None = None,
        force_auto_action_buttons: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if self.recognition_server.poll() is not None:
            raise RuntimeError("resident recognition server is not running")
        if not self.recognition_server.stdin or not self.recognition_server.stdout:
            raise RuntimeError("resident recognition server pipes are unavailable")
        self.recognition_request_id += 1
        request_id = self.recognition_request_id
        self.recognition_server.stdin.write(json.dumps({
            "id": request_id,
            "screenshot": str(screenshot),
            "concealedOnly": concealed_only,
            "drawOnly": draw_only,
            "concealedTiles": concealed_tiles,
            "evaluateForceAuto": evaluate_force_auto,
            "dynamicLayout": dynamic_layout,
            "openMelds": open_melds,
            "publicObservation": public_observation,
            "forceAutoActionButtons": force_auto_action_buttons,
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

    def advance_ranked_loop(self, page: Page, state: str, confidence: float) -> bool:
        """Enter or re-enter Bronze Room four-player East after every match."""
        if not self.args.ranked_loop or confidence < 0.25:
            return False
        point = self.ranked_loop_click_point(state, self.layout["viewport"])
        if point is None:
            return False
        now = time.monotonic()
        if state == self.last_ranked_loop_state and now - self.last_ranked_loop_click_at < 1.5:
            return True
        page.mouse.click(point["x"], point["y"])
        self.last_ranked_loop_state = state
        self.last_ranked_loop_click_at = now
        self.log("ranked_loop_advanced", state=state, confidence=confidence, clickPoint=point)
        return True

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
        if not pending:
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
        return count

    def evaluate(self, screenshot: Path, pending_discard: dict[str, str] | None = None,
                 public_observation: dict[str, Any] | None = None,
                 recognition: dict[str, Any] | None = None) -> dict[str, Any]:
        evaluator_mode = "advisor" if self.args.mode == "observer" else self.args.mode
        command = [
            "node", "dist/src/cli.js", "evaluate-frame", str(screenshot),
            str(self.layout_path), str(self.templates), f"--state={self.state_path}",
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
        result = subprocess.run(
            command,
            cwd=self.root,
            env=self.evaluator_env,
            text=True,
            capture_output=True,
            timeout=self.args.evaluation_timeout,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "frame evaluator failed").strip())
        return json.loads(result.stdout)

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
        recognition = self.recognize_resident(screenshot, concealed_only=True)
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
            "recognition": recognition,
            "availableUiActions": ["pass"],
            "actionButton": {
                "action": "pass", "present": True, "confidence": 1,
                "center": point, "source": "force_auto_fixed_geometry",
            },
        }

    def observe_public_board(self, screenshot: Path) -> dict[str, Any] | None:
        command = [
            "node", "dist/src/cli.js", "public-observation", str(screenshot),
            str(self.layout_path), str(self.templates), f"--seat={self.public_state.get('seat', 'east')}",
        ]
        result = subprocess.run(command, cwd=self.root, env=self.evaluator_env, text=True,
                                capture_output=True, timeout=self.args.evaluation_timeout, check=False)
        if result.returncode != 0:
            self.log("public_observation_failed", error=(result.stderr or result.stdout).strip())
            return None
        return json.loads(result.stdout)

    @staticmethod
    def infer_pending_discard(previous: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, str] | None:
        if not previous or not current:
            return None
        additions = []
        for opponent in current.get("opponentDiscards", []):
            prior = next((item for item in previous.get("opponentDiscards", [])
                          if item.get("seat") == opponent.get("seat")), None)
            before = prior.get("discards", []) if prior else []
            after = opponent.get("discards", [])
            if len(after) == len(before) + 1 and after[:-1] == before:
                additions.append({"tile": after[-1], "fromSeat": opponent["seat"]})
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
    ) -> dict[str, Any]:
        region = region_override or self.layout.get("actionButtonRegions", {}).get(action)
        if not region:
            raise RuntimeError(f"layout has no calibrated {action} button region")
        clip = {key: region[key] for key in ("x", "y", "width", "height")}
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

    def execute(
        self, page: Page, evaluation: dict[str, Any], evaluated_hand: bytes | None = None,
        evaluated_full: bytes | None = None, evaluated_draw_generation: int | None = None,
    ) -> dict[str, Any]:
        decision = evaluation["decision"]
        recognition = evaluation["recognition"]
        selected = decision.get("selectedAction", {"action": decision.get("recommendedAction", "discard")})
        selected_action = selected.get("action")
        force_auto = self.args.mode == "force-auto"
        certified_auto = self.args.mode == "auto" and decision.get("executable") is True
        local_auto = local_discard_allowed(self.args, evaluation)
        if not force_auto and not certified_auto and not local_auto:
            return {"clicked": False, "reason": "advisor_or_safety_stop"}
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
                    cwd=self.root, env=self.evaluator_env, text=True, capture_output=True,
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
        current_streamed_hand = crop_screenshot(current_streamed_full, self.hand_clip) \
            if current_streamed_full is not None else None
        streamed_delta = mean_pixel_delta(evaluated_hand, current_streamed_hand) \
            if evaluated_hand is not None and current_streamed_hand is not None else None
        streamed_turn_is_current = bool(
            evaluated_draw_generation is not None
            and getattr(self, "screencast_draw_generation", None) == evaluated_draw_generation
            and streamed_delta is not None
            and streamed_delta <= self.args.stability_pixel_delta
        )
        # Compare screencast JPEG to the newest screencast JPEG. A fresh PNG
        # has a stable ~4-point codec/background delta on the live compact
        # hand and is not a valid stale-frame comparison.
        pre_click_full = current_streamed_full or page.screenshot(animations="disabled")
        if is_away_resume_dialog(pre_click_full, self.layout["viewport"]):
            self.resume_if_away(page, pre_click_full)
            raise RetryableSafetyAbort("decision canceled because away dialog appeared during evaluation")

        hand_before = current_streamed_hand or crop_screenshot(pre_click_full, self.hand_clip)
        if force_auto:
            if evaluated_hand is None:
                raise RuntimeError("force-auto requires the stable evaluated hand image")
            if not streamed_turn_is_current:
                evaluated_delta = mean_pixel_delta(evaluated_hand, hand_before)
                if evaluated_delta > self.args.stability_pixel_delta:
                    raise RetryableSafetyAbort(
                        f"hand changed since evaluation (pixel delta={evaluated_delta:.3f})"
                    )
        river_before = crop_screenshot(pre_click_full, self.river_clip)
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
            button_before = page.screenshot(clip=button_clip, animations="disabled")
            meld_region = self.layout.get("publicTileRegions", {}).get("ownMelds")
            meld_clip = {key: meld_region[key] for key in ("x", "y", "width", "height")} if meld_region else None
            meld_before = page.screenshot(clip=meld_clip, animations="disabled") if button_action in {"chi", "pon", "kan"} and meld_clip else None
            page.wait_for_timeout(120)
            if mean_pixel_delta(button_before, page.screenshot(clip=button_clip, animations="disabled")) > self.args.stability_pixel_delta:
                raise RuntimeError(f"{button_action} button changed during pre-click stability check")
            point = observed["center"]
            self.log("action_click_sent", action=button_action, clickPoint=point)
            page.mouse.click(point["x"], point["y"])
            action_receipt = self.confirm_action_button(
                page, button_action, button_before, hand_before, meld_before,
                region_override=region if force_auto else None,
            )
            if selected_action != "riichi":
                return {"clicked": True, "policy": "certified_auto", "action": selected_action,
                        "clickPoint": point, **action_receipt}

        point = dynamic_click_point if has_dynamic_click_point else points[click_index]
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
        self.log(
            "click_sent",
            policy="force_auto" if force_auto else "certified_auto" if certified_auto else "local_discard_only",
            tile=selected.get("tile", decision.get("tile")),
            clickIndex=click_index,
            clickPoint=point,
        )
        send_discard_click(page.mouse, point, self.layout["viewport"])
        receipt = self.confirm_discard(page, hand_before, river_before, recognition["tiles"], click_index)
        return {
            "clicked": True,
            "policy": "force_auto" if force_auto else "certified_auto" if certified_auto else "local_discard_only",
            "clickIndex": click_index,
            "clickPoint": point,
            "clickedAt": clicked_at,
            **({"declaration": action_receipt} if selected_action == "riichi" else {}),
            **receipt,
        }

    def execute_reaction_pass(self, page: Page, evaluation: dict[str, Any]) -> dict[str, Any]:
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
        before = page.screenshot(clip=button_clip, animations="disabled")
        page.wait_for_timeout(120)
        if mean_pixel_delta(before, page.screenshot(clip=button_clip, animations="disabled")) > self.args.stability_pixel_delta:
            raise RuntimeError("pass button changed during pre-click stability check")
        point = observed["center"]
        self.log("action_click_sent", action="pass", clickPoint=point,
                 availableUiActions=evaluation.get("availableUiActions", []))
        page.mouse.click(point["x"], point["y"])
        receipt = self.confirm_action_button(page, "pass", before)
        return {"clicked": True, "policy": "force_auto" if self.args.mode == "force-auto" else "certified_auto", "action": "pass",
                "clickPoint": point, **receipt}

    def execute_force_auto_call(
        self, page: Page, screenshot: bytes, button: dict[str, Any],
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
        self.log("action_click_sent", action=call_action, clickPoint=point, source="single_call_button")
        sequence_before = self.screencast_sequence
        page.mouse.click(point["x"], point["y"])
        deadline = time.monotonic() + min(3.0, self.args.confirmation_timeout)
        current = screenshot
        while time.monotonic() < deadline:
            page.wait_for_timeout(50)
            if self.screencast_sequence != sequence_before and self.latest_screencast_frame is not None:
                current = self.latest_screencast_frame
                sequence_before = self.screencast_sequence
            else:
                current = page.screenshot(animations="disabled")
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
        self.log("action_click_sent", action="ron", clickPoint=point, source="reaction_win_color")
        page.mouse.click(point["x"], point["y"])
        deadline = time.monotonic() + min(3.0, self.args.confirmation_timeout)
        while time.monotonic() < deadline:
            page.wait_for_timeout(50)
            after = page.screenshot(animations="disabled")
            if not force_auto_reaction_win_button(after, self.layout["viewport"], pass_region):
                self.last_processed_hand = None
                self.armed = True
                return {
                    "clicked": True, "policy": "force_auto", "action": "ron",
                    "clickPoint": point, "confirmation": "reaction_win_button_disappeared",
                }
        raise RetryableSafetyAbort("reaction win button did not disappear after click")

    def run(self, page: Page) -> None:
        self.ensure_viewport(page, force=True)
        self.start_screencast_gate(page)
        if self.args.mode == "force-auto":
            deadline = time.monotonic() + 2
            while self.latest_screencast_frame is None and time.monotonic() < deadline:
                page.wait_for_timeout(25)
            if self.latest_screencast_frame is None:
                self.seed_silent_screencast_gate(page)
        self.log("started", mode=self.args.mode, page=page.url,
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
        while True:
            iterations += 1
            if self.args.max_iterations and iterations > self.args.max_iterations:
                return
            try:
                self.poll_public_recognition()
                # Force-auto quick/exact gates consume the newest completed
                # public snapshot. Establish it before either branch; the
                # non-force path captures synchronously later in the loop.
                public_observation = self.cached_public_observation \
                    if self.args.mode == "force-auto" else None
                self.ensure_viewport(page)
                gate_frame = None
                quick_draw = False
                quick_pass = False
                quick_calls: list[dict[str, Any]] = []
                quick_reaction_win = False
                refreshed_stable_gate = False
                if self.args.mode == "force-auto" and self.layout.get("drawSlot"):
                    if self.screencast_sequence == last_gate_sequence:
                        silent_gate_polls += 1
                        page.wait_for_timeout(max(20, min(100, round(self.args.poll * 1000))))
                        if silent_gate_polls >= 5 and self.refresh_silent_screencast_gate(page):
                            silent_gate_polls = 0
                            refreshed_stable_gate = True
                    else:
                        silent_gate_polls = 0
                    gate_frame = self.latest_screencast_frame
                    gate_content_hash = perceptual_hash(gate_frame) if gate_frame else None
                    if gate_content_hash is not None and gate_content_hash == last_gate_content_hash:
                        unchanged_gate_content_polls += 1
                    else:
                        unchanged_gate_content_polls = 0
                    last_gate_content_hash = gate_content_hash
                    if unchanged_gate_content_polls >= 5 \
                            and self.refresh_silent_screencast_gate(page):
                        gate_frame = self.latest_screencast_frame
                        last_gate_content_hash = perceptual_hash(gate_frame) if gate_frame else None
                        unchanged_gate_content_polls = 0
                        refreshed_stable_gate = True
                    last_gate_sequence = self.screencast_sequence
                    restart_open_melds = self.verified_visible_open_melds(
                        self.cached_public_observation,
                    )
                    geometric_open_melds = geometric_open_meld_count(gate_frame, self.layout) \
                        if gate_frame else None
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
                    dynamic_draw_slot = open_hand_draw_slot(self.layout, gate_open_melds or 0)
                    dynamic_draw_occupied = bool(
                        gate_frame and dynamic_draw_slot
                        and is_draw_slot_occupied(gate_frame, dynamic_draw_slot)
                    )
                    restart_probe_hash = perceptual_hash(crop_screenshot(gate_frame, self.hand_clip)) \
                        if gate_frame and restart_open_melds is not None else None
                    restart_open_hand_probe = restart_probe_hash is not None \
                        and restart_probe_hash != self.restart_open_hand_probe_hash
                    quick_draw = self.screencast_draw_occupied is True \
                        or dynamic_draw_occupied \
                        or self.pending_post_call_discard or restart_open_hand_probe
                    pass_region = self.layout.get("actionButtonRegions", {}).get("pass")
                    quick_self_actions: list[dict[str, Any]] = []
                    if gate_frame and pass_region and not self.pending_post_call_discard:
                        quick_calls = force_auto_call_buttons(gate_frame, self.layout["viewport"])
                        quick_self_actions = force_auto_self_action_buttons(
                            gate_frame, self.layout["viewport"],
                        )
                        quick_pass = is_force_auto_pass_clip(crop_screenshot(gate_frame, pass_region)) \
                            or is_contextual_reaction_pass(
                                gate_frame, pass_region, len(quick_calls) + len(quick_self_actions),
                            )
                    if gate_frame and quick_pass and not self.pending_post_call_discard:
                        # Reaction prompts are independent of the draw-slot
                        # gate and must be inspected on every streamed frame.
                        quick_reaction_win = force_auto_reaction_win_button(
                            gate_frame, self.layout["viewport"], pass_region,
                        ) is not None or bool(quick_self_actions)
                    draw_gate_streak = draw_gate_streak + 1 if quick_draw else 0
                    pass_gate_streak = pass_gate_streak + 1 if quick_pass else 0
                    call_gate_streak = call_gate_streak + 1 if quick_calls else 0
                    reaction_win_gate_streak = reaction_win_gate_streak + 1 if quick_reaction_win else 0
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
                    # The small regions are the latency-critical turn gate.
                    # Keep a periodic full frame for away/result handling.
                    if not quick_draw and not quick_pass and not quick_calls and not quick_reaction_win and iterations % 10:
                        page.wait_for_timeout(max(20, round(self.args.poll * 1000)))
                        continue
                full_screen = gate_frame or page.screenshot(animations="disabled")
                draw_slot_heuristic_occupied = False
                screen_state, screen_confidence = classify_screen(full_screen, self.screen_references)
                if screen_state == "away":
                    if self.resume_if_away(page, full_screen):
                        time.sleep(self.args.poll)
                        continue
                    # Match and away references share almost the entire table.
                    # The stricter popup/button geometry remains authoritative.
                    screen_state = "match"
                if screen_state in {"round_result", "match_result"}:
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
                    self.public_cache_generation += 1
                    self.public_cache_last_frame_hash = None
                    self.cached_public_observation = None
                    self.last_shanten = None
                    self.last_processed_hand = None
                    self.armed = True
                    self.attach_outcome("match" if screen_state == "match_result" else "round", full_screen, screen_confidence)
                    if self.args.advance_screens:
                        y_ratio = 0.92 if screen_state == "match_result" else 0.935
                        point = {"x": self.layout["viewport"]["width"] * 0.91, "y": self.layout["viewport"]["height"] * y_ratio}
                        page.mouse.click(point["x"], point["y"])
                        self.log("screen_advanced", state=screen_state, clickPoint=point)
                        time.sleep(self.args.poll)
                        continue
                if self.advance_ranked_loop(page, screen_state, screen_confidence):
                    page.wait_for_timeout(max(100, round(self.args.poll * 1000)))
                    continue
                if screen_state != "match" and self.args.mode != "force-auto":
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
                self.schedule_periodic_public_recognition(full_screen)
                if self.args.mode == "force-auto":
                    pass_region = self.layout.get("actionButtonRegions", {}).get("pass")
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
                    )
                    if has_reaction_prompt:
                        screenshot_path = self.frames / f"{utc_stamp()}.png"
                        screenshot_path.write_bytes(full_screen)
                        reaction_win = force_auto_reaction_win_button(
                            full_screen, self.layout["viewport"], pass_region,
                        )
                        if reaction_win is None and len(orange_buttons) == 1:
                            reaction_win = {**orange_buttons[0], "source": "contextual_reaction_prompt"}
                        if reaction_win:
                            receipt = self.execute_force_auto_reaction_win(page, full_screen, reaction_win)
                            self.log("reaction_win", screenshot=str(screenshot_path), execution=receipt)
                            time.sleep(self.args.poll)
                            continue
                        if getattr(self.args, "accept_single_call", False) and len(call_buttons) == 1:
                            try:
                                receipt = self.execute_force_auto_call(page, full_screen, call_buttons[0])
                            except RetryableSafetyAbort as error:
                                self.log("reaction_call_unconfirmed", screenshot=str(screenshot_path), error=str(error))
                                page.wait_for_timeout(max(100, round(self.args.poll * 1000)))
                                continue
                            self.log("reaction_call", screenshot=str(screenshot_path), execution=receipt)
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
                            receipt = self.execute_reaction_pass(page, reaction)
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
                        self.schedule_periodic_public_recognition(full_screen)
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
                    evaluation_frame = gate_frame
                    hand = crop_screenshot(evaluation_frame, self.hand_clip)
                    action_image = crop_screenshot(evaluation_frame, self.action_clip) if self.action_clip else b""
                else:
                    hand = page.screenshot(clip=self.hand_clip, animations="disabled")
                    page.wait_for_timeout(self.args.stability_ms)
                    hand_second = page.screenshot(clip=self.hand_clip, animations="disabled")
                    if mean_pixel_delta(hand, hand_second) > self.args.stability_pixel_delta:
                        self.armed = True
                        time.sleep(self.args.poll)
                        continue
                    action_image = page.screenshot(clip=self.action_clip, animations="disabled") if self.action_clip else b""
                    evaluation_frame = page.screenshot(animations="disabled")
                evaluation_draw_generation = self.screencast_draw_generation if self.screencast_session else None
                hand_hash = hashlib.sha256((perceptual_hash(hand) + (perceptual_hash(action_image) if action_image else "")).encode()).hexdigest()
                if not self.armed:
                    if hand_hash == self.last_processed_hand:
                        time.sleep(self.args.poll)
                        continue
                    self.armed = True
                    self.log("rearmed", reason="hand_region_changed")
                if hand_hash == self.last_processed_hand:
                    time.sleep(self.args.poll)
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
                    exact_draw_slot = open_hand_draw_slot(self.layout, exact_open_melds or 0) \
                        or self.layout["drawSlot"]
                    exact_draw_occupied = is_draw_slot_occupied(evaluation_frame, exact_draw_slot)
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
                        concealed = self.recognize_resident(screenshot_path, concealed_only=True)
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
                            time.sleep(self.args.poll)
                            continue
                    if not draw_slot_heuristic_occupied:
                        self.log("self_turn_detected", screenshot=str(screenshot_path),
                                 source="evaluated_frame_draw_slot_pixels")
                self.poll_public_recognition()
                # Force-auto never waits for public recognition on our turn;
                # it consumes the newest completed opponent-turn snapshot.
                if self.args.mode != "force-auto":
                    public_observation = self.observe_public_board(screenshot_path)
                pending_discard = None if self.args.mode == "force-auto" \
                    else self.infer_pending_discard(self.previous_public_observation, public_observation)
                if public_observation and self.args.mode != "force-auto":
                    self.previous_public_observation = public_observation
                if self.args.mode == "force-auto" and not pending_discard:
                    self_action_buttons = force_auto_self_action_buttons(
                        evaluation_frame, self.layout["viewport"],
                    )
                    dynamic_layout_was_required = self.dynamic_layout_required
                    try:
                        evaluation = self.recognize_resident(
                            screenshot_path,
                            draw_only=self.cached_concealed_tiles is not None,
                            concealed_tiles=self.cached_concealed_tiles,
                            evaluate_force_auto=True,
                            dynamic_layout=self.dynamic_layout_required,
                            open_melds=self.cached_open_melds if self.cached_open_melds > 0 else None,
                            public_observation=public_observation,
                            force_auto_action_buttons=self_action_buttons,
                        )
                    except RuntimeError as initial_error:
                        self.cached_concealed_tiles = None
                        self.cached_open_melds = 0
                        try:
                            evaluation = self.recognize_resident(
                                screenshot_path, evaluate_force_auto=True, dynamic_layout=True,
                                open_melds=self.cached_open_melds if self.cached_open_melds > 0 else None,
                                public_observation=public_observation,
                                force_auto_action_buttons=self_action_buttons,
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
                    inferred_open_melds = evaluation.get("openMelds", 0)
                    verified_visible_open_melds = self.verified_visible_open_meld_count(
                        inferred_open_melds, public_observation,
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
                elif self.cached_concealed_tiles is not None and not pending_discard:
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
                    evaluation = self.evaluate(screenshot_path, pending_discard, public_observation, recognition)
                else:
                    recognition = self.recognize_resident(
                        screenshot_path, concealed_only=bool(pending_discard),
                    )
                    evaluation = self.evaluate(screenshot_path, pending_discard, public_observation, recognition)
                if evaluation.get("status") != "reaction_prompt":
                    reaction_fallback = self.force_auto_reaction_fallback(screenshot_path)
                    if reaction_fallback:
                        evaluation = reaction_fallback
                if evaluation.get("status") == "reaction_prompt":
                    try:
                        receipt = self.execute_reaction_pass(page, evaluation)
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
                    )
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
                    click_index = evaluation.get("clickIndex")
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
                        self.cached_open_melds = evaluation.get("openMelds", (14 - len(recognized_tiles)) // 3)
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
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--layout", required=True)
    parser.add_argument("--templates", required=True)
    parser.add_argument("--action-templates", default="", help="calibrated riichi/call/win/pass button templates")
    parser.add_argument("--state", required=True)
    parser.add_argument("--env-file", default=".env.local", help="private Jev environment file; use an empty value to disable")
    parser.add_argument("--artifacts", default="artifacts/python-auto")
    parser.add_argument("--mode", choices=("observer", "advisor", "auto", "force-auto"), default="advisor",
                        help="force-auto ignores confidence and calibration gates but keeps stability and post-click checks")
    parser.add_argument("--poll", type=float, default=0.1)
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    operator = PythonAutoOperator(args)
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp)
        try:
            operator.run(find_mahjong_page(browser))
        except KeyboardInterrupt:
            operator.log("stopped", reason="keyboard_interrupt")
        finally:
            operator.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
