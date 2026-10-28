"""Avoid assuming a turn began when an operator joined an existing table."""


class StartupTurnGuard:
    """Quarantine an initially visible action until a stable inactive interval.

    The game clock cannot be inferred from the time the operator first saw a
    turn.  A verified interval without a draw slot establishes a boundary for
    subsequent turns. Unknown/non-match frames never establish that boundary.
    """

    def __init__(self) -> None:
        self.ready = False
        self.no_draw_since: float | None = None
        self.quarantined = False

    def observe(self, *, verified_match: bool, action_visible: bool, now: float) -> str:
        if self.ready:
            return "ready"
        if not verified_match:
            self.no_draw_since = None
            return "wait"
        if action_visible:
            self.no_draw_since = None
            self.quarantined = True
            return "quarantine"
        if self.no_draw_since is None:
            self.no_draw_since = now
        elif now - self.no_draw_since >= 1.0:
            self.ready = True
            return "ready"
        return "wait"
