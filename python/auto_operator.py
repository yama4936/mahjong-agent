#!/usr/bin/env python3
"""Fail-closed Mahjong Soul browser operator.

Python owns the browser and all mouse input. The TypeScript process is a pure
frame evaluator: it receives a screenshot and returns structured JSON without
touching the page.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, sync_playwright
from PIL import Image, ImageChops, ImageStat
from screen_state import classify_screen, load_references


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
    allowed = {"TYPESAFE_API_KEY", "JEV_MODEL"}
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


class PythonAutoOperator:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.root = Path(args.project).resolve()
        self.layout_path = Path(args.layout).resolve()
        self.templates = Path(args.templates).resolve()
        self.state_path = Path(args.state).resolve()
        self.public_state = load_json(self.state_path)
        self.layout = load_json(self.layout_path)
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
        self.last_processed_hand: str | None = None
        self.previous_public_observation: dict[str, Any] | None = None
        self.armed = True

    def resume_if_away(self, page: Page) -> bool:
        if not self.args.resume_away:
            return False
        screenshot = page.screenshot(animations="disabled")
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
                 public_observation: dict[str, Any] | None = None) -> dict[str, Any]:
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
        maximum_hand_delta = 0.0
        maximum_river_delta = 0.0
        while time.monotonic() - started < self.args.confirmation_timeout:
            page.wait_for_timeout(100)
            hand_after = page.screenshot(clip=self.hand_clip, animations="disabled")
            river_after = page.screenshot(clip=self.river_clip, animations="disabled")
            hand_delta = mean_pixel_delta(hand_before, hand_after)
            river_delta = mean_pixel_delta(river_before, river_after)
            maximum_hand_delta = max(maximum_hand_delta, hand_delta)
            maximum_river_delta = max(maximum_river_delta, river_delta)
            if hand_delta >= self.args.action_pixel_delta and river_delta >= self.args.river_pixel_delta:
                page.wait_for_timeout(200)
                verification = self.verify_post_discard(
                    page.screenshot(animations="disabled"), before_tiles, click_index,
                )
                if not verification.get("verified"):
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
    ) -> dict[str, Any]:
        region = self.layout.get("actionButtonRegions", {}).get(action)
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

    def execute(self, page: Page, evaluation: dict[str, Any]) -> dict[str, Any]:
        decision = evaluation["decision"]
        recognition = evaluation["recognition"]
        selected = decision.get("selectedAction", {"action": decision.get("recommendedAction", "discard")})
        selected_action = selected.get("action")
        certified_auto = self.args.mode == "auto" and decision.get("executable") is True
        local_auto = local_discard_allowed(self.args, evaluation)
        if not certified_auto and not local_auto:
            return {"clicked": False, "reason": "advisor_or_safety_stop"}
        # Fresh captures must independently reproduce the evaluated ordered
        # hand. Pixel stability alone can leave a stale decision undetected.
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
                raise RuntimeError("fresh frame recognition disagrees with the evaluated hand")
        if not recognition.get("safe") or recognition.get("confidence", 0) < self.layout.get("minimumTileConfidence", 0.98):
            raise RuntimeError("Python recognition safety gate rejected click")
        if certified_auto:
            auto_certificate = self.layout.get("autoOperation")
            if not auto_certificate or auto_certificate.get("enabled") is not True:
                raise RuntimeError("layout has no passing Auto certificate")
        click_index = evaluation.get("clickIndex")
        points = self.layout["clickPoints"]
        needs_tile_click = selected_action in {"discard", "riichi"}
        if needs_tile_click and (not isinstance(click_index, int) or click_index < 0 or click_index >= len(points)):
            raise RuntimeError("evaluator returned an invalid click index")

        # Evaluation can take long enough for Mahjong Soul to show its away
        # dialog. Re-check the full viewport immediately before touching a
        # hand coordinate; resume only, then discard this stale decision.
        if is_away_resume_dialog(page.screenshot(animations="disabled"), self.layout["viewport"]):
            self.resume_if_away(page)
            raise RuntimeError("decision canceled because away dialog appeared during evaluation")

        hand_before = page.screenshot(clip=self.hand_clip, animations="disabled")
        river_before = page.screenshot(clip=self.river_clip, animations="disabled")
        page.wait_for_timeout(120)
        stability_delta = mean_pixel_delta(hand_before, page.screenshot(clip=self.hand_clip, animations="disabled"))
        if stability_delta > self.args.stability_pixel_delta:
            raise RuntimeError("hand changed during Python pre-click stability check")
        if selected_action != "discard":
            button_action = "kan" if selected_action in {"minkan", "ankan"} else selected_action
            observed = self.validate_action_certificate(button_action, evaluation)
            region = self.layout["actionButtonRegions"][button_action]
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
            action_receipt = self.confirm_action_button(page, button_action, button_before, hand_before, meld_before)
            if selected_action != "riichi":
                return {"clicked": True, "policy": "certified_auto", "action": selected_action,
                        "clickPoint": point, **action_receipt}

        point = points[click_index]
        clicked_at = datetime.now(timezone.utc).isoformat()
        self.log(
            "click_sent",
            policy="certified_auto" if certified_auto else "local_discard_only",
            tile=selected.get("tile", decision.get("tile")),
            clickIndex=click_index,
            clickPoint=point,
        )
        send_discard_click(page.mouse, point, self.layout["viewport"])
        receipt = self.confirm_discard(page, hand_before, river_before, recognition["tiles"], click_index)
        return {
            "clicked": True,
            "policy": "certified_auto" if certified_auto else "local_discard_only",
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
        if self.args.mode != "auto":
            return {"clicked": False, "reason": "advisor_or_observer_reaction_prompt"}
        recognition = evaluation.get("recognition", {})
        if not recognition.get("safe") or len(recognition.get("tiles", [])) != 13:
            raise RuntimeError("reaction prompt does not have a safe 13-tile concealed hand")
        observed = self.validate_action_certificate("pass", evaluation)
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
        return {"clicked": True, "policy": "certified_auto", "action": "pass",
                "clickPoint": point, **receipt}

    def run(self, page: Page) -> None:
        self.log("started", mode=self.args.mode, page=page.url)
        iterations = 0
        while True:
            iterations += 1
            if self.args.max_iterations and iterations > self.args.max_iterations:
                return
            try:
                full_screen = page.screenshot(animations="disabled")
                screen_state, screen_confidence = classify_screen(full_screen, self.screen_references)
                if screen_state == "away":
                    if self.resume_if_away(page):
                        time.sleep(self.args.poll)
                        continue
                    # Match and away references share almost the entire table.
                    # The stricter popup/button geometry remains authoritative.
                    screen_state = "match"
                if screen_state in {"round_result", "match_result"}:
                    self.attach_outcome("match" if screen_state == "match_result" else "round", full_screen, screen_confidence)
                    if self.args.advance_screens:
                        y_ratio = 0.92 if screen_state == "match_result" else 0.935
                        point = {"x": self.layout["viewport"]["width"] * 0.91, "y": self.layout["viewport"]["height"] * y_ratio}
                        page.mouse.click(point["x"], point["y"])
                        self.log("screen_advanced", state=screen_state, clickPoint=point)
                        time.sleep(self.args.poll)
                        continue
                if screen_state != "match":
                    self.log("screen_state", state=screen_state, confidence=screen_confidence)
                    time.sleep(self.args.poll)
                    continue
                if self.resume_if_away(page):
                    time.sleep(self.args.poll)
                    continue
                hand = page.screenshot(clip=self.hand_clip, animations="disabled")
                page.wait_for_timeout(self.args.stability_ms)
                hand_second = page.screenshot(clip=self.hand_clip, animations="disabled")
                if mean_pixel_delta(hand, hand_second) > self.args.stability_pixel_delta:
                    self.armed = True
                    time.sleep(self.args.poll)
                    continue
                action_image = page.screenshot(clip=self.action_clip, animations="disabled") if self.action_clip else b""
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
                screenshot_path = self.frames / f"{utc_stamp()}.png"
                screenshot_path.write_bytes(page.screenshot(animations="disabled"))
                public_observation = self.observe_public_board(screenshot_path)
                pending_discard = self.infer_pending_discard(self.previous_public_observation, public_observation)
                if public_observation:
                    self.previous_public_observation = public_observation
                evaluation = self.evaluate(screenshot_path, pending_discard, public_observation)
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
                    receipt = self.execute(page, evaluation)
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
    parser.add_argument("--mode", choices=("observer", "advisor", "auto"), default="advisor")
    parser.add_argument("--poll", type=float, default=0.1)
    parser.add_argument("--stability-ms", type=int, default=120)
    parser.add_argument("--stability-pixel-delta", type=float, default=1.5)
    parser.add_argument("--action-pixel-delta", type=float, default=3.0)
    parser.add_argument("--river-pixel-delta", type=float, default=1.0)
    parser.add_argument("--confirmation-timeout", type=float, default=8.0)
    parser.add_argument("--evaluation-timeout", type=float, default=30.0)
    parser.add_argument("--consensus-frames", type=int, choices=range(2, 6), default=3,
                        help="number of matching fresh hand observations required before clicking")
    parser.add_argument("--max-iterations", type=int, default=0, help="0 keeps watching until interrupted")
    parser.add_argument("--stop-on-error", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--resume-away", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--advance-screens", action=argparse.BooleanOptionalAction, default=False)
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
            browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
