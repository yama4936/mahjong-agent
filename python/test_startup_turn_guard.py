import unittest

from startup_turn_guard import StartupTurnGuard


class StartupTurnGuardTests(unittest.TestCase):
    def test_initial_draw_never_gets_a_fresh_clock(self):
        guard = StartupTurnGuard()
        self.assertEqual(guard.observe(verified_match=True, action_visible=True, now=0), "quarantine")
        self.assertEqual(guard.observe(verified_match=True, action_visible=True, now=300), "quarantine")
        self.assertEqual(guard.observe(verified_match=True, action_visible=False, now=301), "wait")
        self.assertEqual(guard.observe(verified_match=True, action_visible=False, now=302), "ready")
        self.assertEqual(guard.observe(verified_match=True, action_visible=True, now=303), "ready")

    def test_transient_or_unknown_frames_do_not_end_quarantine(self):
        guard = StartupTurnGuard()
        guard.observe(verified_match=True, action_visible=True, now=0)
        guard.observe(verified_match=True, action_visible=False, now=1)
        guard.observe(verified_match=False, action_visible=False, now=2)
        self.assertEqual(guard.observe(verified_match=True, action_visible=True, now=3), "quarantine")

    def test_initial_opponent_turn_establishes_boundary(self):
        guard = StartupTurnGuard()
        self.assertEqual(guard.observe(verified_match=True, action_visible=False, now=0), "wait")
        self.assertEqual(guard.observe(verified_match=True, action_visible=False, now=1), "ready")

    def test_verified_start_preserves_conservative_initial_action_clock(self):
        guard = StartupTurnGuard()
        guard.record_verified_start_click(clicked_at=10)
        self.assertEqual(guard.observe(verified_match=False, action_visible=False, now=12), "wait")
        self.assertEqual(guard.observe(verified_match=True, action_visible=True, now=20), "ready")
        self.assertEqual(guard.initial_action_anchor, 10)

    def test_dealing_bound_uses_request_start_not_capture_completion(self):
        guard = StartupTurnGuard()
        guard.record_verified_start_click(clicked_at=10)
        self.assertTrue(guard.record_verified_dealing_bound(request_started_at=20, observed_at=22))
        self.assertEqual(guard.observe(verified_match=True, action_visible=True, now=23), "ready")
        self.assertEqual(guard.initial_action_anchor, 20)
        self.assertFalse(guard.record_verified_dealing_bound(request_started_at=24, observed_at=25))

    def test_dealing_bound_cannot_authorize_unknown_or_stale_start(self):
        guard = StartupTurnGuard()
        self.assertFalse(guard.record_verified_dealing_bound(request_started_at=20, observed_at=21))
        guard.record_verified_start_click(clicked_at=10)
        self.assertFalse(guard.record_verified_dealing_bound(request_started_at=9, observed_at=20))
        self.assertFalse(guard.record_verified_dealing_bound(request_started_at=20, observed_at=41))
        self.assertTrue(guard.record_verified_dealing_bound(request_started_at=20, observed_at=21))
        self.assertEqual(guard.observe(verified_match=True, action_visible=True, now=41), "quarantine")

    def test_stale_or_reversed_start_and_existing_quarantine_fail_closed(self):
        for now in (9, 41):
            guard = StartupTurnGuard()
            guard.record_verified_start_click(clicked_at=10)
            self.assertEqual(guard.observe(verified_match=True, action_visible=True, now=now), "quarantine")
        guard = StartupTurnGuard()
        guard.observe(verified_match=True, action_visible=True, now=1)
        guard.record_verified_start_click(clicked_at=2)
        self.assertEqual(guard.observe(verified_match=True, action_visible=True, now=3), "quarantine")

    def test_no_initial_action_does_not_backdate_later_turn(self):
        guard = StartupTurnGuard()
        guard.record_verified_start_click(clicked_at=10)
        self.assertEqual(guard.observe(verified_match=True, action_visible=False, now=15), "wait")
        self.assertEqual(guard.observe(verified_match=True, action_visible=False, now=16), "ready")
        self.assertIsNone(guard.initial_action_anchor)


if __name__ == "__main__":
    unittest.main()
