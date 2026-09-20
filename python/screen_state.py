from __future__ import annotations

import io
from pathlib import Path
from typing import Literal

from PIL import Image, ImageChops, ImageStat

ScreenState = Literal[
    "login", "account_modal", "lobby", "ranked_menu", "ranked_room",
    "matchmaking", "match", "away", "round_result", "match_result", "exit_confirm", "unknown",
]

REFERENCE_FILES: list[tuple[ScreenState, str]] = [
    ("login", "result-step-1.png"),
    ("account_modal", "login-step-1.png"),
    ("lobby", "lobby-ready.png"),
    ("ranked_menu", "ranked-menu.png"),
    ("ranked_room", "ranked-copper.png"),
    ("matchmaking", "ranked-matchmaking.png"),
    ("match", "login-step-3.png"),
    ("match", "ranked-live-match.png"),
    ("away", "away-dialog.png"),
    ("round_result", "round-result.png"),
    ("match_result", "match-result.png"),
    ("exit_confirm", "exit-dialog.png"),
]


def _open(value: bytes | Path | str) -> Image.Image:
    return Image.open(io.BytesIO(value) if isinstance(value, bytes) else value).convert("RGB")


def _signature(image: Image.Image) -> Image.Image:
    # Compare in the same RGB space. Independent palette quantization can map
    # identical colors to different palette indices and invert nearest states.
    return image.resize((64, 36)).convert("RGB")


def _distance(left: Image.Image, right: Image.Image) -> float:
    mean = ImageStat.Stat(ImageChops.difference(_signature(left), _signature(right))).mean
    return sum(mean) / (3 * 255)


def load_references(directory: Path) -> dict[str, tuple[ScreenState, Image.Image]]:
    return {
        f"{state}:{index}": (state, _open(directory / filename))
        for index, (state, filename) in enumerate(REFERENCE_FILES)
        if (directory / filename).exists()
    }


def classify_screen(
    screenshot: bytes | Path | str,
    references: dict[str, tuple[ScreenState, Image.Image]],
    maximum_distance: float = 0.16,
) -> tuple[ScreenState, float]:
    image = _open(screenshot)
    if not references:
        return "unknown", 0.0
    scored = sorted((_distance(image, reference), state) for state, reference in references.values())
    distance, state = scored[0]
    confidence = max(0.0, 1 - distance / maximum_distance)
    return (state, confidence) if distance <= maximum_distance else ("unknown", 0.0)
