"""One experimental friend-match discard; not wired into the playing loop.

Caller-provided recognition, room and timing claims are not independently
certified. A successful click receipt does not prove a discard reached the river.
"""
import hashlib
import math
import time

from auto_operator import send_discard_click


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
            or freshness.get("status") != "identical_pixels_candidate"
            or hand.get("status") != "candidate" or geometry.get("status") != "candidate"
            or row.get("status") != "candidate"):
        raise ValueError("turn, frame, hand or action row unavailable")
    hand_value, geo_value = hand.get("value") or {}, geometry.get("value") or {}
    row_slots = (row.get("value") or {}).get("slots")
    tiles, points = hand_value.get("tiles"), geo_value.get("clickPoints")
    if (hand_value.get("safe") is not True or hand_value.get("turnReady") is not True
            or not isinstance(row_slots, list) or len(row_slots) != 3
            or any(slot.get("status") != "empty_candidate" for slot in row_slots)
            or not isinstance(tiles, list) or len(tiles) != 14 or not isinstance(points, list) or len(tiles) != len(points)
            or draw.get("index") != len(tiles) - 1 or draw.get("tile") != tiles[-1]
            or draw.get("point") != points[-1]):
        raise ValueError("unsafe hand, uncertain prompt or draw mismatch")
    slots = [{"tile": tile, **point} for tile, point in zip(tiles, points)]
    plan = {"scope": "offline_untrusted_sanma_discard_plan", "operationAuthorized": False,
            "tile": draw["tile"], "clickIndex": draw["index"], "clickPoint": draw["point"]}
    observation = {"status": "candidate", "phase": "self_turn", "promptStatus": "none",
                   "handStatus": "candidate", "layoutStatus": "candidate", "slots": slots,
                   "frameSha256": receipt["digest"]}
    session = {"mode": "cpu_friend", "rules": "sanma", "clock": "300+0", "actionDeadlineMs": 300000,
               "ranked": False, "cpuCount": 2, "roomVerified": True}
    def record(event):
        operator.log("sanma_friend_discard_experiment", **event)
    return execute_friend_discard(page, session=session, observation=observation, plan=plan,
                                  layout=operator.layout, log=record,
                                  turn_started_monotonic=getattr(operator, "verified_friend_300_started_at", None),
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
        if not isinstance(before, bytes) or hashlib.sha256(before).hexdigest() != observation.get("frameSha256"):
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
