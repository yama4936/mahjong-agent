"""Offline-only preparation for a manually reviewed three-player friend room.

No function here clicks, navigates, starts an operator, or authorizes an action.
"""
import hashlib

from friend_start import await_reviewed_friend_room, reviewed_sanma_300_plus_zero


def inspect_sanma_friend_start(page, reviewed_preflight: bytes, *, action_deadline_ms: int, attempts: int = 8, on_capture=None):
    """Gather matching room observations; never produce permission to play.

    The caller must have independently reviewed the preflight's player slots,
    readiness, settings and CPU identities. Existing template verification is
    only calibrated on one room. The mandatory deadline is a configuration
    claim; no operator or timer is started or verified here.
    """
    if type(action_deadline_ms) is not int or action_deadline_ms != 300000:
        raise ValueError("sanma friend inspection requires explicit action deadline 300000 ms")
    if not isinstance(reviewed_preflight, bytes) or not reviewed_sanma_300_plus_zero(reviewed_preflight):
        raise ValueError("reviewed 1920x1080 sanma 300+0 preflight required")
    if type(attempts) is not int or not 2 <= attempts <= 32:
        raise ValueError("attempts must be between 2 and 32")
    captures = []

    def capture(index, frame, matched):
        captures.append({"index": index, "sha256": hashlib.sha256(frame).hexdigest(), "matched": matched})
        if on_capture is not None:
            on_capture(index, frame, matched)

    await_reviewed_friend_room(page, reviewed_preflight, attempts=attempts, on_capture=capture, sanma=True)
    return {
        "scope": "offline_untrusted_sanma_friend_start_inspection",
        "preflightSha256": hashlib.sha256(reviewed_preflight).hexdigest(),
        "actionDeadlineMs": action_deadline_ms,
        "clock": "300+0",
        "rules": "sanma",
        "captures": captures,
        # Native manually observed start point; intentionally not a click target.
        "observedStartPoint": {"x": 1140, "y": 998},
        "operationAuthorized": False,
    }
