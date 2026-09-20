import json
import base64
import tempfile
import unittest
from pathlib import Path
from dashboard import HTML, capture_cdp_screenshot, read_operator_status


class DashboardTest(unittest.TestCase):
    def test_raw_cdp_capture_does_not_use_page_viewport_emulation(self):
        class Session:
            def __init__(self):
                self.calls = []

            def send(self, method, params):
                self.calls.append((method, params))
                return {"data": base64.b64encode(b"png").decode()}

        session = Session()
        self.assertEqual(capture_cdp_screenshot(session), b"png")
        self.assertEqual(session.calls, [("Page.captureScreenshot", {
            "format": "png", "fromSurface": True, "captureBeyondViewport": False,
        })])

    def test_dashboard_renders_choice_probabilities(self):
        self.assertIn('aria-label="選択肢と選択確率"', HTML)
        self.assertIn("d?.jev?.probabilities", HTML)
        self.assertIn("percent(probabilities[id])", HTML)

    def test_dashboard_renders_reaction_actions_without_a_discard_tile(self):
        self.assertIn("selected.action||d.recommendedAction", HTML)
        self.assertIn("pon:'ポン'", HTML)
        self.assertIn("pass:'見送り'", HTML)
        self.assertIn("e.status==='reaction_prompt'", HTML)

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
