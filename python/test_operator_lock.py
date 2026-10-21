import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from operator_lock import OperatorAlreadyRunning, lock_path, operator_lease


class OperatorLockTest(unittest.TestCase):
    def setUp(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.cdp = f"http://127.0.0.1:{self.port}"
        self.root = Path(__file__).resolve().parents[1]

    def test_same_browser_aliases_share_lock_across_checkouts(self):
        with operator_lease(self.cdp):
            with self.assertRaises(OperatorAlreadyRunning):
                with operator_lease(f"http://localhost:{self.port}"):
                    self.fail("duplicate acquired")
            with operator_lease(f"http://127.0.0.1:{self.port % 65534 + 1}"):
                pass  # A different browser endpoint remains independent.

    def test_direct_cli_rejects_before_reading_layout_or_connecting(self):
        with tempfile.TemporaryDirectory() as directory, operator_lease(self.cdp):
            artifacts = Path(directory) / "rejected"
            result = subprocess.run([sys.executable, str(self.root / "python/auto_operator.py"),
                "--project", directory, "--cdp", f"http://localhost:{self.port}",
                "--layout", "missing-layout", "--templates", "missing-templates",
                "--state", "missing-state", "--artifacts", str(artifacts)],
                cwd=directory, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2, result.stderr)
            row = json.loads(result.stdout)
            self.assertEqual(row["event"], "duplicate_operator_stop")
            self.assertEqual(json.loads((artifacts / "operator-startup.jsonl").read_text()), row)
            self.assertFalse((artifacts / "python-operator.jsonl").exists())
            self.assertFalse((artifacts / "frames").exists())

    def test_crashed_owner_releases_kernel_lock_without_deleting_file(self):
        environment = {**os.environ, "PYTHONPATH": str(self.root / "python")}
        with tempfile.TemporaryDirectory() as directory:
            child = subprocess.Popen([sys.executable, "-c",
                "import sys,time; from operator_lock import operator_lease; "
                "lease=operator_lease(sys.argv[1]); lease.__enter__(); "
                "print('held',flush=True); time.sleep(30)", self.cdp],
                cwd=directory, env=environment, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), "held")
                with self.assertRaises(OperatorAlreadyRunning):
                    with operator_lease(self.cdp):
                        self.fail("duplicate acquired")
                child.kill()
                child.wait(timeout=5)
                self.assertTrue(lock_path(self.cdp).exists())
                with operator_lease(self.cdp):
                    pass
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
                child.stdout.close()


    def test_connection_failure_closes_recognizers_and_releases_lease(self):
        import auto_operator
        operator = Mock()
        playwright = Mock()
        playwright.chromium.connect_over_cdp.side_effect = RuntimeError("browser unavailable")
        context = Mock()
        context.__enter__ = Mock(return_value=playwright)
        context.__exit__ = Mock(return_value=False)
        with patch.object(auto_operator, "parse_args", return_value=SimpleNamespace(cdp=self.cdp)), \
                patch.object(auto_operator, "PythonAutoOperator", return_value=operator), \
                patch.object(auto_operator, "sync_playwright", return_value=context):
            with self.assertRaisesRegex(RuntimeError, "browser unavailable"):
                auto_operator.main()
        operator.run.assert_not_called()
        operator.close.assert_called_once()
        with operator_lease(self.cdp):
            pass


if __name__ == "__main__":
    unittest.main()
