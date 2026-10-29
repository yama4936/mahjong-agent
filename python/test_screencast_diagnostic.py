import tempfile
import json
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from auto_operator import parse_args
from screencast_diagnostic import ScreencastDiagnostic
from analyze_screencast_timing import analyze


class ScreencastDiagnosticTest(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch("sys.argv", ["operator", "--layout", "x", "--templates", "x", "--state", "x"]):
            self.assertIsNone(parse_args().screencast_diagnostic)

    def test_record_and_expiration(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = ScreencastDiagnostic(directory, duration=1)
            recorder.offer(1, 10.0, {"timestamp": 123}, b"frame")
            recorder.offer(2, 11.1, {}, b"late")
            result = recorder.close()
            self.assertFalse(result["workerAlive"])
            self.assertEqual(result["pending"], 0)
            self.assertEqual((recorder.directory / "00000001.jpg").read_bytes(), b"frame")
            self.assertIn('"receiptMonotonic": 10.0', (recorder.directory / "receipts.jsonl").read_text())
            self.assertFalse((recorder.directory / "00000002.jpg").exists())

    def test_full_queue_does_not_block_and_close_reports_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = ScreencastDiagnostic(directory, capacity=1)
            started, release = threading.Event(), threading.Event()
            def slow_write(item):
                started.set()
                release.wait(3)
            recorder._write = slow_write
            recorder.offer(1, 0, {}, b"one")
            self.assertTrue(started.wait(1))
            recorder.offer(2, 0.1, {}, b"two")
            before = time.monotonic()
            recorder.offer(3, 0.2, {}, b"three")
            self.assertLess(time.monotonic() - before, 0.1)
            result = recorder.close(timeout=0.01)
            self.assertEqual(result["droppedSequences"], [3])
            self.assertTrue(result["workerAlive"])
            self.assertEqual(result["pending"], 1)
            release.set()
            self.assertFalse(recorder.close(timeout=2)["workerAlive"])

    def test_write_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = ScreencastDiagnostic(directory)
            recorder._write = lambda item: (_ for _ in ()).throw(OSError("disk failure"))
            recorder.offer(1, 1, {}, b"x")
            result = recorder.close()
            self.assertEqual(result["writeErrors"][0]["sequence"], 1)
            self.assertIn("disk failure", result["writeErrors"][0]["error"])

    def test_clock_record_and_analysis_is_diagnostic_only(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = ScreencastDiagnostic(directory)
            recorder.offer(1, 10, {"timestamp": 1000}, b"a", receipt_wall=1000.4)
            recorder.offer(2, 10.2, {"timestamp": 1000.1}, b"b", receipt_wall=1000.6)
            recorder.close()
            records = [json.loads(line) for line in (recorder.directory / "receipts.jsonl").read_text().splitlines()]
            result = list(analyze(records))
            self.assertEqual(result[0]["uncalibratedWallMinusCdpMs"], 400)
            self.assertEqual(result[1]["cdpIntervalMs"], 100)
            self.assertEqual(result[1]["receiptIntervalMs"], 200)
            self.assertEqual(result[1]["issues"], [])

    def test_invalid_or_discontinuous_clocks_are_flagged(self):
        records = [
            {"sequence": 1, "receiptMonotonic": 1, "receiptWallTime": 100, "cdpMetadata": {"timestamp": 90}},
            {"sequence": 3, "receiptMonotonic": 2, "receiptWallTime": 102, "cdpMetadata": {"timestamp": 90}},
            {"sequence": 4, "receiptMonotonic": 3, "cdpMetadata": {"timestamp": float("nan")}},
        ]
        result = list(analyze(records))
        self.assertIn("sequence_gap_or_reordering", result[1]["issues"])
        self.assertIn("cdp_timestamp_not_increasing", result[1]["issues"])
        self.assertIn("wall_clock_discontinuity", result[1]["issues"])
        self.assertIn("missing_or_invalid_cdp_timestamp", result[2]["issues"])
        self.assertNotIn("uncalibratedWallMinusCdpMs", result[2])

    def test_reused_root_preserves_legacy_and_separates_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "receipts.jsonl").write_text("legacy\n")
            (root / "00000001.jpg").write_bytes(b"legacy")
            first = ScreencastDiagnostic(root)
            first.offer(1, 1, {"timestamp": 10}, b"first", receipt_wall=11)
            first_result = first.close()
            second = ScreencastDiagnostic(root)
            second.offer(1, 2, {"timestamp": 20}, b"second", receipt_wall=21)
            second_result = second.close()
            self.assertNotEqual(first.directory, second.directory)
            self.assertEqual(first_result["directory"], str(first.directory))
            self.assertEqual(second_result["directory"], str(second.directory))
            self.assertEqual((first.directory / "00000001.jpg").read_bytes(), b"first")
            self.assertEqual((second.directory / "00000001.jpg").read_bytes(), b"second")
            self.assertEqual((root / "00000001.jpg").read_bytes(), b"legacy")
            self.assertEqual((root / "receipts.jsonl").read_text(), "legacy\n")
            for recorder in (first, second):
                records = [json.loads(line) for line in (recorder.directory / "receipts.jsonl").read_text().splitlines()]
                self.assertEqual(len(list(analyze(records))), 1)


if __name__ == "__main__":
    unittest.main()
