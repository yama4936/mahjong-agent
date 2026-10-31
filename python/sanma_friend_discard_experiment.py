"""One experimental friend-match discard; not wired into the playing loop.

Caller-provided recognition, room and timing claims are not independently
certified. A successful click receipt does not prove a discard reached the river.
"""
import hashlib
import io

from PIL import Image, ImageChops, ImageStat
import io

from PIL import Image
import math
import time
from pathlib import Path

from auto_operator import send_discard_click
from sanma_friend_freshness import friend_action_started_at, friend_frame_stable, latch_friend_action_target


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


def friend_visible_row_with_north_overlap(frame, row_slots):
    """Unverified friend-only blank-left hypothesis; hidden pixels remain unknown."""
    if (not isinstance(row_slots, list) or len(row_slots) != 3
            or any(not isinstance(slot, dict) for slot in row_slots)
            or any(slot.get("status") != "empty_candidate" for slot in row_slots[:2])
            or row_slots[2].get("status") != "unresolved"):
        return False
    try:
        with Image.open(io.BytesIO(frame)) as source:
            if source.size != (1920, 1080): return False
            image = source.convert("RGB")
        with Image.open("test/fixtures/sanma-button-rows/empty.png") as source:
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
        with Image.open(io.BytesIO(frame)) as source:
            if source.size != (1920,1080): return False
            observed=source.convert('RGB').crop((1180,785,1425,875))
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


def experimental_draw_only_candidate(hand, geometry, draw):
    """Only the separated draw label is used; other labels remain uncertain."""
    try:
        tiles, matches = hand["tiles"], hand["matches"]
        ev = geometry["evidence"]
        match = matches[-1]
        return (hand.get("turnReady") is True and len(tiles) == len(matches) == 14
                and geometry.get("confidence",0) >= .98 and ev.get("detectedTiles") == 14
                and ev.get("rowBottomSpread",999) <= 2
                and type(ev.get("drawGap")) in (int,float) and type(ev.get("medianGap")) in (int,float)
                and ev["drawGap"] >= ev["medianGap"] + 10
                and draw.get("index") == 13 and draw.get("tile") == tiles[-1]
                and match.get("tile") == tiles[-1] and type(match.get("confidence")) in (int,float)
                and type(match.get("runnerUpConfidence")) in (int,float)
                and match["confidence"] >= .98 and match["confidence"] - match["runnerUpConfidence"] >= .1)
    except (TypeError, KeyError, IndexError):
        return False


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
    white_candidates = None if hand_value.get("safe") is True else experimental_white_hand_candidate(baseline, hand_value, geo_value)
    partial_row = (friend_visible_row_with_north_overlap(baseline, row_slots)
                   or friend_visible_empty_row_candidate(baseline, row_slots))
    draw_only = hand_value.get("safe") is not True and white_candidates is None and experimental_draw_only_candidate(hand_value, geo_value, draw)
    if ((hand_value.get("safe") is not True and white_candidates is None and not draw_only) or hand_value.get("turnReady") is not True
            or not isinstance(row_slots, list) or len(row_slots) != 3
            or (not partial_row and any(slot.get("status") != "empty_candidate" for slot in row_slots))
            or not isinstance(tiles, list) or len(tiles) != 14 or not isinstance(points, list) or len(tiles) != len(points)
            or draw.get("index") != len(tiles) - 1 or draw.get("tile") != tiles[-1]
            or draw.get("point") != points[-1]):
        raise ValueError("unsafe hand, uncertain prompt or draw mismatch")
    slots = [{"tile": tile, **point} for tile, point in zip(tiles, points)]
    from sanma_friend_shape_candidate import friend_shape_candidate, friend_non_riichi_hypothesis, friend_hand_click_geometry
    shape = friend_shape_candidate(receipt)
    # CPU-friend experiment: visual rail and hand confidence are hypotheses,
    # never an assertion that riichi status or turn are confirmed.
    calibrated_points = operator.layout.get("clickPoints", []) if isinstance(operator.layout, dict) else []
    calibrated_slots = ([*operator.layout.get("handSlots", []), operator.layout.get("drawSlot")]
                        if isinstance(operator.layout, dict) else [])
    shape_choice = (getattr(operator, "sanma_friend_riichi_attempted", False) is False
                    and shape.get("status") == "candidate"
                    and all(slot.get("status") == "empty_candidate" for slot in row_slots)
                    and len(calibrated_points) == len(points) == len(calibrated_slots) == 14
                    and calibrated_points == points
                    and friend_hand_click_geometry(calibrated_slots, calibrated_points)
                    and calibrated_slots == [*geo_value.get("handSlots", []), geo_value.get("drawSlot")]
                    and friend_non_riichi_hypothesis(baseline, hand_value))
    selected = shape if shape_choice else draw
    plan = {"scope": "offline_untrusted_sanma_discard_plan", "operationAuthorized": False,
            "tile": selected["tile"], "clickIndex": selected["index"], "clickPoint": selected["point"]}
    operator.log("sanma_friend_shape_candidate", candidate=shape,
                 selectedAction="shape_hypothesis" if shape_choice else "draw_only",
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
                   "frameSha256": receipt["digest"], "referenceFrame": baseline,
                   "experimentalDrawReport": report if freshness.get("status") == "stable_draw_glyph_candidate" else None}
    session = {"mode": "cpu_friend", "rules": "sanma", "clock": "300+0", "actionDeadlineMs": 300000,
               "ranked": False, "cpuCount": 2, "roomVerified": True}
    def record(event):
        operator.log("sanma_friend_discard_experiment", **event)
    latch_friend_action_target(operator, baseline, "discard")
    return execute_friend_discard(page, session=session, observation=observation, plan=plan,
                                  layout=operator.layout, log=record,
                                  turn_started_monotonic=friend_action_started_at(operator),
                                  session_check=lambda: getattr(operator, "verified_friend_300_active", False) is True)


def execute_friend_discard(page, *, session, observation, plan, layout, log,
                           turn_started_monotonic, clock=time.monotonic, session_check=None):
    """Map a supplied TS plan to the existing select/confirm routine.

    This experimental entry point depends on a caller that establishes the
    room and game identity, captures/recognizes the turn, and persists log
    events. It does not establish any of those claims itself.
    """
    started = clock()
    event = {"kind": "sanma_friend_discard", "status": "blocked"}
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
        before = page.screenshot(animations="disabled")
        reference = observation.get("referenceFrame")
        if not isinstance(before, bytes) or (hashlib.sha256(before).hexdigest() != observation.get("frameSha256")
                and (not isinstance(reference, bytes)
                     or hashlib.sha256(reference).hexdigest() != observation.get("frameSha256")
                     or not (friend_frame_stable(reference, before)
                             or (observation.get("experimentalDrawReport") is not None
                                 and __import__("auto_operator").experimental_draw_glyph_stability(reference, before, observation["experimentalDrawReport"]))))):
            raise ValueError("recognition frame changed before click")
        def deadline():
            if session_check is not None and session_check() is not True:
                raise RuntimeError("friend session revoked")
            if not 0 <= clock() - turn_started_monotonic < 300:
                raise RuntimeError("action deadline expired")
        deadline()
        event.update(status="attempted", tile=plan["tile"], clickIndex=index, clickPoint=point,
                     frameSha256=observation["frameSha256"])
        log(dict(event))
        receipt = send_discard_click(page.mouse, point, layout["viewport"], page.wait_for_timeout,
                                     before,
                                     lambda _: page.screenshot(animations="disabled"), layout, index, 5, deadline)
        event.update(status="selection_confirmed", selectionReceipt=receipt,
                     result="discard_not_verified")
        log(dict(event))
        return event
    except Exception as error:
        event.update(status="failed" if event["status"] == "attempted" else "blocked",
                     error=str(error), result="discard_not_verified")
        log(dict(event))
        raise
