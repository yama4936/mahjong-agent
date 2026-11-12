"""Evidence boundary tests; the CLI separately replays all real saved images."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from replay_evidence188 import checked_bytes


class EvidenceBoundaryTests(unittest.TestCase):
    def test_missing_evidence_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                checked_bytes(Path(directory), {'path': 'missing.png', 'sha256': '0' * 64})

    def test_altered_evidence_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'frame.png').write_bytes(b'altered')
            with self.assertRaisesRegex(AssertionError, 'SHA256 mismatch'):
                checked_bytes(root, {'path': 'frame.png',
                                     'sha256': hashlib.sha256(b'original').hexdigest()})


if __name__ == '__main__':
    unittest.main()
