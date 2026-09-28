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


def parse_board_tokens(tokens: list[dict]) -> dict:
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
    result = engine(np.array(image.crop((780, 310, 1160, 545)).resize((1140, 705))))
    tokens = []
    if result.txts is not None:
        for text, confidence, box in zip(result.txts, result.scores, result.boxes):
            center = box.mean(axis=0) / 3 + [780, 310]
            tokens.append({"text": text, "confidence": float(confidence),
                           "x": float(center[0]), "y": float(center[1])})
    # Fixed isolated digits avoid confusing the stick icon and multiplication
    # sign with the count; never substitute zero when recognition fails.
    for box, x in [((110, 132, 155, 178), 132), ((250, 132, 285, 178), 268)]:
        counter = engine(np.array(image.crop(box).resize((180, 184))),
                         use_det=False, use_cls=False)
        if counter.txts is not None and len(counter.txts) == 1:
            tokens.append({"text": counter.txts[0], "confidence": float(counter.scores[0]),
                           "x": x, "y": 155})
    return {**parse_board_tokens(tokens), "tokens": tokens,
            "source": str(image_path), "scope": "seat_round_scores_honba_riichi_remaining"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("screenshot", type=Path)
    print(json.dumps(recognize_board(parser.parse_args().screenshot), ensure_ascii=False))
