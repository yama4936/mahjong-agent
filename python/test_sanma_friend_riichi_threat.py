import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw
import io
from sanma_friend_discard_experiment import friend_opponent_riichi_candidates, execute_friend_draw_candidate

ROOT=Path('/home/yama1/.codex/sanma-run-41b9fb3-20261031')
@unittest.skipUnless((ROOT/'manual-21-before.png').exists(),'friend-match captures unavailable')
class SanmaFriendRiichiThreat(unittest.TestCase):
 def test_actual_multiple_frames_sticks_and_absence(self):
  for n in (1,10,14):self.assertEqual(friend_opponent_riichi_candidates((ROOT/f'manual-{n:02}-before.png').read_bytes()),[])
  for n in (15,16):self.assertEqual(friend_opponent_riichi_candidates((ROOT/f'manual-{n:02}-before.png').read_bytes()),['left'])
  for n in (17,18,19,20,21):self.assertEqual(friend_opponent_riichi_candidates((ROOT/f'manual-{n:02}-before.png').read_bytes()),['right','left'])
 def test_red_dot_without_stick_is_not_positive(self):
  image=Image.open(ROOT/'manual-14-before.png').convert('RGB')
  ImageDraw.Draw(image).ellipse((1095,416,1105,426),fill=(220,0,0));out=io.BytesIO();image.save(out,format='PNG')
  self.assertNotIn('right',friend_opponent_riichi_candidates(out.getvalue()))
 def test_observed_sticks_stop_bridge_before_input(self):
  baseline=ROOT/'manual-21-before.png';digest=hashlib.sha256(baseline.read_bytes()).hexdigest()
  report={'digest':digest,'hand':{'status':'candidate'},'handGeometry':{'status':'candidate'},'buttonRow':{'status':'candidate'}}
  receipt={'scope':'sanma_self_turn_observation','digest':digest,'screenshot':str(baseline),
      'sourceObservation':{'digest':digest,'report':report},'drawCandidate':{'status':'candidate','digest':digest},
      'freshness':{'status':'identical_pixels_candidate'}}
  op=Mock();op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
  op.verified_friend_300_active=True;page=Mock()
  with patch('sanma_friend_discard_experiment.send_discard_click') as send:
   with self.assertRaisesRegex(ValueError,'opponent riichi candidate; safe discard unverified'):execute_friend_draw_candidate(op,page,receipt)
   send.assert_not_called();page.mouse.click.assert_not_called()
  event=next(c for c in op.log.call_args_list if c.args[0]=='sanma_friend_opponent_riichi_candidate')
  self.assertEqual(event.kwargs['opponents'],['right','left']);self.assertFalse(event.kwargs['confirmed'])
 def test_no_detection_is_not_legal_or_safe_confirmation(self):
  # Positive-only result deliberately does not classify the opponents as safe.
  self.assertEqual(friend_opponent_riichi_candidates((ROOT/'manual-01-before.png').read_bytes()),[])
