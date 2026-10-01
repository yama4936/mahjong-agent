"""Read-only OCR probe for the calibrated Mahjong Soul center scoreboard."""
import argparse
import json
import re
import copy
from functools import lru_cache
from pathlib import Path

WINDS = {"東": "east", "南": "south", "西": "west", "北": "north"}
SEATS = ["east", "south", "west", "north"]


def remap_seats(value, source_seat: str, target_seat: str):
    """Rotate absolute labels while preserving screen-relative player identity."""
    shift = SEATS.index(target_seat) - SEATS.index(source_seat)
    def visit(item):
        if isinstance(item, list):
            return [visit(child) for child in item]
        if isinstance(item, dict):
            return {key: SEATS[(SEATS.index(child) + shift) % 4]
                    if key in {"seat", "fromSeat"} and child in SEATS else visit(child)
                    for key, child in item.items()}
        return item
    return visit(copy.deepcopy(value))


@lru_cache(maxsize=1)
def ocr_engine():
    from rapidocr import RapidOCR
    return RapidOCR()


def parse_board_tokens(tokens: list[dict], expected_total_points: int = 100000) -> dict:
    def at(x: float, y: float, pattern: str):
        matches = [item for item in tokens if item["confidence"] >= 0.98
                   and abs(item["x"] - x) <= 24 and abs(item["y"] - y) <= 20
                   and re.fullmatch(pattern, item["text"])]
        return matches[0]["text"] if len(matches) == 1 else None

    wind = at(824, 514, "[東南西北]")
    round_text = at(960, 405, "[東南西北][1-4]局")
    if not wind or not round_text:
        return {"verified": False, "reason": "seat_or_round_not_verified"}
    seat = WINDS[wind]
    scores = {}
    # Relative clockwise order: own, right, opposite, left.
    for offset, (x, y) in enumerate([(960, 482), (1047, 419), (958, 364), (876, 423)]):
        text = at(x, y, r"-?\d{3,6}")
        if text is None:
            return {"verified": False, "reason": "four_scores_not_verified"}
        scores[SEATS[(SEATS.index(seat) + offset) % 4]] = int(text)
    remaining = at(959, 443, r"余\d{1,2}")
    riichi_sticks = at(132, 155, r"\d{1,2}")
    honba = at(268, 155, r"\d{1,2}")
    if riichi_sticks is None or honba is None:
        return {"verified": False, "reason": "honba_or_riichi_sticks_not_verified"}
    if sum(scores.values()) + int(riichi_sticks) * 1000 != expected_total_points:
        return {"verified": False, "reason": "scores_and_riichi_sticks_total_mismatch"}
    return {"verified": True, "seat": seat,
            "round": f"{WINDS[round_text[0]]}_{round_text[1]}", "scores": scores,
            "honba": int(honba), "riichiSticks": int(riichi_sticks),
            **({"remainingTiles": int(remaining[1:])} if remaining and int(remaining[1:]) <= 70 else {})}


def recognize_board(image_path: Path) -> dict:
    # Optional dependencies stay outside the live operator until validated.
    from PIL import Image
    image = Image.open(image_path).convert("RGB")
    if image.size != (1920, 1080):
        return {"verified": False, "reason": "uncalibrated_viewport"}
    from screen_state import classify_screen
    state, _ = classify_screen(image_path, {})
    if state != "match":
        return {"verified": False, "reason": "not_gameplay_screen", "screenState": state}
    import numpy as np
    engine = ocr_engine()
    result = engine(np.array(image.crop((780, 310, 1160, 545)).resize((1140, 705))),
                    use_det=True, use_cls=True, use_rec=True)
    tokens = []
    if result.txts is not None:
        for text, confidence, box in zip(result.txts, result.scores, result.boxes):
            center = box.mean(axis=0) / 3 + [780, 310]
            tokens.append({"text": text, "confidence": float(confidence),
                           "x": float(center[0]), "y": float(center[1])})
    # Other seats' scores are rotated. Retry calibrated crops upright only when
    # no high-confidence numeric token exists; retain ambiguity rejection.
    for side, x, y, box, angle in [
        ("left", 876, 423, (859, 371, 891, 474), 90),
        ("right", 1047, 419, (1031, 368, 1063, 471), 270),
        ("opposite", 958, 364, (905, 345, 1015, 383), 180),
    ]:
        side_scores = [token for token in tokens
                       if abs(token["x"] - x) <= 24 and abs(token["y"] - y) <= 20
                       and re.fullmatch(r"-?\d{3,6}", token["text"])]
        # The opposite score is upside down in the full-board OCR crop.  OCR
        # can therefore return a *high-confidence reversed* number (for
        # example ``0086`` for 9800).  Do not let confidence alone suppress
        # the calibrated upright retry for that seat: point conservation is
        # only useful when the orientation is correct.
        needs_upright_retry = side == "opposite" or not any(
            token["confidence"] >= 0.98 for token in side_scores
        )
        if needs_upright_retry:
            upright = image.crop(box).rotate(angle, expand=True)
            # A second aspect ratio recovers short right-seat scores without
            # cropping digits or weakening the confidence/conservation gates.
            for width in ([412, 328] if side == "right" else [412]):
                score = engine(np.array(upright.resize((width, 128))),
                               use_det=False, use_cls=False, use_rec=True)
                if score.txts is not None and len(score.txts) == 1:
                    text, confidence = score.txts[0], float(score.scores[0])
                    tokens.append({"text": text, "confidence": confidence,
                                   "x": x, "y": y, "source": f"upright_{side}_score_crop",
                                   "cropWidth": width})
                    if confidence >= 0.98 and re.fullmatch(r"-?\d{3,6}", text):
                        if side == "opposite":
                            # Prefer the calibrated upright reading over the
                            # full-board token at this location.  Keeping
                            # both makes parse_board_tokens correctly reject
                            # the score as ambiguous, but also prevents a
                            # valid corrected snapshot from being used.
                            tokens[:] = [token for token in tokens
                                         if not (abs(token["x"] - x) <= 24
                                                 and abs(token["y"] - y) <= 20
                                                 and token.get("source") != f"upright_{side}_score_crop")]
                        break
    # The own-seat wind is small and its full-scoreboard detection can be
    # stable but just below the strict 0.98 gate. Retry only the calibrated
    # glyph crop instead of weakening the shared token threshold.
    seat_winds = [token for token in tokens
                  if abs(token["x"] - 824) <= 24 and abs(token["y"] - 514) <= 20
                  and re.fullmatch(r"[東南西北]", token["text"])]
    if not any(token["confidence"] >= 0.98 for token in seat_winds):
        seat_wind = engine(np.array(image.crop((804, 492, 846, 532)).resize((256, 192))),
                           use_det=False, use_cls=False, use_rec=True)
        if seat_wind.txts is not None and len(seat_wind.txts) == 1:
            text, confidence = seat_wind.txts[0], float(seat_wind.scores[0])
            tokens.append({"text": text, "confidence": confidence,
                           "x": 824, "y": 514, "source": "isolated_seat_wind_crop"})
    # Fixed isolated digits avoid confusing the stick icon and multiplication
    # sign with the count; never substitute zero when recognition fails.
    for box, x in [((110, 132, 155, 178), 132), ((250, 132, 285, 178), 268)]:
        counter = engine(np.array(image.crop(box).resize((180, 184))),
                         use_det=False, use_cls=False)
        if counter.txts is not None and len(counter.txts) == 1:
            tokens.append({"text": counter.txts[0], "confidence": float(counter.scores[0]),
                           "x": x, "y": 155})
    parsed = parse_board_tokens(tokens)
    if parsed.get("verified"):
        parsed["riichiSeats"] = recognize_riichi_sticks(image, parsed["seat"])
    return {**parsed, "tokens": tokens,
            "source": str(image_path), "scope": "seat_round_scores_honba_riichi_remaining"}


def recognize_riichi_sticks(image, own_seat: str) -> list[str]:
    """Positive-only evidence from the calibrated white/red HUD sticks."""
    if image.size != (1920, 1080):
        return []
    regions = [
        ((880, 515, 1025, 528), (944, 513, 964, 530)),
        ((1093, 378, 1108, 478), (1090, 415, 1111, 433)),
        ((890, 320, 1035, 333), (955, 318, 975, 338)),
        ((811, 378, 828, 460), (803, 398, 833, 424)),
    ]
    detected = []
    rgb = image.convert("RGB")
    for offset, (body, center) in enumerate(regions):
        pixels = list(rgb.crop(body).getdata())
        white = sum(min(pixel) > 185 and max(pixel) - min(pixel) < 45 for pixel in pixels) / len(pixels)
        red = sum(r > 160 and g < 100 and b < 100 and r - g > 70
                  for r, g, b in rgb.crop(center).getdata())
        if white >= 0.45 and red >= 8:
            detected.append(SEATS[(SEATS.index(own_seat) + offset) % 4])
    return detected


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("screenshot", type=Path)
    print(json.dumps(recognize_board(parser.parse_args().screenshot), ensure_ascii=False))
