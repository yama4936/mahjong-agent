"""One experimental friend-match discard; not wired into the playing loop.

Caller-provided recognition, room and timing claims are not independently
certified. A successful click receipt does not prove a discard reached the river.
"""
import hashlib
import math
import time

from auto_operator import send_discard_click


def execute_friend_discard(page, *, session, observation, plan, layout, log,
                           turn_started_monotonic, clock=time.monotonic):
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
