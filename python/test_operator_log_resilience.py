"""A terminal mirror is optional; evidence files and RPC failures are not."""
import errno
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from auto_operator import PythonAutoOperator


class OperatorLogResilienceTest(unittest.TestCase):
    def make(self, folder):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.log_path = Path(folder) / "python-operator.jsonl"
        operator.analysis_recorder = Mock()
        return operator

    def test_broken_pipe_disables_only_mirror_and_keeps_all_raw_payloads(self):
        with tempfile.TemporaryDirectory() as folder:
            operator = self.make(folder)
            payload = {"nested": {"candidates": [{"tile": "0s", "value": 123}]}, "label": "記録"}
            with patch("sys.stdout") as stream, patch("builtins.print", side_effect=BrokenPipeError(errno.EPIPE, "closed")) as output:
                stream.fileno.side_effect = io.UnsupportedOperation("no descriptor in this mock")
                operator.log("decision", **payload)
                operator.log("continued", tile="9s")
            output.assert_called_once()
            rows = [json.loads(line) for line in operator.log_path.read_text().splitlines()]
            self.assertEqual([row["event"] for row in rows], ["decision", "continued"])
            self.assertEqual(rows[0]["nested"], payload["nested"])
            self.assertEqual(rows[0]["label"], "記録")
            self.assertEqual(operator.analysis_recorder.observe.call_count, 2)

    def test_plain_oserror_epipe_is_handled_but_other_io_errors_still_raise(self):
        for error in (OSError(errno.EPIPE, "closed"), OSError(errno.EIO, "other IO failure")):
            with self.subTest(errno=error.errno), tempfile.TemporaryDirectory() as folder:
                operator = self.make(folder)
                with patch("sys.stdout") as stream, patch("builtins.print", side_effect=error):
                    stream.fileno.side_effect = io.UnsupportedOperation("no descriptor in this mock")
                    if error.errno == errno.EPIPE:
                        operator.log("written")
                        self.assertTrue(operator.console_mirror_disconnected)
                    else:
                        with self.assertRaises(OSError) as caught:
                            operator.log("written")
                        self.assertIs(caught.exception, error)
                        self.assertFalse(getattr(operator, "console_mirror_disconnected", False))
                self.assertEqual(json.loads(operator.log_path.read_text())["event"], "written")

    def test_durable_sink_failure_is_not_swallowed_even_after_mirror_disconnect(self):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.console_mirror_disconnected = True
        operator.log_path = Mock()
        operator.log_path.open.side_effect = OSError(errno.ENOSPC, "disk full")
        with patch("builtins.print") as output, self.assertRaises(OSError) as caught:
            operator.log("not_saved")
        self.assertEqual(caught.exception.errno, errno.ENOSPC)
        output.assert_not_called()

    def test_normal_mirror_and_analysis_still_receive_complete_record(self):
        with tempfile.TemporaryDirectory() as folder:
            operator = self.make(folder)
            with patch("builtins.print") as output:
                operator.log("normal", action="pass")
            row = json.loads(operator.log_path.read_text())
            self.assertEqual(json.loads(output.call_args.args[0]), row)
            self.assertEqual(output.call_args.kwargs, {"flush": True})
            operator.analysis_recorder.observe.assert_called_once_with(row)

    def test_unrelated_public_rpc_broken_pipe_is_still_a_failure(self):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.console_mirror_disconnected = True
        import threading
        operator.public_recognition_io_lock = threading.Lock()
        operator.public_recognition_server = Mock()
        operator.public_recognition_server.poll.return_value = None
        error = BrokenPipeError(errno.EPIPE, "RPC lost its reader")
        operator.public_recognition_server.stdin.write.side_effect = error
        with self.assertRaises(BrokenPipeError) as caught:
            operator.request_public_recognition({"id": 1})
        self.assertIs(caught.exception, error)

    def test_real_disconnected_pipe_preserves_records_and_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "operator.jsonl"
            code = (
                "from auto_operator import PythonAutoOperator;"
                "from unittest.mock import Mock;from pathlib import Path;import sys;"
                "op=PythonAutoOperator.__new__(PythonAutoOperator);"
                "op.log_path=Path(sys.argv[1]);op.analysis_recorder=Mock();"
                "op.log('first',nested={'value':123});op.log('continued');"
                "sys.stderr.write('stderr still available\\n')"
            )
            child = subprocess.Popen([sys.executable, "-c", code, str(path)],
                                     cwd=Path(__file__).resolve().parent,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            child.stdout.close()
            stderr = child.stderr.read()
            child.stderr.close()
            self.assertEqual(child.wait(timeout=5), 0, stderr)
            self.assertEqual(stderr, b"stderr still available\n")
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([row["event"] for row in rows], ["first", "continued"])
            self.assertEqual(rows[0]["nested"], {"value": 123})


if __name__ == "__main__":
    unittest.main()
