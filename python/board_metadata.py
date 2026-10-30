"""Read-only OCR probe for the calibrated Mahjong Soul center scoreboard."""
import argparse
import json
import re
import copy
from functools import lru_cache
from pathlib import Path

WINDS = {"東": "east", "南": "south", "西": "west", "北": "north"}
SEATS = ["east", "south", "west", "north"]


def sanma_seats_by_screen_position(own_seat: str) -> dict[str, str]:
    """Map observed sanma positions to winds; this is not screen recognition.

    Input is an independently established current own seat. No right-hand
    player exists. This mapping is not connected to the live OCR/operator.
    """
    seats = ("east", "south", "west")
    if not isinstance(own_seat, str) or own_seat not in seats:
        raise ValueError("Sanma own seat must be east, south or west")
    index = seats.index(own_seat)
    return {"own": own_seat, "left": seats[(index - 1) % 3],
            "opposite": seats[(index + 1) % 3]}


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


def recognize_remaining_count(image_path: Path) -> int | None:
    """Read the calibrated wall counter independently; never guess on failure."""
    import numpy as np
    from PIL import Image
    with Image.open(image_path) as source:
        if source.size != (1920, 1080):
            return None
        crop = source.convert("RGB").crop((923, 429, 995, 455)).resize((288, 104))
    result = ocr_engine()(np.array(crop), use_det=False, use_cls=False, use_rec=True)
    if result.txts is None or len(result.txts) != 1 or float(result.scores[0]) < 0.98:
        return None
    match = re.fullmatch(r"余(\d{1,2})", result.txts[0])
    if not match or int(match.group(1)) > 70:
        return None
    return int(match.group(1))


def recognize_round_counters(image_path: Path) -> tuple[int, int] | None:
    """Independently verify the riichi-stick and honba counts, in that order."""
    import numpy as np
    from PIL import Image
    with Image.open(image_path) as source:
        if source.size != (1920, 1080):
            return None
        image = source.convert("RGB")
    counts = []
    for box in ((110, 132, 155, 178), (250, 132, 285, 178)):
        result = ocr_engine()(np.array(image.crop(box).resize((180, 184))),
                              use_det=False, use_cls=False, use_rec=True)
        if result.txts is None or len(result.txts) != 1 or len(result.scores) != 1 \
                or float(result.scores[0]) < 0.98 or not re.fullmatch(r"\d{1,2}", result.txts[0]):
            return None
        counts.append(int(result.txts[0]))
    return counts[0], counts[1]


def recognize_score(image_path: Path, position: str) -> int | None:
    """Read one calibrated score upright; reject ambiguous OCR."""
    import numpy as np
    from PIL import Image
    geometry = {
        "own": ((905, 456, 1015, 500), 0),
        "right": ((1031, 368, 1063, 471), 270),
        "opposite": ((905, 345, 1015, 383), 180),
        "left": ((859, 371, 891, 474), 90),
    }
    if position not in geometry:
        return None
    with Image.open(image_path) as source:
        if source.size != (1920, 1080):
            return None
        box, angle = geometry[position]
        upright = source.convert("RGB").crop(box).rotate(angle, expand=True)
    def read(width: int) -> int | None:
        result = ocr_engine()(np.array(upright.resize((width, 128))),
                              use_det=False, use_cls=False, use_rec=True)
        if (result.txts is None or len(result.txts) != 1
                or result.scores is None or len(result.scores) != 1):
            return None
        try:
            confidence = float(result.scores[0])
        except (TypeError, ValueError, OverflowError):
            return None
        text = result.txts[0]
        if (not 0.98 <= confidence <= 1.0 or not isinstance(text, str)
                or not re.fullmatch(r"-?\d{3,6}", text)):
            return None
        return int(text)

    primary = read(412)
    if primary is not None or position != "left":
        return primary
    # Turn highlights can lower the left crop's confidence at one aspect
    # ratio. Recover only when two bounded retries independently agree at
    # the original confidence threshold; never substitute a cached number.
    retries = [read(width) for width in (360, 480)]
    return retries[0] if retries[0] is not None and retries[0] == retries[1] else None


def recognize_right_score(image_path: Path) -> int | None:
    """Read the calibrated right-hand score; reject ambiguous OCR."""
    return recognize_score(image_path, "right")


def parse_board_tokens(tokens: list[dict], expected_total_points: int = 100000) -> dict:
    def at(x: float, y: float, pattern: str, minimum_confidence: float = 0.98):
        matches = [item for item in tokens if item["confidence"] >= minimum_confidence
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
        # A player can be at exactly zero points.  OCR assigns a slightly
        # lower confidence to this single glyph than to multi-digit scores;
        # admit it only at this tightly calibrated HUD position.  The four
        # score conservation check below remains mandatory, so a 1000+ score
        # misread as zero cannot become a verified board.
        text = at(x, y, r"-?\d{3,6}")
        if text is None:
            # Keep the normal 0.98 ambiguity gate for every multi-digit
            # score.  The narrowly lower gate applies only to the lone zero
            # glyph, not to a competing low-confidence numeric reading.
            text = at(x, y, r"0", 0.95)
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


def recognize_board(image_path: Path, *, sanma_compact_candidate: bool = False) -> dict:
    # Optional dependencies stay outside the live operator until validated.
    from PIL import Image
    image = Image.open(image_path).convert("RGB")
    if image.size != (1920, 1080):
        return {"verified": False, "reason": "uncalibrated_viewport"}
    from screen_state import classify_screen
    state, _ = classify_screen(image_path, {})
    # Opt-in OCR candidate only: a saved sanma three-meld hand missed the
    # ordinary gameplay gate by 0.00057 dark-ink fraction despite visible
    # faces. This does not alter screen classification or authorize actions.
    compact_candidate = False
    if sanma_compact_candidate and state == "unknown":
        pixels = list(image.crop((1920 * .115, 1080 * .87, 1920 * .30, 1080 * .97)).getdata())
        white = sum(min(p) > 130 and max(p) - min(p) < 60 for p in pixels) / len(pixels)
        ink = sum(max(p) < 100 for p in pixels) / len(pixels)
        compact_candidate = white >= .70 and .018 <= ink < .02
    if state != "match" and not compact_candidate:
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
    if compact_candidate:
        parsed = {**parsed, "verified": False, "reason": "sanma_compact_screen_unverified"}
    return {**parsed, "tokens": tokens,
            "source": str(image_path), "scope": "seat_round_scores_honba_riichi_remaining",
            **({"screenEvidence": "sanma_compact_candidate"} if compact_candidate else {})}


def reconcile_riichi_metadata(previous: dict | None, current: dict) -> dict:
    """Preserve declarations and infer only conserved 1000-point stick payments."""
    result = {**current, "riichiSeats": list(current.get("riichiSeats", [])),
              "riichiScoreDeclarations": []}

    def valid(snapshot):
        scores = snapshot.get("scores", {})
        sticks = snapshot.get("riichiSticks")
        return (snapshot.get("verified") is True and snapshot.get("seat") in SEATS
                and snapshot.get("round") is not None and type(snapshot.get("honba")) is int
                and isinstance(scores, dict) and set(scores) == set(SEATS)
                and all(type(value) is int for value in scores.values())
                and type(sticks) is int and 0 <= sticks <= 99
                and sum(scores.values()) + sticks * 1000 == 100000)

    if previous is None or not valid(previous) or not valid(current) \
            or any(previous.get(key) != current.get(key) for key in ("seat", "round", "honba")):
        return result
    changes = {seat: current["scores"][seat] - previous["scores"][seat] for seat in SEATS}
    stick_change = current["riichiSticks"] - previous["riichiSticks"]
    declarations = [seat for seat, change in changes.items() if change == -1000]
    payment = (stick_change > 0 and len(declarations) == stick_change
               and all(change in (0, -1000) for change in changes.values()))
    unchanged = stick_change == 0 and all(change == 0 for change in changes.values())
    if payment or unchanged:
        result["riichiSeats"] = [seat for seat in SEATS if seat in {
            *previous.get("riichiSeats", []), *current.get("riichiSeats", []),
            *(declarations if payment else []),
        }]
        result["riichiScoreDeclarations"] = declarations if payment else []
    return result


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


def validate_sanma_board_consistency(snapshot: dict, *, expected_total_points: int | None,
                                     payment_phase: str | None) -> dict:
    """Check supplied sanma metadata, not OCR accuracy or screen identity.

    ``settled`` means both scores and riichi-stick count reflect all completed
    transfers for this same instant. In-flight or unknown phases are not
    certifiable. ``expected_total_points`` includes outstanding deposits and
    must come from independently reviewed room settings. This function is not
    connected to the operator or its four-seat OCR path.
    """
    if type(expected_total_points) is not int or expected_total_points <= 0:
        return {"consistent": False, "reason": "expected_total_points_unknown"}
    if payment_phase != "settled":
        return {"consistent": False, "reason": "payment_phase_not_settled"}
    if not isinstance(snapshot, dict):
        return {"consistent": False, "reason": "invalid_snapshot"}
    seats = ("east", "south", "west")
    if snapshot.get("seat") not in seats:
        return {"consistent": False, "reason": "seat_not_verified"}
    round_name = snapshot.get("round")
    if not isinstance(round_name, str) or not re.fullmatch(r"(?:east|south|west|north)_[1-3]", round_name):
        return {"consistent": False, "reason": "round_not_verified"}
    scores = snapshot.get("scores")
    if not isinstance(scores, dict) or set(scores) != set(seats) \
            or any(type(value) is not int for value in scores.values()):
        return {"consistent": False, "reason": "three_scores_not_verified"}
    sticks, honba = snapshot.get("riichiSticks"), snapshot.get("honba")
    if type(sticks) is not int or not 0 <= sticks <= 99 \
            or type(honba) is not int or not 0 <= honba <= 99:
        return {"consistent": False, "reason": "honba_or_riichi_sticks_not_verified"}
    if sum(scores.values()) + sticks * 1000 != expected_total_points:
        return {"consistent": False, "reason": "scores_and_riichi_sticks_total_mismatch"}
    return {"consistent": True, "scope": "sanma_supplied_values_only"}


def parse_sanma_board_tokens(tokens: list[dict], *, expected_total_points: int | None,
                             payment_phase: str | None) -> dict:
    """Offline candidate parsing only; never certifies OCR or game mode.

    Token coordinates use the three native 1920x1080 frames documented in the
    validation. Caller supplies separately verified settings and payment phase.
    The function is not connected to screenshot acquisition or live control.
    """
    result = {"verified": False, "scope": "sanma_offline_ocr_candidate"}
    if not isinstance(tokens, list) or any(not isinstance(t, dict) for t in tokens):
        return {**result, "reason": "invalid_tokens"}

    def at(x, y, pattern, minimum=0.98):
        matches = []
        for item in tokens:
            text, confidence, px, py = (item.get(k) for k in ("text", "confidence", "x", "y"))
            if (isinstance(text, str) and type(confidence) in (int, float)
                    and type(px) in (int, float) and type(py) in (int, float)
                    and minimum <= confidence <= 1 and abs(px - x) <= 24 and abs(py - y) <= 20
                    and re.fullmatch(pattern, text)):
                matches.append(text)
        return matches[0] if len(matches) == 1 else None

    wind = at(824, 514, "[東南西]")
    round_text = at(960, 405, "[東南西北][1-3]局")
    sticks = at(132, 155, r"\d{1,2}")
    honba = at(268, 155, r"\d{1,2}")
    positions = (("own", 960, 482), ("left", 876, 423), ("opposite", 958, 364))
    numbers = {}
    for position, x, y in positions:
        number = at(x, y, r"-?\d{3,6}")
        if number is None:
            number = at(x, y, r"0", 0.95)
        numbers[position] = number
    if not wind or not round_text or sticks is None or honba is None or any(v is None for v in numbers.values()):
        return {**result, "reason": "incomplete_or_ambiguous_tokens"}
    if any(isinstance(t.get("text"), str) and re.fullmatch(r"-?\d{1,6}", t["text"])
           and type(t.get("confidence")) in (int, float) and 0.98 <= t["confidence"] <= 1
           and type(t.get("x")) in (int, float) and type(t.get("y")) in (int, float)
           and abs(t["x"] - 1047) <= 24 and abs(t["y"] - 419) <= 20 for t in tokens):
        return {**result, "reason": "unexpected_right_score"}
    seat = WINDS[wind]
    mapping = sanma_seats_by_screen_position(seat)
    candidate = {"seat": seat, "round": f"{WINDS[round_text[0]]}_{round_text[1]}",
                 "scores": {mapping[position]: int(value) for position, value in numbers.items()},
                 "riichiSticks": int(sticks), "honba": int(honba)}
    # Preserve the observed wall count as an OCR candidate only.  Missing,
    # ambiguous, or implausible readings do not imply an empty wall.
    remaining = at(959, 443, r"余\d{1,2}")
    if remaining is not None and int(remaining[1:]) <= 70:
        candidate["remainingTiles"] = int(remaining[1:])
    check = validate_sanma_board_consistency(candidate, expected_total_points=expected_total_points,
                                              payment_phase=payment_phase)
    if not check["consistent"]:
        return {**result, "reason": check["reason"], "candidate": candidate}
    return {**result, "consistent": True, "candidate": candidate}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("screenshot", type=Path)
    print(json.dumps(recognize_board(parser.parse_args().screenshot), ensure_ascii=False))
