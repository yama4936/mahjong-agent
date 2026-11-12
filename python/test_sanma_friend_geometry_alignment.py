import hashlib
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from PIL import Image
from sanma_friend_discard_recovery import candidate
from sanma_friend_geometry_alignment import aligned_post_slots
from sanma_concealed_conservation import consistent

ROOT = Path('/home/yama1/server/data/dev-work/jantama/evidence191')

@unittest.skipUnless((ROOT/'operator.log').exists(), 'saved evidence191 unavailable')
class SavedRecoveryTest(unittest.TestCase):
    def test_actual_candidate_and_changed_hand_rejected(self):
        frame_dir = ROOT/'attempt/artifacts/frames'
        with tempfile.TemporaryDirectory() as temp:
            receipts=[]
            for i, prefix in enumerate(('2026-11-12T09-06-58.', '2026-11-12T09-07-11.', '2026-11-12T09-07-16.')):
                receipt=json.loads(next(frame_dir.glob(prefix+'*.sanma-self-turn.receipt.json')).read_text())
                folder=Path(temp)/str(i); folder.mkdir(); path=folder/Path(receipt['screenshot']).name
                shutil.copyfile(receipt['screenshot'], path); receipt['screenshot']=str(path)
                path.with_suffix('.receipt.json').write_text(json.dumps(receipt)); receipts.append(receipt)
            before, *posts = receipts
            journal=[j for line in (ROOT/'operator.log').read_text().splitlines() if (j:=json.loads(line)).get('event')=='sanma_friend_discard_experiment' and j.get('status') in ('attempted','selection_confirmed')][-2:]
            watch=Mock(); watch.alive.return_value=True
            def evaluate(active=lambda:True, started=None):
                return candidate(before, posts, journal, continuity=watch, active=active,
                                 started=time.monotonic() if started is None else started, deadline_ms=300000)
            self.assertIsNotNone(aligned_post_slots(before, posts[0]))
            self.assertTrue(consistent(before, posts[0], 12))
            self.assertTrue(evaluate())
            self.assertFalse(evaluate(active=lambda:False))
            self.assertFalse(evaluate(started=time.monotonic()-301))
            watch.alive.return_value=False
            self.assertFalse(evaluate()); watch.alive.return_value=True
            path=Path(posts[0]['screenshot'])
            with Image.open(path) as source:
                image=source.convert('RGB')
                # Replace observed 6s with an actual different visible 3s face,
                # keeping OCR labels untouched to test the image-level guard.
                geometry=posts[0]['sourceObservation']['report']['handGeometry']['value']['handSlots']
                a,b=geometry[9],geometry[10]
                image.paste(image.crop((a['x'],921,a['x']+a['width'],1072)).resize((b['width'],151)), (b['x'],921))
                image.save(path)
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            posts[0]['digest']=digest; posts[0]['sourceObservation']['digest']=digest
            path.with_suffix('.receipt.json').write_text(json.dumps(posts[0]))
            self.assertFalse(consistent(before,posts[0],12))
            self.assertFalse(evaluate())

    def test_alignment_requires_exact_geometry(self):
        frame_dir=ROOT/'attempt/artifacts/frames'
        def read(prefix):return json.loads(next(frame_dir.glob(prefix+'*.sanma-self-turn.receipt.json')).read_text())
        before=read('2026-11-12T09-06-58.'); after=read('2026-11-12T09-07-11.')
        self.assertIsNotNone(aligned_post_slots(before,after))
        after['sourceObservation']['report']['handGeometry']['value']['handSlots'][0]['y']+=1
        self.assertIsNone(aligned_post_slots(before,after))
        for mutate in ('overlap','reorder','shift','width'):
            after=read('2026-11-12T09-07-11.')
            slots=after['sourceObservation']['report']['handGeometry']['value']['handSlots']
            if mutate=='overlap': slots[1]=dict(slots[0])
            elif mutate=='reorder': slots[0],slots[1]=slots[1],slots[0]
            elif mutate=='shift': slots[5]['x']+=2
            else: slots[5]['width']=94
            self.assertIsNone(aligned_post_slots(before,after),mutate)

    def test_real_recovery_candidate_reaches_next_action_in_operator_loop(self):
        from unittest.mock import patch
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        frame_dir=ROOT/'attempt/artifacts/frames'
        with tempfile.TemporaryDirectory() as temp:
            receipts=[]
            for i,prefix in enumerate(('2026-11-12T09-06-58.', '2026-11-12T09-07-11.', '2026-11-12T09-07-16.')):
                r=json.loads(next(frame_dir.glob(prefix+'*.sanma-self-turn.receipt.json')).read_text())
                folder=Path(temp)/str(i);folder.mkdir();path=folder/Path(r['screenshot']).name
                shutil.copyfile(r['screenshot'],path);r['screenshot']=str(path)
                r['candidates']={'candidates':[]};r['freshness']={'status':'identical_pixels_candidate'}
                path.with_suffix('.receipt.json').write_text(json.dumps(r));receipts.append(r)
            journal=[j for line in (ROOT/'operator.log').read_text().splitlines() if (j:=json.loads(line)).get('event')=='sanma_friend_discard_experiment' and j.get('status') in ('attempted','selection_confirmed')][-2:]
            watch=Mock();watch.alive.return_value=True
            case=ExperimentalSanmaFriendLoopTest('runTest');case.setUp();self.addCleanup(case.doCleanups)
            case.op.args.max_iterations=3
            case.op.inspect_sanma_self_turn.side_effect=receipts
            case.op.observe_sanma_friend_transition.return_value={'status':'visual_change_unconfirmed','confirmed':False}
            def replay(before,posts,ignored,**kwargs):return candidate(before,posts,journal,**kwargs)
            with patch('sanma_friend_discard_recovery.MatchContinuity',return_value=watch), \
                 patch('sanma_friend_discard_recovery.candidate',side_effect=replay), \
                 patch('sanma_friend_discard_experiment.execute_friend_draw_candidate',return_value=journal[1]) as discard:
                case.run_room()
            self.assertEqual(discard.call_count,2)
            self.assertTrue(any(c.args[0]=='sanma_friend_discard_recovery_candidate' for c in case.op.log.call_args_list))
            # A ron candidate on the later observation must stop before any
            # second input, even after the evidence chain has accepted it.
            receipts[2]['candidates']={'candidates':[{'action':'ron'}]}
            Path(receipts[2]['screenshot']).with_suffix('.receipt.json').write_text(json.dumps(receipts[2]))
            other=ExperimentalSanmaFriendLoopTest('runTest');other.setUp();self.addCleanup(other.doCleanups)
            other.op.args.max_iterations=3
            other.op.inspect_sanma_self_turn.side_effect=receipts
            other.op.observe_sanma_friend_transition.return_value={'status':'visual_change_unconfirmed','confirmed':False}
            with patch('sanma_friend_discard_recovery.MatchContinuity',return_value=watch), \
                 patch('sanma_friend_discard_recovery.candidate',side_effect=replay), \
                 patch('sanma_friend_discard_experiment.execute_friend_draw_candidate',return_value=journal[1]) as discard:
                other.run_room()
            self.assertEqual(discard.call_count,1)
            self.assertTrue(any(c.kwargs.get('reason')=='discard_recovery_action_requires_review' for c in other.op.log.call_args_list))
