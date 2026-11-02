"""Redacted recorded-frame regression; never grants operation or proves freshness."""
import copy
import hashlib
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from PIL import Image
from sanma_friend_kita_rearm import rearm_friend_kita_candidate
from sanma_friend_freshness import friend_action_target_key

ROOT=Path(__file__).parent/'fixtures'/'sanma-kita-30f-redacted'

class RecordedNorthRegression(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.manifest=json.loads((ROOT/'manifest.json').read_text())
  for name,meta in cls.manifest.items():
   data=(ROOT/(name+'.png')).read_bytes()
   assert hashlib.sha256(data).hexdigest()==meta['redactedSha256']
   with Image.open(ROOT/(name+'.png')) as image: assert image.size==(1920,1080)
 def setUp(self):
  self.op=Mock();self.op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
  self.op.verified_friend_300_active=True;self.op._sanma_friend_kita_rearmed=False
  self.op._sanma_friend_attempted_targets={friend_action_target_key((ROOT/'before.png').read_bytes(),'kita')}
 def receipt(self,name):
  meta=self.manifest[name];digest=meta['redactedSha256']
  # The image is redacted and digest rebound; original live freshness is preserved.
  return {'scope':'sanma_self_turn_observation','operationAuthorized':False,'screenshot':str(ROOT/(name+'.png')),'digest':digest,
          'freshness':copy.deepcopy(meta['freshness']),
          'sourceObservation':{'operationAuthorized':False,'digest':digest,'report':{'digest':digest,'hand':copy.deepcopy(meta['hand'])}}}
 def test_recorded_lighting_candidates_stop_without_rearm(self):
  first,second=self.receipt('before'),self.receipt('after')
  self.assertEqual(first['freshness']['status'],'stable_kita_glyph_candidate')
  self.assertEqual(second['freshness']['status'],'stable_kita_glyph_candidate')
  self.assertFalse(rearm_friend_kita_candidate(self.op,first,second))
  self.op.log.assert_not_called()
 def test_same_recorded_frame_cannot_rearm(self):
  first=self.receipt('before')
  self.assertFalse(rearm_friend_kita_candidate(self.op,first,copy.deepcopy(first)))
  self.op.log.assert_not_called()
 def test_later_kita_and_kan_button_candidates_are_distinct(self):
  def actions(name):return [s.get('action') for s in self.manifest[name]['buttonRow']['value']['slots']]
  self.assertEqual(actions('later'),[None,'kita','skip'])
  self.assertEqual(actions('kan'),[None,'kan','skip'])
  self.assertEqual(self.manifest['later']['hand']['status'],'unresolved')
