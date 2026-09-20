import json
import tempfile
import unittest
from pathlib import Path
from dashboard import HTML, read_operator_status


class DashboardTest(unittest.TestCase):
    def test_dashboard_renders_choice_probabilities(self):
        self.assertIn('aria-label="選択肢と選択確率"', HTML)
        self.assertIn("d?.jev?.probabilities", HTML)
        self.assertIn("percent(probabilities[id])", HTML)

    def test_missing_log(self):
        self.assertIsNone(read_operator_status(None)["judgment"])

    def test_stopped_event_keeps_last_evaluation_and_skips_partial_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.jsonl"
            judgment = {"event": "not_ready", "timestamp": "2026-09-20T00:00:00Z",
                        "evaluation": {"recognition": {"safe": False, "tiles": ["8p"]}}}
            path.write_text(json.dumps(judgment)+'\n'+json.dumps({"event":"stopped"})+'\n{"event":', encoding="utf-8")
            status = read_operator_status(path)
            self.assertEqual(status["lastEvent"], "stopped")
            self.assertEqual(status["judgment"], judgment)

    def test_new_run_clears_old_recommendation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.jsonl"
            path.write_text('{"evaluation":{"decision":{"tile":"1m"}}}\n{"event":"started"}\n', encoding="utf-8")
            self.assertIsNone(read_operator_status(path)["judgment"])
