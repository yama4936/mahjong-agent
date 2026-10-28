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
        self.start_click_at: float | None = None
        self.initial_action_anchor: float | None = None

    def record_verified_start_click(self, *, clicked_at: float) -> None:
        """Record a click made by this process on a separately verified room.

        The caller must verify the room and its controls immediately before
        clicking. This is not permission to trust a generic navigation screen.
        """
        if not self.ready and not self.quarantined:
            self.start_click_at = clicked_at

    def observe(self, *, verified_match: bool, action_visible: bool, now: float) -> str:
        if self.ready:
            return "ready"
        if not verified_match:
            self.no_draw_since = None
            return "wait"
        if self.start_click_at is not None:
            # A stale click, slow load, reconnect, or clock reversal cannot
            # authorize an initial action. The short window is intentionally
            # independent of the configured game deadline.
            age = now - self.start_click_at
            if 0 <= age <= 30 and action_visible:
                self.ready = True
                self.initial_action_anchor = self.start_click_at
                self.start_click_at = None
                return "ready"
            if not 0 <= age <= 30:
                self.start_click_at = None
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
