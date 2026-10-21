import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from operator_supervisor import Supervisor, processes, restart_allowed, terminal_event


class SupervisorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = {"operator": [], "launcher": [], "browser": [], "profile": []}
        self.now = 100
        self.healthy = True
        self.launches = []
        self.commit = patch("operator_supervisor.subprocess.check_output", return_value="test-commit\n")
        self.commit.start()
        self.addCleanup(self.commit.stop)
        self.supervisor = self.make_supervisor()

    def make_supervisor(self):
        return Supervisor(self.root, self.root / "artifacts/supervisor", "layout.json",
                          clock=lambda: self.now, scan=lambda: self.state,
                          ready=lambda: self.healthy, launch=self.launch)

    def launch(self, kind, command, output):
        self.launches.append((kind, command, output))
        return 321

    def adopt(self):
        self.state["operator"] = [{"pid": 123, "args": ["python", "python/auto_operator.py",
            "--artifacts=artifacts/game"]}]
        self.supervisor.tick()
        log = self.root / "artifacts/game/operator-stdout.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        return log

    def test_live_operator_is_adopted_without_cdp_or_restart(self):
        self.supervisor.ready = lambda: self.fail("CDP must not be probed during live play")
        self.adopt()
        self.supervisor.tick()
        self.assertEqual(self.launches, [])

    def test_closed_browser_recovers_after_operator_exit_only(self):
        log = self.adopt()
        log.write_text(json.dumps({"event": "safety_stop", "error":
            "Page.wait_for_timeout: Target page, context or browser has been closed"}) + "\n")
        self.healthy = False
        self.state["operator"] = []
        self.supervisor.tick()
        self.assertEqual(self.launches, [])  # Exit grace period.
        self.now += 11
        self.supervisor.tick()
        self.assertEqual([row[0] for row in self.launches], ["browser"])
        self.healthy = True
        self.now += 11
        self.supervisor.tick()
        self.assertEqual([row[0] for row in self.launches], ["browser", "operator"])
        command = self.launches[-1][1]
        for arg in ("--force-auto-click-budget-ms=2600", "--action-deadline-ms=300000", "--ranked-loop"):
            self.assertIn(arg, command)

    def test_safety_stops_persist_across_supervisor_restart(self):
        for event in ("ranked_click_budget_safety_stop", "screen_loss_stop", "safety_stop", "match_completed_stop",
                      "ranked_terminal_transition_stop", "login_required_stop", "blocking_dialog_stop",
                      "connection_recovery_limit_stop", "black_screen_recovery_limit_stop",
                      "black_screen_outcome_missing_stop", "future_guard_stop"):
            with self.subTest(event=event):
                log = self.adopt()
                log.write_text(json.dumps({"event": event, "error": "unknown"}) + "\n")
                self.state["operator"] = []
                self.supervisor.tick()
                self.now += 11
                self.supervisor = self.make_supervisor()
                self.supervisor.tick()
                self.assertTrue(self.supervisor.held)
                self.assertEqual(self.launches, [])
                self.supervisor.hold_file.unlink()
                self.supervisor = self.make_supervisor()

    def test_cdp_timeout_does_not_duplicate_existing_browser(self):
        self.healthy = False
        for kind in ("browser", "profile"):
            self.state[kind] = [{"pid": 456}]
            self.supervisor.tick()
            self.now += 30
            self.assertEqual(self.launches, [])
            self.state[kind] = []

    def test_launcher_startup_does_not_spawn_another_operator(self):
        self.state["launcher"] = [{"pid": 654}]
        self.supervisor.tick()
        self.now += 30
        self.supervisor.tick()
        self.assertEqual(self.launches, [])

    def test_duplicate_operators_are_recorded_without_signalling_them(self):
        self.state["operator"] = [{"pid": 1}, {"pid": 2}]
        self.supervisor.tick()
        self.assertTrue(self.supervisor.held)
        self.assertEqual(self.launches, [])

    def test_repeated_unknown_crashes_are_bounded(self):
        for _ in range(4):
            self.supervisor.tick()
            self.now += 11
            self.supervisor.tick()
            self.now += 11
        self.assertEqual(len(self.launches), 3)
        self.assertTrue(self.supervisor.held)

    def test_browser_and_operator_have_separate_recovery_limits(self):
        self.supervisor.attempts["browser"] = [90, 95, 99]
        self.supervisor.tick()
        self.assertEqual([row[0] for row in self.launches], ["operator"])
        self.assertFalse(self.supervisor.held)

    def test_fast_terminal_stop_before_first_adoption_is_preserved(self):
        self.supervisor.tick()
        self.supervisor.operator_log.write_text('{"event":"ranked_click_budget_safety_stop"}\n')
        self.now += 11
        self.supervisor.tick()
        self.assertTrue(self.supervisor.held)
        self.assertEqual(len(self.launches), 1)

    def test_terminal_reader_ignores_old_run_after_new_started_event(self):
        log = self.root / "log"
        log.write_text('broken\n{"event":"safety_stop"}\n{"event":"started"}\n')
        self.assertIsNone(terminal_event(log))
        self.assertFalse(restart_allowed({"event": "safety_stop", "error": "other failure"}))

    def test_real_ranked_transition_stop_is_not_an_unknown_crash(self):
        from operator_supervisor import ROOT
        log = ROOT / "test/fixtures/ranked-terminal-transition-stop-20261020.jsonl"
        terminal = terminal_event(log)
        self.assertEqual(terminal["event"], "ranked_terminal_transition_stop")
        self.assertFalse(restart_allowed(terminal))

    def test_browser_close_during_cleanup_does_not_override_intentional_stop(self):
        log = self.root / "log"
        log.write_text(json.dumps({"event": "login_required_stop"}) + "\n" + json.dumps({
            "event": "safety_stop", "error": "Target page, context or browser has been closed"}) + "\n")
        self.assertEqual(terminal_event(log)["event"], "login_required_stop")
        log.write_text(log.read_text() + '{"event":"started"}\n' + json.dumps({
            "event": "safety_stop", "error": "Target page, context or browser has been closed"}) + "\n")
        self.assertTrue(restart_allowed(terminal_event(log)))

    def test_exit_while_supervisor_offline_still_holds_safety_stop(self):
        log = self.adopt()
        log.write_text('{"event":"screen_loss_stop"}\n')
        self.state["operator"] = []
        self.supervisor = self.make_supervisor()
        self.supervisor.tick()
        self.assertTrue(self.supervisor.held)
        self.assertEqual(self.launches, [])

    def test_repository_lock_rejects_second_supervisor_before_launch(self):
        import fcntl
        from operator_supervisor import ROOT
        lock_path = ROOT / ".runtime/operator-supervisor.lock"
        lock_path.parent.mkdir(exist_ok=True)
        with lock_path.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.skipTest("A real supervisor is already running")
            result = subprocess.run([sys.executable, str(ROOT / "python/operator_supervisor.py"),
                "--artifacts", str(self.root / "unused")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Another supervisor holds the repository lock", result.stderr)
        self.assertFalse((self.root / "unused").exists())

    def test_real_process_scan_adopts_frozen_checkout_on_same_cdp_only(self):
        # Actual script argv/cwd like the observed isolated live checkout,
        # with a harmless sleeping body instead of a real browser connection.
        script = self.root / "python/auto_operator.py"
        script.parent.mkdir()
        script.write_text("import time; time.sleep(30)\n")
        child = subprocess.Popen([sys.executable, "python/auto_operator.py",
                                  "--cdp=http://localhost:9222"], cwd=self.root)
        try:
            found = processes(self.root)
            self.assertIn(child.pid, [p["pid"] for p in found["operator"]])
            self.assertIn(child.pid, [p["pid"] for p in processes(self.root / "elsewhere")["operator"]])
            self.assertNotIn(child.pid, [p["pid"] for p in processes(self.root / "elsewhere", port=9223)["operator"]])
        finally:
            child.terminate()
            child.wait()


if __name__ == "__main__":
    unittest.main()
