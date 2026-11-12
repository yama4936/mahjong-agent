"""Offline integrity and historical guard replay for evidence189."""
import tempfile
import json
import shutil
import os
import subprocess
import sys
import unittest
from pathlib import Path

from replay_evidence189_preclick import DEFAULT_ROOT, LOG_SHA, checked, replay


class Evidence189PreclickReplayTest(unittest.TestCase):
    def test_recorded_rejections_replay(self):
        result = replay()
        self.assertFalse(result['operationAuthorized'])
        self.assertEqual([x['diagnostic']['stage'] for x in result['cases']],
                         ['hand_faces', 'binary_frame', 'hand_faces'])
        self.assertEqual(result['deadlineElapsedMs'], 301247)

    def test_tampered_log_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'operator.log'
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                checked(path, LOG_SHA)
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                replay(Path(directory))


    def test_tampered_image_and_receipt_are_rejected(self):
        rows = [json.loads(line) for line in (DEFAULT_ROOT / 'operator.log').read_bytes().splitlines()]
        rejects = [rows[i] for i in (189, 234, 242)]
        observations = [next(row for row in rows[:i] if row.get('event') == 'sanma_self_turn_observed'
                             and row['digest'] == reject['referenceSha256'])
                        for i, reject in zip((189, 234, 242), rejects)]
        paths = [DEFAULT_ROOT / 'operator.log']
        for reject, observation in zip(rejects, observations):
            paths.extend(Path(reject[key]) for key in ('referenceScreenshot', 'screenshot'))
            paths.append(Path(observation['receiptPath']))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in paths:
                target = root / path.relative_to(DEFAULT_ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            for original in (Path(rejects[0]['screenshot']), Path(observations[0]['receiptPath'])):
                target = root / original.relative_to(DEFAULT_ROOT)
                saved = target.read_bytes()
                target.write_bytes(saved + b'tampered')
                with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                    replay(root)
                target.write_bytes(saved)

    def test_optimized_execution_explicitly_rejected(self):
        script = 'from replay_evidence189_preclick import replay; replay()'
        result = subprocess.run([sys.executable, '-O', '-c', script], capture_output=True, text=True,
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('optimized execution is unsupported', result.stderr)


if __name__ == '__main__':
    unittest.main()
