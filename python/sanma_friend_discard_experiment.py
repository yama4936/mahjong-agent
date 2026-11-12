"""One experimental friend-match discard; not wired into the playing loop.

Caller-provided recognition, room and timing claims are not independently
certified. A successful click receipt does not prove a discard reached the river.
"""
from contextlib import nullcontext
import hashlib
import os
import io

from PIL import Image, ImageChops, ImageStat
import io

from PIL import Image
import math
import time
import uuid
import tempfile
from pathlib import Path

from auto_operator import send_discard_click
from screen_state import require_sanma_observable_frame
from sanma_friend_freshness import friend_action_started_at, friend_frame_stable, latch_friend_action_target


def friend_opponent_riichi_candidates(frame):
    """Positive-only stick candidates in physical left/right HUD regions.

    No stick is not proof that an opponent has not declared riichi.
    """
    from board_metadata import recognize_riichi_sticks
    with Image.open(io.BytesIO(frame)) as image:
        detected = recognize_riichi_sticks(image, 'east')
    return [side for seat, side in (('south', 'right'), ('north', 'left'), ('west', 'opposite')) if seat in detected]


def friend_genbutsu_candidate(source, digest, threats, tiles, matches):
    """Unverified matching labels in every observed threatening physical river."""
    if not threats or any(side not in ('left', 'right') for side in threats): return None
    rivers = {}
    for side in threats:
        river = source.get(side + 'River')
        if (not isinstance(river, dict) or river.get('frameSha256') != digest
                or river.get('scope') != f'offline_untrusted_sanma_{side}_river'
                or river.get('verified') is not False or river.get('operationAuthorized') is not False
                or not isinstance(river.get('candidates'), list)):
            return None
        low, high = (500, 805) if side == 'left' else (1115, 1420)
        rivers[side] = {item['tile'] for item in river['candidates'] if isinstance(item, dict)
                        and isinstance(item.get('tile'), str) and item.get('verified') is False
                        and type(item.get('confidence')) in (int, float) and .99 <= item['confidence'] <= 1
                        and type(item.get('x')) in (int, float) and low <= item['x'] < high
                        and type(item.get('y')) in (int, float) and 285 <= item['y'] < 560}
    if not isinstance(matches, list) or len(matches) != len(tiles): return None
    for index, (tile, match) in enumerate(zip(tiles, matches)):
        if (isinstance(match, dict) and match.get('tile') == tile
                and type(match.get('confidence')) in (int, float) and .99 <= match['confidence'] <= 1
                and all(tile in rivers[side] for side in threats)):
            return {'tile': tile, 'index': index, 'opponents': threats, 'confirmed': False}
    return None


def experimental_white_hand_candidate(frame, hand, geometry):
    """Narrow visual hypothesis only; unloaded tile faces may look identical."""
    try:
        tiles, matches = hand["tiles"], hand["matches"]
        presence, rects = hand["presenceFractions"], geometry["handSlots"]
        evidence = geometry["evidence"]
        if (hand.get("turnReady") is not True or len(tiles) != 14 or len(matches) != 14
                or len(presence) != 14 or len(rects) != 13
                or geometry.get("confidence", 0) < .98 or evidence.get("detectedTiles") != 14
                or evidence.get("rowBottomSpread", 999) > 2
                or any(not isinstance(v, (int, float)) or v < .75 for v in presence)):
            return None
        unknown = []
        for i, (tile, match) in enumerate(zip(tiles, matches)):
            if match.get("tile") != tile:
                return None
            if tile == "P" and match.get("confidence") == 0 and match.get("runnerUpConfidence") == 0:
                if i == 13: return None
                unknown.append(i)
            elif (not isinstance(match.get("confidence"), (int, float))
                  or not isinstance(match.get("runnerUpConfidence"), (int, float))
                  or match["confidence"] < .95
                  or match["confidence"] - match["runnerUpConfidence"] < .01):
                return None
        if not unknown or len(unknown) > 4:
            return None
        with Image.open(io.BytesIO(frame)) as source:
            if source.size != (1920, 1080): return None
            image = source.convert("RGB")
            for i in unknown:
                rect = rects[i]
                x, y, w, h = (rect[k] for k in ("x", "y", "width", "height"))
                if (any(type(v) is not int for v in (x,y,w,h)) or not (85 <= w <= 100 and 140 <= h <= 160)
                        or x < 0 or y < 0 or x+w > 1920 or y+h > 1080): return None
                core = image.crop((x+w//4, y+h//4, x+3*w//4, y+3*h//4))
                pixels = list(core.getdata())
                if sum(min(p) >= 170 and max(p)-min(p) <= 35 for p in pixels) / len(pixels) < .99:
                    return None
        return unknown
    except (KeyError, TypeError, ValueError, OSError, ZeroDivisionError):
        return None


def friend_empty_first_two_pixels(image):
    """Independent visual check; still a partial, unverified observation."""
    with Image.open(Path(__file__).resolve().parent.parent / 'test/fixtures/sanma-button-rows/empty.png') as source:
        empty=source.convert('RGB')
    if empty.size != (825,90):return False
    for x in (600,890):
        difference=ImageChops.difference(image.crop((x,785,x+245,875)),empty.crop((x-600,0,x-600+245,90)))
        if max(channel[1] for channel in difference.getextrema()) > 40:return False
        if any(sum(ImageStat.Stat(difference.crop((xx,yy,min(xx+16,245),min(yy+16,90)))).mean)/3 > 3
               for yy in range(0,90,16) for xx in range(0,245,16)):return False
    return True


def friend_visible_row_with_north_overlap(frame, row_slots):
    """Unverified friend-only blank-left hypothesis; hidden pixels remain unknown."""
    if (not isinstance(row_slots, list) or len(row_slots) != 3
            or any(not isinstance(slot, dict) for slot in row_slots)
            or any(slot.get("status") != "empty_candidate" for slot in row_slots[:2])
            or row_slots[2].get("status") != "unresolved"):
        return False
    try:
        with (nullcontext(frame) if isinstance(frame, Image.Image) else Image.open(io.BytesIO(frame))) as source:
            if source.size != (1920, 1080): return False
            image = source.convert("RGB")
        if not friend_empty_first_two_pixels(image):return False
        with Image.open(Path(__file__).resolve().parent.parent / 'test/fixtures/sanma-button-rows/empty.png') as source:
            blank = source.convert("RGB").crop((580,0,715,90))
        with Image.open(Path(__file__).parent / "fixtures" / "sanma-friend-two-north-overlap.png") as source:
            north = source.convert("RGB")
        with Image.open(Path(__file__).parent / "fixtures" / "sanma-friend-covered-slot.png") as source:
            covered_slot = source.convert("RGB")
        difference = ImageChops.difference(image.crop((1180,785,1425,875)), covered_slot)
        # Every visible pixel of the slot is checked, including the narrow
        # strip between the north and the clock. Strict changes fail closed.
        if max(difference.getextrema()[channel][1] for channel in range(3)) > 30:
            return False
        # Apply the same local-change bound used by the other partial-row
        # references; a weak but broad mark can pass a full-crop average.
        if any(sum(ImageStat.Stat(difference.crop((x,y,min(x+16,245),min(y+16,90)))).mean)/3 > 3
               for y in range(0,90,16) for x in range(0,245,16)):
            return False
        def similarity(a,b):
            return 1 - sum(ImageStat.Stat(ImageChops.difference(a,b)).mean) / 765
        return (similarity(image.crop((1180,785,1315,875)),blank) >= .995
                and similarity(image.crop((1322,765,1390,850)),north) >= .98)
    except (OSError, ValueError):
        return False


def friend_visible_empty_row_candidate(frame, row_slots):
    """Unverified visible empty slot matching one reviewed CPU-friend capture."""
    if (not isinstance(row_slots,list) or len(row_slots)!=3
            or any(not isinstance(slot,dict) or slot.get('status')!='empty_candidate' for slot in row_slots[:2])
            or not isinstance(row_slots[2],dict) or row_slots[2].get('status')!='unresolved'):
        return False
    try:
        with (nullcontext(frame) if isinstance(frame, Image.Image) else Image.open(io.BytesIO(frame))) as source:
            if source.size != (1920,1080): return False
            image=source.convert('RGB')
            observed=image.crop((1180,785,1425,875))
        # Recheck the reported-empty first two slots against pixels as well;
        # a stale or incorrect row report must not conceal a visible prompt.
        if not friend_empty_first_two_pixels(image):return False
        # Include an independently observed two-north/clock layout. It is a
        # visible-pixel hypothesis, not evidence about the obscured action.
        for name in ('sanma-friend-empty-slot-bf.png', 'sanma-friend-two-north-slot-dd.png', 'sanma-friend-empty-slot-6c.png'):
            with Image.open(Path(__file__).parent/'fixtures'/name) as source:
                reference=source.convert('RGB')
            difference=ImageChops.difference(observed,reference)
            if max(channel[1] for channel in difference.getextrema()) > 30:
                continue
            if all(sum(ImageStat.Stat(difference.crop((x,y,min(x+16,245),min(y+16,90)))).mean)/3 <= 3
                   for y in range(0,90,16) for x in range(0,245,16)):
                return True
        return False
    except (OSError,ValueError):
        return False


def friend_visible_full_empty_row_candidate(frame, row_slots):
    """Friend-only visible-empty hypothesis, requiring an unobscured full row.

    A pixel match cannot establish hidden state or riichi status. Only the
    reviewed blank-slot reference is accepted, not north-overlap references.
    """
    if (not isinstance(row_slots, list) or len(row_slots) != 3
            or any(not isinstance(slot, dict) or slot.get('status') != 'empty_candidate' for slot in row_slots[:2])
            or not isinstance(row_slots[2], dict) or row_slots[2].get('status') != 'unresolved'):
        return False
    try:
        with Image.open(io.BytesIO(frame)) as source:
            if source.size != (1920, 1080):
                return False
            image = source.convert('RGB')
        if not friend_empty_first_two_pixels(image):
            return False
        with Image.open(Path(__file__).parent / 'fixtures' / 'sanma-friend-empty-slot-6c.png') as source:
            reference = source.convert('RGB')
        if reference.size != (245, 90):
            return False
        delta = ImageChops.difference(image.crop((1180, 785, 1425, 875)), reference)
        if max(channel[1] for channel in delta.getextrema()) > 30:
            return False
        return all(sum(ImageStat.Stat(delta.crop((x, y, min(x+16, 245), min(y+16, 90)))).mean) / 3 <= 3
                   for y in range(0, 90, 16) for x in range(0, 245, 16))
    except (OSError, ValueError, TypeError):
        return False


SANMA_FRIEND_DRAW_MIN_CONFIDENCE = 0.98


def experimental_draw_only_candidate(hand, geometry, draw):
    """Only the separated draw label is used; other labels remain uncertain."""
    try:
        tiles, matches = hand["tiles"], hand["matches"]
        ev = geometry["evidence"]
        match = matches[-1]
        geometry_confidence = geometry.get('confidence')
        return (hand.get("turnReady") is True and len(tiles) == len(matches) == 14
                and type(geometry_confidence) in (int,float) and math.isfinite(geometry_confidence)
                and .98 <= geometry_confidence <= 1 and ev.get("detectedTiles") == 14
                and type(ev.get('rowBottomSpread')) in (int,float) and math.isfinite(ev['rowBottomSpread'])
                and 0 <= ev['rowBottomSpread'] <= 2
                and type(ev.get("drawGap")) in (int,float) and type(ev.get("medianGap")) in (int,float)
                and math.isfinite(ev['drawGap']) and math.isfinite(ev['medianGap'])
                and ev["drawGap"] >= ev["medianGap"] + 10
                and draw.get("index") == 13 and draw.get("tile") == tiles[-1]
                and match.get("tile") == tiles[-1] and type(match.get("confidence")) in (int,float)
                and type(match.get("runnerUpConfidence")) in (int,float)
                and math.isfinite(match['confidence']) and math.isfinite(match['runnerUpConfidence'])
                and 0 <= match['confidence'] <= 1 and 0 <= match['runnerUpConfidence'] <= 1
                and match["confidence"] >= SANMA_FRIEND_DRAW_MIN_CONFIDENCE and match["confidence"] - match["runnerUpConfidence"] >= .1)
    except (TypeError, KeyError, IndexError):
        return False


class DiscardPreclickChanged(ValueError):
    """A comparison rejected the frame before any discard input."""


def execute_friend_draw_candidate(operator, page, receipt):
    """Experimental draw-only bridge from the resident observation to input.

    A separated draw is used because riichi status is not recognized. A draw
    candidate does not itself prove the game is on our turn. The room, turn,
    labels and empty action row remain experimental observations.
    """
    args = operator.args
    if (getattr(args, "experimental_sanma_friend", False) is not True
            or getattr(args, "rules", None) != "sanma" or getattr(args, "mode", None) != "force-auto"
            or getattr(args, "action_deadline_ms", None) != 300000
            or getattr(args, "ranked_loop", None) is not False
            or getattr(operator, "verified_friend_300_active", False) is not True):
        raise ValueError("experimental reviewed CPU friend session required")
    if not isinstance(receipt, dict) or receipt.get("scope") != "sanma_self_turn_observation":
        raise ValueError("self-turn observation missing")
    source = receipt.get("sourceObservation") or {}
    report = source.get("report") or {}
    hand, geometry, row = (report.get(name) or {} for name in ("hand", "handGeometry", "buttonRow"))
    draw = receipt.get("drawCandidate") or {}
    freshness = receipt.get("freshness") or {}
    if (source.get("digest") != receipt.get("digest") or report.get("digest") != receipt.get("digest")
            or draw.get("digest") != receipt.get("digest") or draw.get("status") != "candidate"
            or freshness.get("status") not in ("identical_pixels_candidate", "stable_except_clock_candidate", "stable_draw_glyph_candidate")
            or hand.get("status") != "candidate" or geometry.get("status") != "candidate"
            or row.get("status") != "candidate"):
        raise ValueError("turn, frame, hand or action row unavailable")
    if freshness.get("status") == "stable_draw_glyph_candidate" and (type(freshness.get("elapsedMs")) not in (int, float) or not 0 <= freshness["elapsedMs"] <= 20000):
        raise ValueError("draw lighting observation expired")
    hand_value, geo_value = hand.get("value") or {}, geometry.get("value") or {}
    row_slots = (row.get("value") or {}).get("slots")
    tiles, points = hand_value.get("tiles"), geo_value.get("clickPoints")
    baseline = Path(receipt["screenshot"]).read_bytes()
    if hashlib.sha256(baseline).hexdigest() != receipt.get("digest"):
        raise ValueError("recognition frame changed on disk")
    threats = friend_opponent_riichi_candidates(baseline)
    white_candidates = None if hand_value.get("safe") is True else experimental_white_hand_candidate(baseline, hand_value, geo_value)
    partial_row = (friend_visible_row_with_north_overlap(baseline, row_slots)
                   or friend_visible_empty_row_candidate(baseline, row_slots))
    draw_only = hand_value.get("safe") is not True and experimental_draw_only_candidate(hand_value, geo_value, draw)
    blank_only = False
    if hand_value.get("safe") is not True and not draw_only:
        from sanma_friend_blank_draw import blank_draw_candidate
        blank_only = draw_only = blank_draw_candidate(baseline, hand_value, geo_value, draw)
        if blank_only:
            operator.log('sanma_friend_blank_draw_candidate', digest=receipt['digest'], confirmed=False,
                         operationAuthorized=False, reason='blank draw may be an unloaded tile; identity unknown')
    five_sou_only = False
    if hand_value.get("safe") is not True and not draw_only:
        from sanma_five_sou_candidate import ordinary_five_sou_candidate
        five_sou_only = draw_only = ordinary_five_sou_candidate(baseline, hand_value, geo_value, draw)
        if draw_only:
            operator.log('sanma_friend_five_sou_candidate', digest=receipt['digest'], confirmed=False,
                         operationAuthorized=False, reason='ordinary five sou color and shape hypothesis')
    defensive = (friend_genbutsu_candidate(source, receipt['digest'], threats, tiles, hand_value.get('matches'))
                 if threats and isinstance(tiles, list) and isinstance(points, list) and len(points) == len(tiles) else None)
    if five_sou_only or blank_only:
        defensive = None
    if defensive is not None and defensive['index'] != draw.get('index'):
        from sanma_friend_shape_candidate import friend_hand_click_geometry, friend_clear_riichi_rail
        calibrated = operator.layout if isinstance(operator.layout,dict) else {}
        hand_slots = [*geo_value.get('handSlots', []),geo_value.get('drawSlot')]
        if (calibrated.get('handSlots') != geo_value.get('handSlots')
                or calibrated.get('drawSlot') != geo_value.get('drawSlot')
                or calibrated.get('clickPoints') != points
                or not friend_hand_click_geometry(hand_slots,points)
                or getattr(operator, 'sanma_friend_riichi_attempted', False) is not False
                or not friend_clear_riichi_rail(baseline)):
            defensive = None
    if ((hand_value.get("safe") is not True and not draw_only and defensive is None) or hand_value.get("turnReady") is not True
            or not isinstance(row_slots, list) or len(row_slots) != 3
            or (not partial_row and any(slot.get("status") != "empty_candidate" for slot in row_slots))
            or not isinstance(tiles, list) or len(tiles) != 14 or not isinstance(points, list) or len(tiles) != len(points)
            or draw.get("index") != len(tiles) - 1 or draw.get("tile") != tiles[-1]
            or draw.get("point") != points[-1]):
        matches = hand_value.get("matches")
        last_match = matches[-1] if isinstance(matches, list) and matches and isinstance(matches[-1], dict) else {}
        operator.log("sanma_friend_discard_guard_rejected", digest=receipt.get("digest"),
                     safeHand=hand_value.get("safe") is True, drawOnlyCandidate=bool(draw_only),
                     defensiveCandidate=defensive is not None, turnReady=hand_value.get("turnReady") is True,
                     partialOrEmptyRowCandidate=bool(partial_row) or (isinstance(row_slots, list) and len(row_slots) == 3
                                                           and all(isinstance(slot, dict) and slot.get("status") == "empty_candidate" for slot in row_slots)),
                     handTileCount=len(tiles) if isinstance(tiles, list) else None,
                     clickPointCount=len(points) if isinstance(points, list) else None,
                     drawIndex=draw.get("index"), drawTile=draw.get("tile"),
                     lastHandSlotConfidence=last_match.get("confidence"),
                     lastHandSlotRunnerUpConfidence=last_match.get("runnerUpConfidence"),
                     drawIndexMatchesLastSlot=(isinstance(tiles, list) and bool(tiles)
                                               and type(draw.get("index")) is int and draw.get("index") == len(tiles) - 1),
                     drawOnlyMinimumConfidence=SANMA_FRIEND_DRAW_MIN_CONFIDENCE,
                     confirmed=False, operationAuthorized=False)
        raise ValueError("unsafe hand, uncertain prompt or draw mismatch")
    slots = [{"tile": tile, **point} for tile, point in zip(tiles, points)]
    if threats:
        operator.log('sanma_friend_opponent_riichi_candidate', opponents=threats,
                     screenshot=receipt['screenshot'], digest=receipt['digest'], confirmed=False,
                     genbutsuCandidate=defensive,
                     reason='river and hand labels are unverified; absent sticks do not rule out riichi', operationAuthorized=False)
        if defensive is None:
            raise ValueError('opponent riichi candidate; safe discard unverified')
    from sanma_friend_shape_candidate import friend_shape_candidate, friend_non_riichi_hypothesis, friend_hand_click_geometry
    shape = friend_shape_candidate(receipt)
    # CPU-friend experiment: visual rail and hand confidence are hypotheses,
    # never an assertion that riichi status or turn are confirmed.
    calibrated_points = operator.layout.get("clickPoints", []) if isinstance(operator.layout, dict) else []
    calibrated_slots = ([*operator.layout.get("handSlots", []), operator.layout.get("drawSlot")]
                        if isinstance(operator.layout, dict) else [])
    shape_choice = (not five_sou_only and not blank_only
                    and getattr(operator, "sanma_friend_riichi_attempted", False) is False
                    and shape.get("status") == "candidate"
                    and (all(slot.get("status") == "empty_candidate" for slot in row_slots)
                         or friend_visible_full_empty_row_candidate(baseline, row_slots))
                    and len(calibrated_points) == len(points) == len(calibrated_slots) == 14
                    and calibrated_points == points
                    and friend_hand_click_geometry(calibrated_slots, calibrated_points)
                    and calibrated_slots == [*geo_value.get("handSlots", []), geo_value.get("drawSlot")]
                    and friend_non_riichi_hypothesis(baseline, hand_value))
    if defensive is not None:
        selected = {**defensive, 'point': points[defensive['index']]}
        shape_choice = False
    else:
        selected = shape if shape_choice else draw
    plan = {"scope": "offline_untrusted_sanma_discard_plan", "operationAuthorized": False,
            "tile": selected["tile"], "clickIndex": selected["index"], "clickPoint": selected["point"]}
    operator.log("sanma_friend_shape_candidate", candidate=shape,
                 selectedPlan=plan, sourceDigest=receipt['digest'],
                 selectedAction="genbutsu_candidate" if defensive is not None else "shape_hypothesis" if shape_choice else "draw_only",
                 reason="visible rail and hand are unverified; riichi, live tiles and turn remain unknown")
    if draw_only:
        operator.log("sanma_friend_draw_only_candidate", digest=receipt["digest"], confirmed=False,
                     risk="other hand labels, turn, legal actions and strategy remain unverified")
    if partial_row:
        operator.log("sanma_friend_partial_row_candidate", digest=receipt["digest"], confirmed=False,
                     risk="slot 2 is unresolved; hidden action and turn remain unverified")
    if white_candidates is not None:
        operator.log("sanma_friend_white_candidate", indices=white_candidates, confirmed=False,
                     risk="unloaded tile faces may appear identical", digest=receipt["digest"])
    observation = {"status": "candidate", "phase": "self_turn", "promptStatus": "none",
                   "handStatus": "candidate", "layoutStatus": "candidate", "slots": slots,
                   "frameSha256": receipt["digest"], "referenceFrame": baseline, "referenceScreenshot": receipt["screenshot"],
                   "experimentalDrawReport": report if freshness.get("status") == "stable_draw_glyph_candidate" else None}
    session = {"mode": "cpu_friend", "rules": "sanma", "clock": "300+0", "actionDeadlineMs": 300000,
               "ranked": False, "cpuCount": 2, "roomVerified": True}
    def record(event):
        operator.log("sanma_friend_discard_experiment", **event)
    def save_rejected_frame(frame):
        path = operator.frames / f"{uuid.uuid4().hex}.sanma-discard-preclick-rejected.png"
        path.write_bytes(frame)
        operator.log("sanma_friend_discard_preclick_rejected", screenshot=str(path),
                     sha256=hashlib.sha256(frame).hexdigest(),
                     referenceScreenshot=receipt["screenshot"], referenceSha256=receipt["digest"],
                     operationAuthorized=False)
    def session_check():
        from sanma_friend_freshness import check_friend_recovery_guard
        check_friend_recovery_guard(operator)
        return getattr(operator, "verified_friend_300_active", False) is True
    result = execute_friend_discard(page, session=session, observation=observation, plan=plan,
                                  layout=operator.layout, log=record,
                                  turn_started_monotonic=friend_action_started_at(operator),
                                  session_check=session_check,
                                  self_turn_wall_opt_in=getattr(operator.args, 'experimental_sanma_self_turn_wall', False) is True,
                                  save_rejected_frame=save_rejected_frame, evidence_directory=operator.frames,
                                  before_click=lambda: latch_friend_action_target(operator, baseline, "discard"))
    if blank_only:
        result['blankDrawIdentityUnknown'] = True
    return result


# Fix B (timing) support: regions whose animation is already bounded by a
# dedicated semantic guard in experimental_draw_glyph_stability. The wall
# region is the crop of experimental_kita_wall_color_stable; the centre box
# is compared structurally as the final glyph stage. Binary changes anywhere
# else can never justify adopting a fresh baseline.
_REFRESH_WALL_REGION = (150, 80, 390, 700)
_REFRESH_CENTER_BOX = (905, 375, 1010, 465)


def _masked_binary_difference(reference, frame, report):
    """Replicate the binary_frame mask of the draw glyph guard.

    Returns the thresholded (<120) difference image after the guard's own
    clock, self-lamp, hand, draw and button masks. No threshold or mask is
    altered. Returns None when the scan cannot be performed; callers must
    fail closed.
    """
    try:
        geometry = report["handGeometry"]["value"]
        boxes = list(geometry["handSlots"]) + [geometry["drawSlot"]] + [
            {"x": 600, "y": 785, "width": 245, "height": 90},
            {"x": 890, "y": 785, "width": 245, "height": 90},
            {"x": 1180, "y": 785, "width": 245, "height": 90}]
        with Image.open(io.BytesIO(reference)) as a, Image.open(io.BytesIO(frame)) as b:
            if a.size != (1920, 1080) or b.size != a.size:
                return None
            first = a.convert("L").point(lambda v: 255 if v < 120 else 0)
            second = b.convert("L").point(lambda v: 255 if v < 120 else 0)
            diff = ImageChops.difference(first, second)
            for rect in ((1425, 755, 1650, 870), (890, 495, 1015, 516)):
                diff.paste(0, rect)
            for box in boxes:
                x, y, w, h = (int(box[k]) for k in ("x", "y", "width", "height"))
                if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1920 or y + h > 1080:
                    return None
                diff.paste(0, (x, y, x + w, y + h))
            return diff
    except (KeyError, TypeError, ValueError, OSError, IndexError):
        return None


def _binary_frame_change_blocks(reference, frame, report):
    """32-pixel blocks whose masked binary changes exceed the guard's 14."""
    diff = _masked_binary_difference(reference, frame, report)
    if diff is None:
        return None
    blocks = []
    for y in range(0, 1080, 32):
        for x in range(0, 1920, 32):
            changed = diff.crop((x, y, min(x + 32, 1920), min(y + 32, 1080))).histogram()[255]
            if changed > 14:
                blocks.append({"x": x, "y": y, "changedPixels": changed})
    return blocks


def _changed_pixels_confined_to_animation_regions(reference, frame, report, blocks):
    """Pixel-level containment of the flagged binary changes.

    Every changed pixel inside a flagged block must lie within the wall
    crop or the centre box. A block that merely intersects a region while
    its changed pixels sit outside it confines nothing. Changed pixels in
    unflagged blocks stay under the guard's own 14-pixel block threshold,
    exactly as in the original scan. Returns None when the scan cannot be
    performed; callers must fail closed.
    """
    if not blocks:
        return False
    diff = _masked_binary_difference(reference, frame, report)
    if diff is None:
        return None
    regions = (_REFRESH_WALL_REGION, _REFRESH_CENTER_BOX)
    pixels = diff.load()
    for block in blocks:
        for yy in range(block["y"], min(block["y"] + 32, 1080)):
            for xx in range(block["x"], min(block["x"] + 32, 1920)):
                if pixels[xx, yy] and not any(
                        rx1 <= xx < rx2 and ry1 <= yy < ry2
                        for rx1, ry1, rx2, ry2 in regions):
                    return False
    return True


def _save_refresh_frame(directory, refresh_id, role, frame, *, captured_at=None,
                        captured_at_unix=None, source_screenshot=None):
    """Save exact bytes durably, with capture-completion (not shutter) times.

    Unknown original capture times remain null. Directory fsync requires the
    Linux filesystem used by the operator; unsupported storage fails closed.
    """
    if directory is None:
        raise ValueError("baseline refresh evidence directory required")
    path = Path(directory).resolve() / f"{refresh_id}.sanma-refresh-{role}.png"
    digest = hashlib.sha256(frame).hexdigest()
    # Private staging plus link() publishes atomically without clobbering a winner.
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    temporary = None
    published = False
    try:
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".pending", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(frame)
            stream.flush()
            os.fsync(stream.fileno())
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
            raise OSError("baseline refresh evidence read-back hash mismatch")
        os.link(temporary, path)
        published = True
        temporary.unlink()
        temporary = None
        os.fsync(directory_fd)
    except Exception:
        # A failed publication must not remove a pre-existing winning file.
        if published:
            path.unlink()
        if temporary is not None:
            temporary.unlink()
        raise
    finally:
        os.close(directory_fd)
    return {"screenshot": str(path), "sha256": digest, "byteLength": len(frame),
            "capturedAtMonotonic": captured_at, "capturedAtUnix": captured_at_unix,
            "savedAtUnix": time.time(), "sourceScreenshot": source_screenshot}


# Separate from the 300+0 turn budget: blocking work never renews evidence.
_DISCARD_FRAME_MAX_AGE_SECONDS = 5.0


def _require_discard_capture_fresh(clock, *captured_times):
    now = clock()
    if any(not 0 <= now - captured < _DISCARD_FRAME_MAX_AGE_SECONDS
           for captured in captured_times):
        raise RuntimeError("discard image freshness expired")


def _refresh_discard_baseline(page, *, reference, candidate, candidate_captured_at,
                              report, diagnostic, wall_errors, self_turn_wall_opt_in,
                              draw_index, clock, log, evidence_directory=None,
                              candidate_captured_at_unix=None, reference_screenshot=None, input_guard=None):
    """Adopt a fresh preclick capture as the comparison baseline, or return None.

    The recognised reference is already seconds old when the preclick capture
    is compared with it (recognition, freshness guards and candidate work run
    in between), so animation phase drift alone can trip the binary_frame
    guard and force a full reobservation cycle. A candidate is adopted only
    when every one of these holds; any other outcome returns None and the
    caller rejects exactly as before (fail closed):

    1. The original comparison failed solely at the binary_frame stage, so
       wall colour, hand faces, button glyphs, protected colour and button
       RGB stages all already passed against the reference, and the wall
       guard reported no execution error.
    2. The opt-in self-turn lighting hypothesis does not already explain
       the pair; pairs it explains stay behind that opt-in, draw-only gate.
    3. Every changed pixel inside the flagged binary change blocks lies
       within the wall or centre regions those semantic guards cover
       (pixel-level containment, not block intersection).
    4. The physical hand faces, including the planned slot, still match the
       reference under the same check and threshold the glyph guard uses.
    5. The centre display still matches the original reference under the
       glyph guard's own final stage (structure delta <= .5 against the
       reference, never against the candidate itself).
    6. An immediate confirmation capture matches the candidate under the
       same stability chain (identity, clock-masked stability, glyph
       stability, and the opt-in self-turn fallback) with the same report.

    No guard threshold, mask or rescue condition is changed by this path.
    The returned record identifies the adopted baseline frame and when it
    was captured; failures after eligibility are logged the same way.
    """
    if wall_errors or diagnostic.get("stage") != "binary_frame":
        return None
    # The reviewed self-turn lighting hypothesis is opt-in and draw-only.
    # A pair that hypothesis already explains must stay behind that gate;
    # refreshing the baseline must never become a default-on substitute for
    # it. (The evidence184 rejections are exactly the pairs it does not
    # explain, e.g. the self lamp caught mid-blink.)
    if __import__("sanma_friend_self_turn_stability").self_turn_stability(reference, candidate, report):
        return None
    detail = {"kind": "sanma_discard_baseline_refresh_failed", "confirmed": False,
              "operationAuthorized": False,
              "referenceSha256": hashlib.sha256(reference).hexdigest(),
              "candidateSha256": hashlib.sha256(candidate).hexdigest(),
              "candidateCapturedAtMonotonic": candidate_captured_at,
              "originalDiagnostic": dict(diagnostic), "refreshId": uuid.uuid4().hex,
              "evidence": {}}
    def save_role(role, frame, captured=None, unix=None, source=None):
        detail["evidence"][role] = {
            "status": "failed", "sha256": hashlib.sha256(frame).hexdigest(),
            "byteLength": len(frame), "capturedAtMonotonic": captured,
            "capturedAtUnix": unix, "sourceScreenshot": source, "screenshot": None}
        try:
            saved = _save_refresh_frame(
                evidence_directory, detail["refreshId"], role, frame,
                captured_at=captured, captured_at_unix=unix, source_screenshot=source)
        except Exception as error:
            detail["evidence"][role]["error"] = f"{type(error).__name__}: {error}"
            raise
        detail["evidence"][role] = {"status": "saved", **saved}

    try:
        for role, frame, captured, unix, source in (
                ("reference", reference, None, None, reference_screenshot),
                ("candidate", candidate, candidate_captured_at, candidate_captured_at_unix, None)):
            save_role(role, frame, captured, unix, source)
    except Exception as error:
        detail["reason"] = f"refresh evidence unavailable: {type(error).__name__}: {error}"
        log(detail)
        return None
    blocks = _binary_frame_change_blocks(reference, candidate, report)
    detail["binaryChangeBlocks"] = blocks
    if blocks is None:
        detail["reason"] = "binary change scan unavailable"
        log(detail)
        return None
    confined = _changed_pixels_confined_to_animation_regions(
        reference, candidate, report, blocks)
    detail["binaryChangesConfined"] = confined
    if confined is None:
        detail["reason"] = "binary change pixel scan unavailable"
        log(detail)
        return None
    if not confined:
        detail["reason"] = "binary changes outside wall/centre animation regions"
        log(detail)
        return None
    try:
        geometry = report["handGeometry"]["value"]
        hand_layout = {"handSlots": geometry["handSlots"], "drawSlot": geometry["drawSlot"]}
        mismatches = __import__("auto_operator").closed_hand_face_mismatches(
            reference, candidate, hand_layout, .5)
    except Exception as error:
        detail["reason"] = f"hand face verification unavailable: {type(error).__name__}"
        log(detail)
        return None
    detail["handFaceMismatches"] = mismatches
    if mismatches:
        detail["reason"] = "hand faces differ from reference"
        log(detail)
        return None
    try:
        operator_module = __import__("auto_operator")
        centre_box = {"x": 905, "y": 375, "width": 105, "height": 90}
        centre_delta = operator_module.tile_face_structure_delta(
            operator_module.crop_screenshot(reference, centre_box),
            operator_module.crop_screenshot(candidate, centre_box))
    except Exception as error:
        detail["reason"] = f"centre structure verification unavailable: {type(error).__name__}"
        log(detail)
        return None
    detail["centreStructureDelta"] = centre_delta
    if centre_delta > .5:
        detail["reason"] = "centre structure differs from reference"
        log(detail)
        return None
    try:
        confirmation = page.screenshot(animations="disabled")
        confirmation_captured_at = clock()
        confirmation_captured_at_unix = time.time()
        require_sanma_observable_frame(confirmation)
        if not isinstance(confirmation, bytes):
            raise ValueError("confirmation capture unavailable")
    except Exception as error:
        detail["reason"] = f"confirmation capture unavailable: {type(error).__name__}"
        log(detail)
        return None
    try:
        save_role("confirmation", confirmation, confirmation_captured_at, confirmation_captured_at_unix)
    except Exception as error:
        detail["reason"] = f"confirmation evidence unavailable: {type(error).__name__}: {error}"
        log(detail)
        return None
    detail["confirmationSha256"] = hashlib.sha256(confirmation).hexdigest()
    detail["confirmationCapturedAtMonotonic"] = confirmation_captured_at
    confirmed = detail["confirmationSha256"] == detail["candidateSha256"]
    if not confirmed:
        confirmed = friend_frame_stable(candidate, confirmation)
    if not confirmed:
        confirm_diagnostic = {}
        confirm_wall_errors = []
        def confirm_wall_error(data):
            confirm_wall_errors.append(data)
            log({"kind": "sanma_wall_guard_error", **data})
        confirmed = __import__("auto_operator").experimental_draw_glyph_stability(
            candidate, confirmation, report, diagnostic=confirm_diagnostic,
            on_wall_error=confirm_wall_error)
        if (not confirmed and not confirm_wall_errors and self_turn_wall_opt_in is True
                and draw_index):
            confirmed = __import__("sanma_friend_self_turn_stability").self_turn_stability(
                candidate, confirmation, report)
            if confirmed:
                log({"kind": "sanma_self_turn_wall_candidate", "confirmed": False})
        detail["confirmationDiagnostic"] = confirm_diagnostic
        if confirm_wall_errors:
            detail["reason"] = "wall guard error during baseline confirmation"
            log(detail)
            return None
    if not confirmed:
        detail["reason"] = "candidate baseline not confirmed by immediate capture"
        log(detail)
        return None
    def require_current_evidence():
        try:
            if input_guard is not None:
                input_guard()
            _require_discard_capture_fresh(clock, candidate_captured_at, confirmation_captured_at)
        except Exception as error:
            detail["reason"] = f"refresh input gate rejected: {type(error).__name__}: {error}"
            log(detail)
            raise

    require_current_evidence()
    adopted = {"kind": "sanma_discard_baseline_refreshed", "confirmed": False,
               "refreshId": detail["refreshId"], "evidence": detail["evidence"],
               "operationAuthorized": False,
               "referenceSha256": detail["referenceSha256"],
               "baselineSha256": detail["candidateSha256"],
               "confirmationSha256": detail["confirmationSha256"],
               "baselineCapturedAtMonotonic": candidate_captured_at,
               "confirmationCapturedAtMonotonic": confirmation_captured_at,
               "originalDiagnostic": dict(diagnostic),
               "binaryChangeBlocks": blocks,
               "centreStructureDelta": centre_delta,
               "reason": "reference aged across recognition and freshness; candidate "
                         "re-verified against reference hand faces and confirmed by "
                         "an immediate capture under the same stability chain"}
    log(adopted)
    require_current_evidence()
    return adopted


def execute_friend_discard(page, *, session, observation, plan, layout, log,
                           turn_started_monotonic, clock=time.monotonic, session_check=None,
                           save_rejected_frame=None, before_click=None, self_turn_wall_opt_in=False,
                           evidence_directory=None):
    """Map a supplied TS plan to the existing select/confirm routine.

    This experimental entry point depends on a caller that establishes the
    room and game identity, captures/recognizes the turn, and persists log
    events. It does not establish any of those claims itself.
    """
    started = clock()
    event = {"kind": "sanma_friend_discard", "status": "blocked"}
    precheck_rejected = False
    try:
        if (not isinstance(session, dict) or session.get("mode") != "cpu_friend"
                or session.get("rules") != "sanma" or session.get("clock") != "300+0"
                or session.get("actionDeadlineMs") != 300000 or session.get("ranked") is not False
                or session.get("cpuCount") != 2 or session.get("roomVerified") is not True):
            raise ValueError("explicit reviewed CPU friend 300+0 session required")
        if (not isinstance(observation, dict) or observation.get("status") != "candidate"
                or observation.get("phase") != "self_turn" or observation.get("promptStatus") != "none"
                or observation.get("handStatus") != "candidate" or observation.get("layoutStatus") != "candidate"):
            raise ValueError("ambiguous turn, hand, layout or prompt")
        if (not isinstance(plan, dict) or plan.get("scope") != "offline_untrusted_sanma_discard_plan"
                or plan.get("operationAuthorized") is not False):
            raise ValueError("experimental discard plan required")
        index, point = plan.get("clickIndex"), plan.get("clickPoint")
        slots = observation.get("slots")
        if (type(index) is not int or not isinstance(slots, list) or index < 0 or index >= len(slots)
                or not isinstance(point, dict) or slots[index] != {"tile": plan.get("tile"), **point}
                or set(point) != {"x", "y"}
                or any(type(point[k]) not in (int, float) or not math.isfinite(point[k]) for k in ("x", "y"))
                or not (0 <= point["x"] < 1920 and 0 <= point["y"] < 1080)):
            raise ValueError("plan and recognized slot differ")
        if (type(turn_started_monotonic) not in (int, float) or not math.isfinite(turn_started_monotonic)
                or not 0 <= started - turn_started_monotonic < 300):
            raise ValueError("invalid or expired turn clock")
        def deadline():
            if session_check is not None and session_check() is not True:
                raise RuntimeError("friend session revoked")
            if not 0 <= clock() - turn_started_monotonic < 300:
                raise RuntimeError("action deadline expired")

        before = page.screenshot(animations="disabled")
        before_captured_at = clock()
        before_captured_at_unix = time.time()
        try:
            require_sanma_observable_frame(before)
        except Exception:
            if isinstance(before, bytes) and save_rejected_frame is not None:
                try:
                    save_rejected_frame(before)
                except Exception:
                    pass  # Failed evidence never permits input.
            raise
        reference = observation.get("referenceFrame")
        baseline_refresh = None
        matched = isinstance(before, bytes) and hashlib.sha256(before).hexdigest() == observation.get("frameSha256")
        diagnostic = {"stage": "frame_identity"}
        if not matched and isinstance(before, bytes) and isinstance(reference, bytes):
            if hashlib.sha256(reference).hexdigest() == observation.get("frameSha256"):
                diagnostic["stage"] = "friend_frame_stable"
                matched = friend_frame_stable(reference, before)
                if not matched and observation.get("experimentalDrawReport") is not None:
                    diagnostic = {}
                    wall_errors = []
                    def wall_error(data):
                        wall_errors.append(data)
                        log({"kind":"sanma_wall_guard_error", **data})
                    matched = __import__("auto_operator").experimental_draw_glyph_stability(
                        reference, before, observation["experimentalDrawReport"], diagnostic=diagnostic,
                        on_wall_error=wall_error)
                    if (not matched and not wall_errors and self_turn_wall_opt_in is True
                            and index == len(slots)-1):
                        matched = __import__("sanma_friend_self_turn_stability").self_turn_stability(
                            reference, before, observation["experimentalDrawReport"])
                        if matched:
                            log({"kind":"sanma_self_turn_wall_candidate", "confirmed":False})
                    if not matched:
                        # Fix B (timing): the reference is already seconds old
                        # here, so animation drift alone can trip the binary
                        # guard. Try to adopt this fresh capture as a verified
                        # new baseline instead of forcing a full reobservation.
                        baseline_refresh = _refresh_discard_baseline(
                            page, reference=reference, candidate=before,
                            candidate_captured_at=before_captured_at,
                            report=observation["experimentalDrawReport"],
                            diagnostic=diagnostic, wall_errors=wall_errors,
                            self_turn_wall_opt_in=self_turn_wall_opt_in,
                            draw_index=index == len(slots) - 1,
                            clock=clock, log=log, evidence_directory=evidence_directory,
                            candidate_captured_at_unix=before_captured_at_unix,
                            reference_screenshot=observation.get("referenceScreenshot"), input_guard=deadline)
                        matched = baseline_refresh is not None
        if not matched:
            event['preclickDiagnostic'] = diagnostic
            if isinstance(before, bytes) and save_rejected_frame is not None:
                try:
                    save_rejected_frame(before)
                except Exception as error:
                    event['evidenceSaveError'] = f'{type(error).__name__}: {error}'
            if event.get('evidenceSaveError'):
                raise ValueError("recognition frame changed before click")
            precheck_rejected = True
            raise DiscardPreclickChanged("recognition frame changed before click")
        # A lifted tile may be discarded immediately by the first click.
        # Apply this after every matching path and before any click, including
        # byte-identical frames and the opt-in lighting fallback.
        from auto_operator import raised_closed_hand_slots
        raised = raised_closed_hand_slots(before, layout, strict=True)
        if raised:
            event['raisedSlots'] = raised
            raise ValueError('selected or hovered tile before discard')
        input_captured_at = before_captured_at
        def input_guard():
            deadline()
            _require_discard_capture_fresh(clock, input_captured_at)
        input_guard()
        if before_click is not None:
            before_click()
        event.update(status="attempted", tile=plan["tile"], clickIndex=index, clickPoint=point,
                     frameSha256=observation["frameSha256"])
        if baseline_refresh is not None:
            event.update(baselineRefreshed=True, refreshId=baseline_refresh["refreshId"],
                         baselineSha256=baseline_refresh["baselineSha256"],
                         referenceSha256=baseline_refresh["referenceSha256"])
        log(dict(event))
        def checked_selection(_):
            nonlocal input_captured_at
            frame = page.screenshot(animations="disabled")
            input_captured_at = clock()
            try:
                require_sanma_observable_frame(frame)
            except Exception:
                if isinstance(frame, bytes) and save_rejected_frame is not None:
                    try:
                        save_rejected_frame(frame)
                    except Exception:
                        pass  # The first input is still unresolved; never confirm.
                raise
            return frame
        # The attempted-event logger may block beyond the action deadline or
        # the friend session may be revoked while it writes.
        input_guard()
        receipt = send_discard_click(page.mouse, point, layout["viewport"], page.wait_for_timeout,
                                     before,
                                     checked_selection, layout, index, 5, input_guard)
        event.update(status="selection_confirmed", selectionReceipt=receipt,
                     result="discard_not_verified")
        log(dict(event))
        return event
    except Exception as error:
        event.update(status="failed" if event["status"] == "attempted" else "blocked",
                     error=str(error), result="discard_not_verified")
        try:
            log(dict(event))
        except Exception as log_error:
            raise RuntimeError(f"discard failure could not be recorded; outcome unknown: {error}") from log_error
        if isinstance(error, DiscardPreclickChanged) and not precheck_rejected:
            raise RuntimeError(f"discard input or verification failed; outcome unknown: {error}") from error
        raise
