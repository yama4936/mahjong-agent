"""Offline evidence only; white draw and board candidates are simulated."""
import copy,hashlib,json,tempfile,unittest
from unittest.mock import Mock
from pathlib import Path
from PIL import Image
from sanma_discard_evidence_chain import evaluate
from sanma_concealed_conservation import consistent

LOG=Path('/home/yama1/server/data/dev-work/jantama/evidence149/operator3.log')
@unittest.skipUnless(LOG.exists(),'retained evidence unavailable')
class UnknownDrawRecoveryTests(unittest.TestCase):
 def setUp(self):
  events=[json.loads(line) for line in LOG.read_text().splitlines()]
  self.receipts=[json.loads(Path(e['receiptPath']).read_text()) for e in events if e.get('event')=='sanma_self_turn_observed'][:3]
  self.journal=[e for e in events if e.get('event')=='sanma_friend_discard_experiment' and e.get('status') in ('attempted','selection_confirmed')]
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  # Real west tsumogiri trajectory; replace its selected face with the real
  # blank draw from evidence163 to simulate an unclassified physical draw.
  original=Path(self.receipts[0]['screenshot']); image=Image.open(original).convert('RGB')
  blank=next(Path('/home/yama1/server/data/dev-work/jantama/evidence163/artifacts/frames').glob('*23-11-42*sanma-self-turn.png'))
  with Image.open(blank) as source:image.paste(source.convert('RGB').crop((1486,921,1578,1072)),(1486,921))
  synthetic=Path(self.temp.name)/original.name;image.save(synthetic);digest=hashlib.sha256(synthetic.read_bytes()).hexdigest()
  self.receipts[0]['screenshot']=str(synthetic);self.receipts[0]['digest']=digest;self.receipts[0]['sourceObservation']['digest']=digest
  self.receipts[0]['sourceObservation']['report']['digest']=digest;self.receipts[0]['drawCandidate'].update(tile='P',digest=digest)
  hand=self.receipts[0]['sourceObservation']['report']['hand']['value'];hand['tiles'][13]='P';hand['matches'][13].update(tile='P',confidence=0,runnerUpConfidence=0)
  for item in self.journal:item.update(tile='P',frameSha256=digest,blankDrawIdentityUnknown=True)
  # Recorded recognizer did not support this camera layout; supply manual
  # visible candidates solely to exercise the rest of the offline chain.
  for receipt,remaining in zip(self.receipts,(54,51,51)):
   receipt['sourceObservation']['board']['candidate']={'seat':'east','round':'east_1','honba':0,'scores':{'east':35000,'south':35000,'west':35000},'remainingTiles':remaining}
 def evaluate(self,receipts=None,journal=None):
  receipts=receipts or self.receipts;journal=journal or self.journal;paths=[]
  for i,r in enumerate(receipts):
   path=Path(self.temp.name)/f'{i}.json';path.write_text(json.dumps(r));paths.append(str(path))
  return evaluate(paths[0],paths[1:],journal,unknown_draw=True)
 def test_real_physical_append_and_conservation_with_simulated_unknown_label(self):
  self.assertTrue(all(consistent(self.receipts[0],p,13) for p in self.receipts[1:]))
  r=self.evaluate();self.assertEqual(r['state'],'later_turn_evidence_candidate',r['failures'])
  self.assertIsNone(r['evidence']['selectedTile']);self.assertTrue(r['evidence']['selectedTileIdentityUnknown'])
 def test_wrong_identity_journal_or_position_rejected(self):
  for kind in ('missing_flag','other_tile','other_index','confident_label'):
   r=copy.deepcopy(self.receipts);j=copy.deepcopy(self.journal)
   if kind=='missing_flag':j[1].pop('blankDrawIdentityUnknown')
   elif kind=='other_tile':j[0]['tile']=j[1]['tile']='W'
   elif kind=='other_index':j[0]['clickIndex']=j[1]['clickIndex']=0
   else:r[0]['sourceObservation']['report']['hand']['value']['matches'][13]['confidence']=.99
   with self.subTest(kind=kind):self.assertNotEqual(self.evaluate(r,j)['state'],'later_turn_evidence_candidate')
 def test_hand_and_round_mismatch_rejected(self):
  for kind in ('hand','round','remaining'):
   r=copy.deepcopy(self.receipts)
   if kind=='hand':r[1]['sourceObservation']['report']['hand']['value']['tiles'][0]='C'
   elif kind=='round':r[1]['sourceObservation']['board']['candidate']['round']='east_2'
   else:r[1]['sourceObservation']['board']['candidate']['remainingTiles']=54
   with self.subTest(kind=kind):self.assertNotEqual(self.evaluate(r)['state'],'later_turn_evidence_candidate')
 def test_wrong_physical_river_rejected(self):
  r=copy.deepcopy(self.receipts)
  # Retain the later filename/timestamp and bind the altered pixels correctly;
  # this reaches the physical river check rather than failing on a bad hash.
  path=Path(self.temp.name)/Path(r[1]['screenshot']).name
  path.write_bytes(Path(r[0]['screenshot']).read_bytes());digest=hashlib.sha256(path.read_bytes()).hexdigest()
  r[1]['screenshot']=str(path);r[1]['digest']=digest;r[1]['sourceObservation']['digest']=digest
  result=self.evaluate(r)
  self.assertIn('physical append absent or uncertain',result['failures'])
 def test_original_deadline_expiry_blocks_unknown_recovery(self):
  from sanma_friend_discard_recovery import candidate
  watch=Mock();watch.alive.return_value=True
  self.assertFalse(candidate(self.receipts[0],self.receipts[1:],self.journal,
                             continuity=watch,active=lambda:True,started=100,deadline_ms=300000,now=lambda:400))
