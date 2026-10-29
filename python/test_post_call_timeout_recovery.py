import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from auto_operator import PythonAutoOperator


class PostCallTimeoutRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.operator = PythonAutoOperator.__new__(PythonAutoOperator)
        self.operator.pending_post_call_discard = True
        self.operator.pending_post_call_started_at = 10.0
        self.operator.post_call_timeout_recovery = {
            "baseline": ["2p", "9p", "4m", "N"], "after": 100.0,
            "startedMonotonic": 10.0, "openMelds": 1,
        }
        self.operator.selection_uncertainty_latch = None
        self.operator.action_evidence_kind = "discard"
        self.operator.layout = {}
        self.operator.log = Mock()
        self.operator.force_auto_action_evidence_age_ms = Mock(return_value=3500)
        self.operator.force_auto_click_budget_ms = Mock(return_value=2600)
        self.operator.clear_discard_evidence_on_confirmed_opponent_turn = Mock()

    def observe(self, seconds, river, observed=True):
        stamp = datetime.fromtimestamp(seconds, timezone.utc).isoformat()
        self.operator.observe_post_call_timeout_river({
            "capturedAt": stamp, "ownDiscards": river, "ownDiscardsObserved": observed,
        })

    def recover(self, captured_at=30.0, melds=1, occupied=False):
        with patch("auto_operator.geometric_open_meld_count", return_value=melds):
            return self.operator.recover_post_call_timeout(
                frame=b"frame", captured_at=captured_at, open_melds=melds, draw_occupied=occupied,
            )

    def test_two_fresh_river_captures_and_later_empty_draw_release(self):
        river = ["2p", "9p", "4m", "N", "8s"]
        with patch("auto_operator.time.monotonic", return_value=20):
            self.observe(101, river)
            self.assertFalse(self.recover())
            self.observe(102, river)
        self.assertTrue(self.recover())
        self.assertFalse(self.operator.pending_post_call_discard)
        self.operator.clear_discard_evidence_on_confirmed_opponent_turn.assert_called_once()

    def test_no_recovery_from_old_duplicate_incomplete_or_different_rivers(self):
        river = ["2p", "9p", "4m", "N", "8s"]
        with patch("auto_operator.time.monotonic", return_value=20):
            self.observe(99, river)
            self.observe(101, river)
            self.observe(101, river)
            self.assertFalse(self.recover())
            self.observe(102, river, observed=False)
            self.observe(103, river[:-1] + ["7s"])
            self.assertFalse(self.recover())
            self.observe(104, river)
            self.assertFalse(self.recover())

    def test_occupied_draw_stale_frame_uncertainty_and_unexpired_clock_fail_closed(self):
        river = ["2p", "9p", "4m", "N", "8s"]
        with patch("auto_operator.time.monotonic", return_value=20):
            self.observe(101, river)
            self.observe(102, river)
        self.assertFalse(self.recover(captured_at=19))
        self.assertFalse(self.recover(occupied=True))
        self.assertFalse(self.recover(melds=2))
        self.operator.selection_uncertainty_latch = {"unsafe": True}
        self.assertFalse(self.recover())
        self.operator.selection_uncertainty_latch = None
        self.operator.force_auto_action_evidence_age_ms.return_value = 2599
        self.assertFalse(self.recover())
        self.operator.clear_discard_evidence_on_confirmed_opponent_turn.assert_not_called()
