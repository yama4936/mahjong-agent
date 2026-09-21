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

    def test_dashboard_renders_total_and_decision_processing_times(self):
        self.assertIn('id="processingTime"', HTML)
        self.assertIn("e.processingElapsedMs", HTML)
        self.assertIn("d?.arbitration?.elapsedMs", HTML)
        self.assertIn("(v/1000).toFixed(3)+'秒'", HTML)

    def test_dashboard_renders_end_to_end_deadline_breakdown(self):
        self.assertIn('id="deadline"', HTML)
        self.assertIn("timing.detectionToDecisionMs", HTML)
        self.assertIn("timing.decisionToClickMs", HTML)
        self.assertIn("timing.evidenceToClickMs", HTML)
        self.assertIn("timing.deadlineMet", HTML)

    def test_dashboard_renders_strategy_and_session_metrics(self):
        self.assertIn('id="targetYaku"', HTML)
        self.assertIn('id="pushFold"', HTML)
        self.assertIn('id="shape"', HTML)
        self.assertIn('id="sessionMetrics"', HTML)

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

    def test_reaction_timing_without_evaluation_is_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.jsonl"
            record = {"event": "reaction_call", "execution": {"action": "pon", "actionTiming": {
                "evidenceToClickMs": 240, "deadlineMet": True,
            }}}
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            self.assertEqual(read_operator_status(path)["judgment"], record)

    def test_session_metrics_count_deadline_retries_and_jev_difference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.jsonl"
            records = [{"event": "started"}, {"event": "decision", "recognitionRetries": 2,
                        "execution": {"actionTiming": {"deadlineMet": False}},
                        "evaluation": {"decision": {"jev": {"actionId": "discard_1m"},
                                                     "candidates": [{"actionId": "discard_2m"}]}}}]
            path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
            metrics = read_operator_status(path)["metrics"]
            self.assertEqual(metrics["deadlineMisses"], 1)
            self.assertEqual(metrics["recognitionRetries"], 2)
            self.assertEqual(metrics["jevLocalDifferences"], 1)
