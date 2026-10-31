"""Visual transitions are recorded, not asserted as successful actions."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from auto_operator import PythonAutoOperator, clip_for_hand, load_json

ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / 'artifacts/sanma-manual-e48c562-20261031/actions'
OTHER = Path('/home/yama1/sanma-independent-20261031')


class SanmaFriendTransitionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.op = object.__new__(PythonAutoOperator)
        self.op.frames = Path(self.temp.name)
        self.op.verified_friend_300_active = True
        self.op.screen_references = {}
        layout = load_json(ROOT/'config/layout-runtime.json')
        self.op.hand_clip = clip_for_hand(layout)
        self.op.river_clip = layout['publicTileRegions']['ownDiscards']
        self.page = Mock()

    def receipt(self, data):
        file = self.op.frames/'before.png'
        file.write_bytes(data)
        return {'digest':hashlib.sha256(data).hexdigest(),'screenshot':str(file)}

    @unittest.skipUnless((OTHER/'20-turn.png').exists() and (OTHER/'21-kita.png').exists(), 'independent images unavailable')
    def test_real_kita_change_remains_unconfirmed(self):
        before=(OTHER/'20-turn.png').read_bytes()
        after=(OTHER/'21-kita.png').read_bytes()
        self.page.screenshot.return_value=after
        with patch('auto_operator.classify_screen',return_value=('match',1.0)):
            result=self.op.observe_sanma_friend_transition(self.page,self.receipt(before),'kita')
        self.assertEqual(result['status'],'visual_change_unconfirmed')
        self.assertFalse(result['confirmed'])
        self.assertEqual(Path(result['screenshot']).read_bytes(),after)
        self.page.mouse.click.assert_not_called()

    @unittest.skipUnless((OTHER/'27-turn.png').exists() and (OTHER/'28-pon.png').exists(), 'independent prompt images unavailable')
    def test_disappearing_pon_prompt_is_only_unconfirmed_visual_change(self):
        before=(OTHER/'27-turn.png').read_bytes()
        after=(OTHER/'28-pon.png').read_bytes()
        self.page.screenshot.return_value=after
        with patch('auto_operator.classify_screen', return_value=('match',1.0)):
            result=self.op.observe_sanma_friend_transition(self.page,self.receipt(before),'pass_pon')
        self.assertEqual(result['status'],'visual_change_unconfirmed')
        self.assertFalse(result['confirmed'])
        # This real image pair is a pon, not a pass: the change proves no action outcome.
        self.page.screenshot.return_value=before
        with patch('auto_operator.classify_screen', return_value=('match',1.0)):
            unchanged=self.op.observe_sanma_friend_transition(self.page,self.receipt(before),'pass_pon')
        self.assertEqual(unchanged['status'],'unresolved')

    @unittest.skipUnless((MANUAL/'2026-10-30T16-07-32-642Z-before.png').exists(), 'discard images unavailable')
    def test_real_discard_and_unchanged_or_revoked_screen(self):
        before=(MANUAL/'2026-10-30T16-07-32-642Z-before.png').read_bytes()
        after=(MANUAL/'2026-10-30T16-07-40-491Z-after.png').read_bytes()
        self.page.screenshot.return_value=after
        receipt=self.receipt(before)
        with patch('auto_operator.classify_screen',return_value=('match',1.0)):
            result=self.op.observe_sanma_friend_transition(self.page,receipt,'discard')
            self.assertEqual(result['status'],'visual_change_unconfirmed')
            self.assertFalse(result['confirmed'])
            self.page.screenshot.return_value=before
            unchanged=self.op.observe_sanma_friend_transition(self.page,receipt,'discard')
        self.assertEqual(unchanged['status'],'unresolved')
        self.op.verified_friend_300_active=False
        revoked=self.op.observe_sanma_friend_transition(self.page,receipt,'discard')
        self.assertEqual(revoked['reason'],'friend session revoked')
        self.page.mouse.click.assert_not_called()


if __name__ == '__main__': unittest.main()
