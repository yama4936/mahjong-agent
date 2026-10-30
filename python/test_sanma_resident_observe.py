import io
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from auto_operator import PythonAutoOperator


class ResidentObservationTests(unittest.TestCase):
    def operator(self, response):
        op = object.__new__(PythonAutoOperator)
        op.recognition_request_id = 0
        op.recognition_server = SimpleNamespace(poll=lambda: None, stdin=io.StringIO(), stdout=io.StringIO(json.dumps(response) + '\n'))
        return op

    def test_only_read_only_request_and_reply_are_accepted(self):
        op = self.operator({'id': 1, 'result': {'scope': 'offline_untrusted_sanma_auto_observation', 'operationAuthorized': False}})
        result = op.observe_sanma_resident(Path('frame.png'))
        self.assertFalse(result['operationAuthorized'])
        self.assertEqual(json.loads(op.recognition_server.stdin.getvalue()), {'id': 1, 'screenshot': 'frame.png', 'observeSanma': True})

    def test_bad_id_error_or_executable_reply_are_rejected(self):
        for response in ({'id': 2, 'result': {}}, {'id': 1, 'error': 'unavailable'},
                         {'id': 1, 'result': {'scope': 'offline_untrusted_sanma_auto_observation', 'operationAuthorized': True}},
                         {'id': 1, 'result': {'scope': 'offline_untrusted_sanma_auto_observation'}}):
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                self.operator(response).observe_sanma_resident(Path('frame.png'))


if __name__ == '__main__':
    unittest.main()
