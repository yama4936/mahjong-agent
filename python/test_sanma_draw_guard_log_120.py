"""Preserve observed weak draw confidence as a non-authorizing diagnostic."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sanma_friend_discard_experiment import execute_friend_draw_candidate


class GuardLog120(unittest.TestCase):
    def test_real_weak_draw_score_logs_bound_without_click(self):
        data=json.loads((Path(__file__).parent/'fixtures/sanma-draw-120-report.json').read_text())
        frame=b'fixed mock frame'; digest=hashlib.sha256(frame).hexdigest()
        report=data['report'];report['digest']=digest
        draw=data['draw'];draw['digest']=digest
        op=Mock();op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',
            action_deadline_ms=300000,ranked_loop=False)
        op.verified_friend_300_active=True
        with tempfile.TemporaryDirectory() as directory:
            screenshot=Path(directory)/'frame.png';screenshot.write_bytes(frame)
            receipt={'scope':'sanma_self_turn_observation','digest':digest,'screenshot':str(screenshot),
                     'sourceObservation':{'digest':digest,'report':report},
                     'drawCandidate':draw,'freshness':{'status':'identical_pixels_candidate'}}
            page=Mock()
            with patch('sanma_friend_discard_experiment.friend_opponent_riichi_candidates',return_value=[]), \
                 patch('sanma_friend_discard_experiment.experimental_white_hand_candidate',return_value=None), \
                 patch('sanma_friend_discard_experiment.friend_visible_row_with_north_overlap',return_value=False), \
                 patch('sanma_friend_discard_experiment.friend_visible_empty_row_candidate',return_value=False), \
                 patch('sanma_friend_discard_experiment.execute_friend_discard') as execute:
                with self.assertRaisesRegex(ValueError,'unsafe hand'):
                    execute_friend_draw_candidate(op,page,receipt)
                draw['index'] = 12
                with self.assertRaisesRegex(ValueError,'unsafe hand'):
                    execute_friend_draw_candidate(op,page,receipt)
                execute.assert_not_called();page.mouse.click.assert_not_called()
        events=[c for c in op.log.call_args_list if c.args[0]=='sanma_friend_discard_guard_rejected']
        self.assertEqual(len(events),2)
        event, mismatch = events
        self.assertEqual(mismatch.kwargs['drawIndex'],12)
        self.assertFalse(mismatch.kwargs['drawIndexMatchesLastSlot'])
        self.assertAlmostEqual(mismatch.kwargs['lastHandSlotConfidence'],.9703363097773985)
        self.assertFalse(mismatch.kwargs['operationAuthorized'])
        self.assertAlmostEqual(event.kwargs['lastHandSlotConfidence'],.9703363097773985)
        self.assertEqual(event.kwargs['drawOnlyMinimumConfidence'],.98)
        self.assertEqual(event.kwargs['drawIndex'],13)
        self.assertTrue(event.kwargs['drawIndexMatchesLastSlot'])
        self.assertEqual(event.kwargs['drawTile'],'5s')
        self.assertFalse(event.kwargs['drawOnlyCandidate'])
        self.assertFalse(event.kwargs['operationAuthorized'])
        self.assertFalse(event.kwargs['confirmed'])


if __name__ == '__main__': unittest.main()
