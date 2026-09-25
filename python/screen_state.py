from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from typing import Literal

from PIL import Image, ImageChops, ImageStat

ScreenState = Literal[
    "login", "account_modal", "session_conflict", "connection_error", "lobby", "ranked_menu", "ranked_room",
    "matchmaking", "match", "away", "round_result", "match_result", "rank_progress",
    "post_match_reward", "exit_confirm", "unknown",
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


def _is_session_conflict(image: Image.Image) -> bool:
    """Match the static login-conflict dialog, ignoring the changing table behind it."""
    return _matches_blocking_dialog(image, _blocking_dialog_reference("session-conflict.png"))


def _matches_blocking_dialog(image: Image.Image, reference: Image.Image | None) -> bool:
    if reference is None or image.width / max(1, image.height) < 1.6:
        return False
    if image.size != reference.size:
        return False
    box = (image.width * .35, image.height * .4, image.width * .65, image.height * .69)
    return _distance(image.crop(box), reference.crop(box)) < .035


@lru_cache(maxsize=2)
def _blocking_dialog_reference(filename: str) -> Image.Image | None:
    path = Path(__file__).resolve().parent.parent / "artifacts" / "live" / filename
    return _open(path) if path.exists() else None


def _is_round_result_summary(image: Image.Image) -> bool:
    """Detect the score-transfer summary by its bottom-right confirm button.

    The table behind this overlay changes substantially with every finished
    hand, so a whole-frame nearest-reference comparison is unreliable.
    """
    width, height = image.size
    region = image.crop((width * 0.859, height * 0.88, width * 0.964, height * 0.968)).convert("RGB")
    pixels = list(region.getdata())
    blue = sum(1 for red, green, value in pixels if value > 70 and value > red * 0.75 and red < 120) / max(1, len(pixels))
    bright = sum(1 for red, green, value in pixels if red > 150 and green > 130 and value < 140) / max(1, len(pixels))
    return 0.25 <= blue <= 0.75 and bright >= 0.05


def _is_ranked_match_result(image: Image.Image) -> bool:
    """Detect the four-place result board plus its yellow confirm button."""
    width, height = image.size
    if width < 1200 or height < 700:
        return False
    button = image.crop((width * 0.84, height * 0.88, width * 0.98, height * 0.97)).convert("RGB")
    pixels = list(button.getdata())
    yellow = sum(1 for red, green, blue in pixels if red > 180 and green > 130 and blue < 120) / max(1, len(pixels))
    board = image.crop((width * 0.42, height * 0.16, width * 0.94, height * 0.87)).convert("RGB")
    board_pixels = list(board.getdata())
    dark = sum(1 for pixel in board_pixels if max(pixel) < 100) / max(1, len(board_pixels))
    white = sum(1 for pixel in board_pixels if min(pixel) > 180) / max(1, len(board_pixels))
    return yellow >= 0.25 and dark >= 0.25 and white >= 0.03


def _is_rank_progress(image: Image.Image) -> bool:
    """Detect the post-result rank gauge and its second confirm button.

    This overlay shares the darkened ranked-room background with matchmaking,
    so require both the yellow confirmation control and the cyan circular gauge.
    """
    width, height = image.size
    if width < 1200 or height < 700:
        return False
    button = image.crop((width * 0.84, height * 0.88, width * 0.98, height * 0.97)).convert("RGB")
    button_pixels = list(button.getdata())
    yellow = sum(
        1 for red, green, blue in button_pixels if red > 180 and green > 130 and blue < 120
    ) / max(1, len(button_pixels))
    gauge = image.crop((width * 0.70, height * 0.30, width * 0.89, height * 0.67)).convert("RGB")
    gauge_pixels = list(gauge.getdata())
    cyan = sum(
        1 for red, green, blue in gauge_pixels
        if green > 100 and blue > 120 and blue - red > 30 and green - red > 20
    ) / max(1, len(gauge_pixels))
    return yellow >= 0.25 and cyan >= 0.025


def _is_post_match_reward(image: Image.Image) -> bool:
    """Detect the achievement reward overlay by its paired action buttons."""
    width, height = image.size
    if width < 1200 or height < 700:
        return False
    confirm = image.crop((width * 0.84, height * 0.88, width * 0.98, height * 0.97)).convert("RGB")
    confirm_pixels = list(confirm.getdata())
    yellow = sum(
        1 for red, green, blue in confirm_pixels if red > 180 and green > 130 and blue < 120
    ) / max(1, len(confirm_pixels))
    replay = image.crop((width * 0.68, height * 0.88, width * 0.83, height * 0.97)).convert("RGB")
    replay_pixels = list(replay.getdata())
    blue = sum(
        1 for red, green, value in replay_pixels
        if value > 100 and value > red * 1.2 and value > green * 0.8 and red < 130
    ) / max(1, len(replay_pixels))
    return yellow >= 0.25 and blue >= 0.40


def _is_cherry_blossom_lobby(image: Image.Image) -> bool:
    """Recognize the current WQHD lobby from its three stacked mode panels."""
    width, height = image.size
    if width < 1200 or height < 700 or width / max(1, height) < 1.6:
        return False
    panels = (
        (0.56, 0.22, 0.89, 0.42),
        (0.56, 0.43, 0.89, 0.63),
        (0.56, 0.64, 0.89, 0.84),
    )
    evidence = []
    for left, top, right, bottom in panels:
        region = image.crop((width * left, height * top, width * right, height * bottom)).convert("RGB")
        pixels = list(region.getdata())
        dark = sum(1 for pixel in pixels if max(pixel) < 100) / max(1, len(pixels))
        white_ink = sum(1 for pixel in pixels if min(pixel) > 180 and max(pixel) - min(pixel) < 60) / max(1, len(pixels))
        evidence.append(dark >= 0.10 and white_ink >= 0.04)
    return all(evidence)


def _is_cherry_blossom_ranked_menu(image: Image.Image) -> bool:
    """Recognize the stacked dark-blue ranked-room panels on the current skin."""
    width, height = image.size
    if width < 1200 or height < 700:
        return False
    panels = (
        (0.59, 0.31, 0.86, 0.45),
        (0.59, 0.47, 0.86, 0.61),
        (0.59, 0.63, 0.86, 0.77),
    )
    dark_fractions = []
    for left, top, right, bottom in panels:
        pixels = list(image.crop((width * left, height * top, width * right, height * bottom)).convert("RGB").getdata())
        dark_fractions.append(sum(1 for pixel in pixels if max(pixel) < 100) / max(1, len(pixels)))
    return all(fraction >= 0.45 for fraction in dark_fractions)


def _is_cherry_blossom_matchmaking(image: Image.Image) -> bool:
    """Detect the bottom-left reservation card before generic ranked menu."""
    if not _is_cherry_blossom_ranked_menu(image):
        return False
    width, height = image.size
    region = image.crop((width * 0.01, height * 0.82, width * 0.29, height * 0.99)).convert("RGB")
    pixels = list(region.getdata())
    dark = sum(1 for pixel in pixels if max(pixel) < 100) / max(1, len(pixels))
    return dark >= 0.65


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
    if _is_round_result_summary(image):
        return "round_result", 1.0
    if _is_post_match_reward(image):
        return "post_match_reward", 1.0
    if _is_rank_progress(image):
        return "rank_progress", 1.0
    if _is_ranked_match_result(image):
        return "match_result", 1.0
    if _is_session_conflict(image):
        return "session_conflict", 1.0
    if _matches_blocking_dialog(image, _blocking_dialog_reference("connection-error.png")):
        return "connection_error", 1.0
    if _is_cherry_blossom_matchmaking(image):
        return "matchmaking", 1.0
    if _is_cherry_blossom_ranked_menu(image):
        return "ranked_menu", 1.0
    if _is_cherry_blossom_lobby(image):
        return "lobby", 1.0
    if not references:
        return "unknown", 0.0
    scored = sorted((_distance(image, reference), state) for state, reference in references.values())
    distance, state = scored[0]
    confidence = max(0.0, 1 - distance / maximum_distance)
    return (state, confidence) if distance <= maximum_distance else ("unknown", 0.0)
