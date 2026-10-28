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


if __name__ == "__main__":
    unittest.main()
