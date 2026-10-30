import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from auto_operator import PythonAutoOperator
from sanma_kita_image_experiment import detect_own_north_candidates

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = ROOT / 'artifacts/sanma-manual-e48c562-20261031/actions'
BEFORE = ACTIONS / '2026-10-30T16-05-55-331Z-before.png'
AFTER = ACTIONS / '2026-10-30T16-05-55-331Z-after.png'
TEMPLATE = ROOT / 'test/fixtures/sanma-public-experiment/own-north-face.png'


def observation(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'scope': 'offline_untrusted_sanma_auto_observation', 'operationAuthorized': False, 'digest': digest,
            'north': {'positions': {'own': detect_own_north_candidates(path, TEMPLATE)}},
            'report': {'digest': digest, 'hand': {'status': 'unresolved'}, 'buttonRow': {'status': 'unresolved'}}}


@unittest.skipUnless(BEFORE.exists() and AFTER.exists(), 'saved sanma match images unavailable')
class SanmaKitaObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.operator = object.__new__(PythonAutoOperator)
        self.operator.frames = Path(self.temp.name)
        self.operator.observe_sanma_resident = Mock(side_effect=observation)
        self.page = Mock()
        self.page.screenshot.return_value = AFTER.read_bytes()

    def test_saved_before_after_frames_are_diagnostic_not_confirmation(self):
        before = observation(BEFORE)
        output = self.operator.inspect_sanma_kita_confirmation(self.page, before)
        self.assertEqual(output['status'], 'unresolved')
        self.assertEqual(output['reason'], 'extraction_and_replacement_not_verified')
        self.assertFalse(output['operationAuthorized'])
        self.assertEqual(output['beforeDigest'], before['digest'])
        self.assertEqual(output['afterDigest'], hashlib.sha256(AFTER.read_bytes()).hexdigest())
        self.assertEqual(Path(output['screenshot']).read_bytes(), AFTER.read_bytes())
        self.assertFalse(output['after']['ownNorth']['complete'])
        self.page.screenshot.assert_called_once_with(animations='disabled')
        self.page.mouse.click.assert_not_called()

    def test_duplicate_and_inconsistent_input_never_authorize(self):
        before = observation(BEFORE)
        self.page.screenshot.return_value = BEFORE.read_bytes()
        duplicate = self.operator.inspect_sanma_kita_confirmation(self.page, before)
        self.assertEqual(duplicate['reason'], 'same_frame')
        self.assertFalse(duplicate['operationAuthorized'])
        self.operator.observe_sanma_resident.assert_not_called()
        before['north']['positions']['own']['frame_sha256'] = 'wrong'
        with self.assertRaisesRegex(RuntimeError, 'baseline north evidence'):
            self.operator.inspect_sanma_kita_confirmation(self.page, before)

    def test_sanma_execution_cannot_bypass_startup_guard(self):
        with self.assertRaisesRegex(RuntimeError, 'sanma execution is not implemented'):
            self.operator.execute(self.page, {'state': {'rules': 'sanma'}})
        self.page.mouse.click.assert_not_called()

    def test_post_observation_digest_mismatch_rejects(self):
        before = observation(BEFORE)
        self.operator.observe_sanma_resident = Mock(return_value={**before, 'digest': '0' * 64})
        with self.assertRaisesRegex(RuntimeError, 'does not match'):
            self.operator.inspect_sanma_kita_confirmation(self.page, before)
        self.page.mouse.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
