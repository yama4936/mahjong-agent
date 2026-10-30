import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from auto_operator import PythonAutoOperator


class ResidentObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / 'frame.png'
        self.file.write_bytes(b'fake frame')
        self.digest = hashlib.sha256(b'fake frame').hexdigest()

    def result(self):
        return {'scope': 'offline_untrusted_sanma_auto_observation', 'operationAuthorized': False,
                'digest': self.digest, 'report': {'digest': self.digest},
                'assembly': {'operationAuthorized': False, 'priority': {'status': 'blocked'}, 'evaluation': {'status': 'blocked'}}}

    def operator(self, response):
        op = object.__new__(PythonAutoOperator)
        op.recognition_request_id = 0
        op.frames = Path(self.temp.name)
        op.log = Mock()
        op.recognition_server = SimpleNamespace(poll=lambda: None, stdin=io.StringIO(), stdout=io.StringIO(json.dumps(response) + '\n'))
        return op

    def test_only_read_only_request_and_matching_image_are_accepted(self):
        op = self.operator({'id': 1, 'result': self.result()})
        result = op.observe_sanma_resident(self.file)
        self.assertFalse(result['operationAuthorized'])
        self.assertEqual(json.loads(op.recognition_server.stdin.getvalue()), {'id': 1, 'screenshot': str(self.file), 'observeSanma': True})

    def test_bad_id_error_executable_or_other_frame_are_rejected(self):
        for response in ({'id': 2, 'result': self.result()}, {'id': 1, 'error': 'unavailable'},
                         {'id': 1, 'result': {**self.result(), 'operationAuthorized': True}},
                         {'id': 1, 'result': {**self.result(), 'digest': '0' * 64}},
                         {'id': 1, 'result': {**self.result(), 'report': {'digest': '0' * 64}}}):
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                self.operator(response).observe_sanma_resident(self.file)

    def test_frame_changed_during_observation_is_rejected(self):
        op = self.operator({'id': 1, 'result': self.result()})
        path = self.file
        class MutatingInput(io.StringIO):
            def flush(self):
                path.write_bytes(b'changed frame')
                super().flush()
        op.recognition_server.stdin = MutatingInput()
        with self.assertRaisesRegex(RuntimeError, 'does not match screenshot'):
            op.observe_sanma_resident(self.file)

    def test_page_capture_routes_priority_to_blocked_receipt_without_click(self):
        op = self.operator({'id': 1, 'result': self.result()})
        page = Mock()
        page.screenshot.return_value = b'fake frame'
        receipt = op.inspect_sanma_self_turn(page)
        self.assertEqual(receipt['status'], 'blocked')
        self.assertEqual(receipt['priority']['status'], 'blocked')
        self.assertFalse(receipt['operationAuthorized'])
        self.assertEqual(Path(receipt['screenshot']).read_bytes(), b'fake frame')
        page.mouse.click.assert_not_called()
        op.log.assert_called_once()

    def test_executable_priority_is_rejected_without_click(self):
        bad = self.result()
        bad['assembly']['priority'] = {'status': 'offline_priority'}
        op = self.operator({'id': 1, 'result': bad})
        page = Mock()
        page.screenshot.return_value = b'fake frame'
        with self.assertRaisesRegex(RuntimeError, 'fail closed'):
            op.inspect_sanma_self_turn(page)
        page.mouse.click.assert_not_called()


class ResidentSanmaEndToEndTests(unittest.TestCase):
    @unittest.skipUnless(
        (Path('artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-05-55-331Z-before.png').exists()
         and Path('.runtime/python-auto-venv/bin/python').exists()
         and Path('.runtime/hybrid-vision/cvmaj-pretrained.tar').exists()
         and Path('templates/bootstrap/1m__hf_base.png').exists()), 'local sanma image or model unavailable')
    def test_mock_page_through_real_resident_server_never_clicks(self):
        import subprocess
        from unittest.mock import Mock
        source = Path('artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-05-55-331Z-before.png')
        page = Mock()
        page.screenshot.return_value = source.read_bytes()
        child = subprocess.Popen(['node', '--import', 'tsx', 'src/recognition/recognitionServer.ts',
                                  'config/layout-runtime.json', 'templates/bootstrap', 'examples/public-unknown.json'],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, encoding='utf-8')
        self.addCleanup(lambda: child.poll() is None and child.kill())
        self.assertTrue(json.loads(child.stdout.readline())['ready'])
        with tempfile.TemporaryDirectory() as directory:
            op = object.__new__(PythonAutoOperator)
            op.recognition_request_id = 0
            op.recognition_server = child
            op.frames = Path(directory)
            op.log = Mock()
            receipt = op.inspect_sanma_self_turn(page)
            self.assertEqual(receipt['status'], 'blocked')
            self.assertFalse(receipt['operationAuthorized'])
            self.assertTrue(any(candidate['action'] == 'kita' for candidate in receipt['candidates']['candidates']))
            self.assertIn('complete independent review missing', receipt['priority']['reasons'])
            self.assertEqual(receipt['drawCandidate']['status'], 'candidate')
            self.assertEqual(receipt['drawCandidate']['tile'], 'E')
            self.assertEqual(receipt['drawCandidate']['index'], 13)
            self.assertFalse(receipt['drawCandidate']['verified'])
            self.assertFalse(receipt['drawCandidate']['operationAuthorized'])
            with self.assertRaisesRegex(RuntimeError, 'sanma execution'):
                op.execute(page, receipt)
            self.assertEqual(Path(receipt['screenshot']).read_bytes(), page.screenshot.return_value)
            page.mouse.click.assert_not_called()
            open_frame = Path('artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-21-44-430Z-before.png')
            page.screenshot.return_value = open_frame.read_bytes()
            open_receipt = op.inspect_sanma_self_turn(page)
            self.assertEqual(open_receipt['status'], 'blocked')
            self.assertEqual(open_receipt['drawCandidate']['status'], 'candidate')
            self.assertEqual(open_receipt['drawCandidate']['tile'], 'N')
            self.assertEqual(open_receipt['drawCandidate']['index'], 10)
            self.assertFalse(open_receipt['drawCandidate']['operationAuthorized'])
            page.mouse.click.assert_not_called()
        child.stdin.close()
        child.wait(timeout=20)
        child.stdout.close()


if __name__ == '__main__':
    unittest.main()
