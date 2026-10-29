import json
import os
from pathlib import Path
import tempfile
import unittest

from telemetry import MAX_BYTES, Telemetry


STAMP = '2026-10-29T06:30:00+00:00'


def decision(**changes):
    data = {'recommendedAction': 'discard', 'tile': 'E', 'selectedActionId': 'b',
            'source': 'jev', 'candidates': [
                {'actionId': 'a', 'action': 'discard', 'tile': 'W', 'winProbability': .9},
                {'actionId': 'b', 'action': 'discard', 'tile': 'E', 'winProbability': .2,
                 'dealInProbability': .03, 'shanten': 2}]}
    data.update(changes)
    return {'event': 'decision', 'timestamp': STAMP, 'evaluation': {
        'decision': data, 'recognition': {'safe': False, 'confidence': .7}}}


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'run' / 'python-operator.jsonl'
        self.path.parent.mkdir()
        self.telemetry = Telemetry(self.root)

    def write(self, *records, mode='ab', path=None):
        with (path or self.path).open(mode) as output:
            for record in records:
                output.write(json.dumps(record).encode() + b'\n')

    def test_selected_candidate_and_safe_false(self):
        self.write(decision())
        state = self.telemetry.snapshot()
        self.assertEqual(state['decision']['winProbability'], .2)
        self.assertEqual(state['decision']['dealInProbability'], .03)
        self.assertIs(state['decision']['recognitionSafe'], False)
        self.assertEqual(state['updatedAt'], STAMP)
        self.assertEqual(state, self.telemetry.snapshot())

    def test_no_first_candidate_fallback(self):
        self.write(decision(selectedActionId='missing'))
        self.assertIsNone(self.telemetry.snapshot()['decision']['winProbability'])
        self.write(decision(selectedActionId=None))
        self.assertEqual(self.telemetry.snapshot()['decision']['winProbability'], .2)

    def test_partial_line_and_incremental_append(self):
        raw = json.dumps(decision()).encode()
        self.path.write_bytes(raw[:150])
        self.assertIsNone(self.telemetry.snapshot()['decision'])
        with self.path.open('ab') as stream:
            stream.write(raw[150:] + b'\n')
        self.assertEqual(len(self.telemetry.snapshot()['logs']), 1)
        self.assertEqual(len(self.telemetry.snapshot()['logs']), 1)

    def test_rotation_clears_decision_ids_monotonic(self):
        self.write(decision())
        first = self.telemetry.snapshot()['logs'][0]['id']
        new = self.root / 'new' / 'operator' / 'python-operator.jsonl'
        new.parent.mkdir(parents=True)
        self.write({'event': 'click_sent', 'timestamp': STAMP}, path=new)
        os.utime(new, ns=(self.path.stat().st_mtime_ns + 1000000,) * 2)
        self.telemetry.discover_at = 0
        state = self.telemetry.snapshot()
        self.assertIsNone(state['decision'])
        self.assertEqual(state['logs'][0]['id'].split(':')[0], first.split(':')[0])
        self.assertGreater(int(state['logs'][0]['id'].split(':')[1]), int(first.split(':')[1]))

    def test_truncation_and_terminal_clear_decision(self):
        self.write(decision())
        self.telemetry.snapshot()
        self.write({'event': 'outcome_observed', 'timestamp': STAMP}, mode='wb')
        state = self.telemetry.snapshot()
        self.assertIsNone(state['decision'])
        self.assertEqual(len(state['logs']), 1)
        self.write(decision(), {'event': 'terminal', 'timestamp': STAMP})
        self.assertIsNone(self.telemetry.snapshot()['decision'])

    def test_allowlist_no_raw_content_and_malformed_structures(self):
        self.write({'event': 'secret', 'error': 'SECRET'},
                   {'event': 'action_aborted', 'error': 'SECRET', 'timestamp': 'SECRET'},
                   {'event': ['SECRET']}, ['SECRET'],
                   decision(source='SECRET', recommendedAction=['SECRET'], tile='SECRET',
                            candidates=[None, {'actionId': 'b', 'winProbability': float('nan'),
                                               'dealInProbability': 10 ** 999}]))
        state = self.telemetry.snapshot()
        self.assertNotIn('SECRET', json.dumps(state))
        self.assertIsNone(state['decision']['winProbability'])
        self.assertIsNone(state['decision']['dealInProbability'])

    def test_bounded_initial_tail_and_ring(self):
        self.path.write_bytes(b'x' * (MAX_BYTES * 2) + b'\n')
        self.write(*[{'event': 'click_sent', 'timestamp': STAMP}] * 150)
        state = self.telemetry.snapshot()
        self.assertEqual(len(state['logs']), 100)
        self.assertEqual(int(state['logs'][-1]['id'].split(':')[1]), 150)
        self.assertLessEqual(len(self.telemetry.partial), MAX_BYTES)

    def test_oversized_partial_does_not_grow_unbounded(self):
        self.path.write_bytes(b'x' * MAX_BYTES)
        self.telemetry.snapshot()
        with self.path.open('ab') as stream:
            stream.write(b'x' * MAX_BYTES)
        self.telemetry.snapshot()
        self.assertLessEqual(len(self.telemetry.partial), MAX_BYTES)
        with self.path.open('ab') as stream:
            stream.write(b'\n')
        self.write(decision())
        self.assertEqual(self.telemetry.snapshot()['decision']['winProbability'], .2)

    def test_missing_directory_returns_empty(self):
        self.assertEqual(Telemetry(self.root / 'missing').snapshot(),
                         {'updatedAt': None, 'decision': None, 'logs': []})

    def test_restart_has_distinct_ids_and_decision_log_is_useful(self):
        self.write(decision())
        first = self.telemetry.snapshot()['logs'][0]
        restarted = Telemetry(self.root).snapshot()['logs'][0]
        self.assertNotEqual(first['id'], restarted['id'])
        self.assertEqual(first['message'], '判断を更新: discard E')
        self.assertEqual(first['action'], 'discard')
        self.assertEqual(first['tile'], 'E')


if __name__ == '__main__':
    unittest.main()
