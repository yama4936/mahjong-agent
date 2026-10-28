import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from auto_operator import parse_args
from screencast_diagnostic import ScreencastDiagnostic


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
            self.assertEqual((Path(directory) / "00000001.jpg").read_bytes(), b"frame")
            self.assertIn('"receiptMonotonic": 10.0', (Path(directory) / "receipts.jsonl").read_text())
            self.assertFalse((Path(directory) / "00000002.jpg").exists())

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


if __name__ == "__main__":
    unittest.main()
