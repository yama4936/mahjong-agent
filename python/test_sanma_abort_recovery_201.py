"""Replay observed 201 prompt recovery; fresh recognition is simulated."""
import copy
import hashlib
import io
import tempfile
from PIL import Image
import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sanma_friend_abort_prompt import recovered_empty_pair, execute
from sanma_friend_discard_experiment import friend_visible_empty_row_candidate

ROOT=Path('/home/yama1/server/data/dev-work/jantama/evidence201')

@unittest.skipUnless((ROOT/'operator.log').exists(),'evidence201 unavailable')
class Recovery201(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  rows=[json.loads(s) for s in (ROOT/'operator.log').read_text().splitlines() if s.startswith('{')]
  click=next(r for r in rows if r.get('event')=='sanma_friend_candidate_click')
  before=next(r for r in rows if r.get('event')=='sanma_self_turn_observed' and r['digest']==click['digest'])
  post=next(r for r in rows if r.get('event')=='sanma_self_turn_observed' and r['timestamp'].startswith('2026-11-12T21:19:38'))
  cls.original=json.loads(Path(before['receiptPath']).read_text());cls.baseline=Path(cls.original['screenshot']).read_bytes()
  cls.post=json.loads(Path(post['receiptPath']).read_text());cls.frame=Path(cls.post['screenshot']).read_bytes()
 def setUp(self):
  self.original=copy.deepcopy(type(self).original);self.observed=copy.deepcopy(type(self).post)
  self.fresh_source=copy.deepcopy(self.observed['sourceObservation'])
  digest=self.observed['freshness']['digest'];self.fresh_source['digest']=digest;self.fresh_source['report']['digest']=digest
  self.op=SimpleNamespace(verified_friend_300_active=True,observe_sanma_resident=Mock(return_value=self.fresh_source))
  self.watch=Mock();self.watch.alive.return_value=True;self.started=time.monotonic()
 def check(self):
  return recovered_empty_pair(self.op,self.baseline,self.original,self.observed,self.frame,
                              self.observed['captureStartedMonotonic'],self.watch,self.started)
 def test_real_pair_and_independent_recognition_result(self):
  path=Path('/home/yama1/server/data/dev-work/jantama/skip201-fresh-recognition.jsonl')
  if not path.exists():self.skipTest('independent OCR evidence unavailable')
  source=json.loads(path.read_text().splitlines()[-1])['result']
  self.op.observe_sanma_resident.return_value=source
  self.assertTrue(self.check())

 def test_real_pair_and_simulated_independent_recognition(self):
  self.assertTrue(self.check());self.op.observe_sanma_resident.assert_called_once_with(Path(self.observed['freshness']['screenshot']))
 def test_unrelated_or_uncertain_fresh_recognition_is_rejected(self):
  for mode in ('ron','changed_hand','changed_round','changed_seat','changed_remaining','changed_geometry','wrong_digest','no_candidate','slot_reordered'):
   with self.subTest(mode=mode):
    self.setUp()
    if mode=='ron':self.fresh_source['candidates']['candidates']=[{'action':'ron'}]
    elif mode=='changed_hand':self.fresh_source['report']['hand']['value']['tiles'][0]='9m'
    elif mode=='changed_round':self.fresh_source['board']['candidate']['round']='east_2'
    elif mode=='changed_seat':self.fresh_source['board']['candidate']['seat']='east'
    elif mode=='changed_remaining':self.fresh_source['board']['candidate']['remainingTiles']-=1
    elif mode=='changed_geometry':self.fresh_source['report']['handGeometry']['value']['drawSlot']['x']+=1
    elif mode=='wrong_digest':self.fresh_source['report']['digest']='0'*64
    elif mode=='no_candidate':self.fresh_source['report']['hand']['status']='unresolved'
    else:self.fresh_source['report']['buttonRow']['value']['slots'][1]['slot']=2
    self.assertFalse(self.check())
 def test_old_prompt_or_wrong_original_capture_does_not_authorize(self):
  self.observed['freshness']['screenshot']=self.original['screenshot']
  self.assertFalse(self.check());self.op.observe_sanma_resident.assert_not_called()
 def test_existing_friend_executor_clicks_once_and_recovers_under_same_watch(self):
  self.op.args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False,experimental_sanma_friend=True)
  self.op.sanma_friend_action_observed_at=self.started;self.op.screen_references={};self.op.log=Mock()
  page=Mock();page.screenshot.side_effect=[self.baseline,self.frame]
  def inspect(page, *, classified_frame, classified_started):
   return dict(self.observed,captureStartedMonotonic=classified_started)
  self.op.inspect_sanma_self_turn=Mock(side_effect=inspect)
  with patch('sanma_friend_abort_prompt.MatchContinuity',return_value=self.watch), \
       patch('sanma_friend_abort_prompt.classify_screen',return_value=('match',1)), \
       patch('sanma_friend_abort_prompt.require_friend_observation_budget'):
   result=execute(self.op,page,self.original)
  self.assertIs(result,self.watch);page.mouse.click.assert_called_once_with(1300,830)
  self.op.observe_sanma_resident.assert_called_once();self.watch.close.assert_not_called()

 def test_recovery_log_failure_or_server_failure_never_retries_skip(self):
  for mode in ('log','server'):
   with self.subTest(mode=mode):
    self.setUp();self.op.args=SimpleNamespace(rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False,experimental_sanma_friend=True)
    self.op.sanma_friend_action_observed_at=self.started;self.op.screen_references={};self.op.log=Mock()
    if mode=='log':self.op.log.side_effect=lambda name,**kw: (_ for _ in ()).throw(OSError('log failure')) if name=='sanma_friend_nine_terminals_pass_recovery' else None
    else:self.op.observe_sanma_resident.side_effect=RuntimeError('server stopped')
    page=Mock();page.screenshot.side_effect=[self.baseline,self.frame]
    self.op.inspect_sanma_self_turn=Mock(side_effect=lambda page,*,classified_frame,classified_started:dict(self.observed,captureStartedMonotonic=classified_started))
    with patch('sanma_friend_abort_prompt.MatchContinuity',return_value=self.watch), \
         patch('sanma_friend_abort_prompt.classify_screen',return_value=('match',1)), \
         patch('sanma_friend_abort_prompt.require_friend_observation_budget'):
     with self.assertRaises((OSError,RuntimeError)):execute(self.op,page,self.original)
    page.mouse.click.assert_called_once_with(1300,830);self.watch.close.assert_called_once()

 def test_independent_frame_modified_during_recognition_rejected(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'fresh.png';path.write_bytes(Path(self.observed['freshness']['screenshot']).read_bytes())
   self.observed['freshness']['screenshot']=str(path)
   def replace(path_arg):
    path.write_bytes(b'changed-after-recognition');return self.fresh_source
   self.op.observe_sanma_resident.side_effect=replace
   self.assertFalse(self.check())

 def test_first_observation_modified_during_recognition_rejected(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'observation.png';path.write_bytes(self.frame)
   self.observed['screenshot']=str(path)
   def replace(path_arg):
    path.write_bytes(b'changed-after-recognition');return self.fresh_source
   self.op.observe_sanma_resident.side_effect=replace
   self.assertFalse(self.check())

 def test_ron_tsumo_overlays_never_authorize(self):
  for name in ('ron','tsumo'):
   with self.subTest(action=name),tempfile.TemporaryDirectory() as directory:
    self.setUp()
    image=Image.open(self.observed['freshness']['screenshot']).convert('RGB')
    icon_path=Path('test/fixtures/ron-button-rows/ron1.png') if name=='ron' else Path('test/fixtures/sanma-buttons/tsumo.png')
    icon=Image.open(icon_path).convert('RGB')
    image.paste(icon,(600,785) if name=='ron' else (890,785));out=io.BytesIO();image.save(out,format='PNG')
    path=Path(directory)/'overlay.png';path.write_bytes(out.getvalue())
    self.observed['freshness'].update(screenshot=str(path),digest=hashlib.sha256(out.getvalue()).hexdigest())
    self.assertFalse(self.check());self.op.observe_sanma_resident.assert_not_called()

 def test_stale_capture_and_recognition_server_failure_cannot_authorize(self):
  self.assertFalse(recovered_empty_pair(self.op,self.baseline,self.original,self.observed,self.frame,
      self.observed['captureStartedMonotonic']-1,self.watch,self.started))
  self.op.observe_sanma_resident.side_effect=RuntimeError('recognition server stopped')
  with self.assertRaisesRegex(RuntimeError,'recognition server stopped'):self.check()

 def test_expired_deadline_or_disconnection_never_recover(self):
  self.started=time.monotonic()-301;self.assertFalse(self.check())
  self.started=time.monotonic();self.watch.alive.return_value=False;self.assertFalse(self.check())
  self.op.observe_sanma_resident.assert_not_called()
 def test_connection_lost_after_ocr_never_recover(self):
  self.watch.alive.side_effect=[True,False];self.assertFalse(self.check());self.op.observe_sanma_resident.assert_called_once()
 def test_north_overlap_excluded(self):
  import io
  from PIL import Image
  img=Image.new('RGB',(1920,1080),(25,35,55));ref=Image.open(Path(__file__).parent/'fixtures/sanma-friend-two-north-slot-dd.png');img.paste(ref,(1180,785));out=io.BytesIO();img.save(out,format='PNG')
  slots=self.observed['sourceObservation']['report']['buttonRow']['value']['slots']
  self.assertFalse(friend_visible_empty_row_candidate(out.getvalue(),slots,allow_north_overlap=False))
