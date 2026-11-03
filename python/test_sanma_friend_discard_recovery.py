import hashlib
import io
import json
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image

from sanma_friend_discard_recovery import candidate
from sanma_friend_freshness import check_friend_recovery_guard

ROOT = Path('/home/yama1/server/data/dev-work/jantama/evidence139')

class RecoveryGuardTest(unittest.TestCase):
    @unittest.skipUnless(Path('/home/yama1/server/data/dev-work/jantama/evidence152/artifacts/frames').exists(),
                         'saved ordinary 5s match unavailable')
    def test_saved_hand_with_ordinary_5s_reaches_recovery(self):
        root=Path('/home/yama1/server/data/dev-work/jantama/evidence152/artifacts/frames')
        prefixes=('2026-11-03T17-49-36','2026-11-03T17-49-56','2026-11-03T17-50-02')
        with tempfile.TemporaryDirectory() as directory:
            receipts=[]
            for i,prefix in enumerate(prefixes):
                receipt=json.loads(next(root.glob(prefix+'*.sanma-self-turn.receipt.json')).read_text())
                source=Path(receipt['screenshot']); folder=Path(directory)/str(i);folder.mkdir()
                target=folder/source.name;shutil.copyfile(source,target);receipt['screenshot']=str(target)
                target.with_suffix('.receipt.json').write_text(json.dumps(receipt));receipts.append(receipt)
            event={'tile':'C','clickIndex':12,'clickPoint':{'x':1407,'y':996.5},'frameSha256':receipts[0]['digest']}
            journal=[dict(event,status='attempted',timestamp='2026-11-03T17:49:41.039791+00:00'),
                     dict(event,status='selection_confirmed',result='discard_not_verified',
                          timestamp='2026-11-03T17:49:42.536845+00:00')]
            watch=Mock();watch.alive.return_value=True
            self.assertTrue(candidate(receipts[0],receipts[1:],journal,continuity=watch,
                                      active=lambda:True,started=time.monotonic(),deadline_ms=300000))
            # Substituting an actual different pin tile under a false 7p
            # label must still fail the supporting visual conservation.
            from sanma_concealed_conservation import consistent
            altered=dict(receipts[1]); path=Path(directory)/'wrong.png'
            g=altered['sourceObservation']['report']['handGeometry']['value']; slots=[*g['handSlots'],g['drawSlot']]
            tiles=altered['sourceObservation']['report']['hand']['value']['tiles']
            a,b=slots[tiles.index('6p')],slots[tiles.index('7p')]
            with Image.open(altered['screenshot']) as source:
                image=source.convert('RGB')
                box=lambda s:(s['x'],s['y'],s['x']+s['width'],s['y']+s['height'])
                image.paste(image.crop(box(a)).resize((b['width'],b['height'])),(b['x'],b['y']))
                image.save(path)
            altered['screenshot']=str(path)
            self.assertFalse(consistent(receipts[0],altered,12))

    def test_revocation_reconnect_and_original_deadline_block_click(self):
        op=Mock()
        op.verified_friend_300_active=True
        watch=Mock()
        watch.alive.return_value=True
        op._sanma_friend_resume_guard=(watch,time.monotonic(),300000)
        check_friend_recovery_guard(op)
        for reason in ('revoked','reconnected','expired'):
            op.verified_friend_300_active=reason != 'revoked'
            watch.alive.return_value=reason != 'reconnected'
            op._sanma_friend_resume_guard=(watch,time.monotonic()-(301 if reason=='expired' else 0),300000)
            with self.subTest(reason=reason), self.assertRaises(RuntimeError):
                check_friend_recovery_guard(op)

    @unittest.skipUnless(Path('/home/yama1/server/data/dev-work/jantama/evidence151/artifacts/frames').exists(),
                         'saved right north frames unavailable')
    def test_two_new_right_north_candidates_require_frame_bound_before_and_after(self):
        from sanma_discard_evidence_chain import _right_north_additions
        root=Path('/home/yama1/server/data/dev-work/jantama/evidence151/artifacts/frames')
        receipts=[json.loads(next(root.glob(prefix+'*.sanma-self-turn.receipt.json')).read_text())
                  for prefix in ('2026-11-03T17-19-32','2026-11-03T17-19-50','2026-11-03T17-19-55')]
        self.assertEqual(_right_north_additions(receipts[0],receipts[1:]),2)
        self.assertEqual(_right_north_additions(receipts[1],receipts[1:]),0)
        self.assertEqual(_right_north_additions(receipts[0],[receipts[1],receipts[0]]),0)
        corrupt=dict(receipts[2],digest='0'*64)
        self.assertEqual(_right_north_additions(receipts[0],[receipts[1],corrupt]),0)

    @unittest.skipUnless(Path('/home/yama1/server/data/dev-work/jantama/evidence151/artifacts/frames').exists(),
                         'saved left/right match unavailable')
    def test_real_left_right_north_extractions_reach_recovery_candidate(self):
        from sanma_board_image import recognize_sanma_board_candidate
        root=Path('/home/yama1/server/data/dev-work/jantama/evidence151/artifacts/frames')
        prefixes=('2026-11-03T17-19-32','2026-11-03T17-19-50','2026-11-03T17-19-55')
        with tempfile.TemporaryDirectory() as directory:
            receipts=[]
            for i,prefix in enumerate(prefixes):
                original=json.loads(next(root.glob(prefix+'*.sanma-self-turn.receipt.json')).read_text())
                source=Path(original['screenshot']); folder=Path(directory)/str(i); folder.mkdir()
                target=folder/source.name; shutil.copyfile(source,target); original['screenshot']=str(target)
                original['sourceObservation']['board']=recognize_sanma_board_candidate(
                    target,expected_total_points=None,payment_phase=None)
                target.with_suffix('.receipt.json').write_text(json.dumps(original))
                receipts.append(original)
            event={'tile':'1m','clickIndex':0,'clickPoint':{'x':269,'y':996.5},
                   'frameSha256':receipts[0]['digest']}
            journal=[dict(event,status='attempted',timestamp='2026-11-03T17:19:37.214237+00:00'),
                     dict(event,status='selection_confirmed',result='discard_not_verified',
                          timestamp='2026-11-03T17:19:38.617414+00:00')]
            watch=Mock();watch.alive.return_value=True
            self.assertTrue(candidate(receipts[0],receipts[1:],journal,continuity=watch,
                                      active=lambda:True,started=time.monotonic(),deadline_ms=300000))

@unittest.skipUnless((ROOT/'receipt0.json').exists(), 'local retained real-match evidence unavailable')
class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.receipts=[]
        for index in range(3):
            r=json.loads((ROOT/f'receipt{index}.json').read_text())
            image=Path(r['screenshot'])
            sub=Path(self.temp.name)/str(index)
            sub.mkdir()
            target=sub/image.name
            shutil.copyfile(image,target)
            r['screenshot']=str(target)
            target.with_suffix('.receipt.json').write_text(json.dumps(r))
            self.receipts.append(r)
        event={'tile':'4p','clickIndex':13,'clickPoint':{'x':1532,'y':996.5},
               'frameSha256':'1c5d4474c9a2be1b623aca955e126e5c749b8a218497f609114199a506c844c1'}
        self.journal=[{**event,'status':'attempted','timestamp':'2026-11-03T13:05:41.405080+00:00'},
                      {**event,'status':'selection_confirmed','result':'discard_not_verified','timestamp':'2026-11-03T13:05:42.783782+00:00'}]
        self.watch=Mock(); self.watch.alive.return_value=True
        self.started=time.monotonic()
    def check(self):
        return candidate(self.receipts[0],self.receipts[1:],self.journal,continuity=self.watch,
                         active=lambda:True,started=self.started,deadline_ms=300000)
    def test_real_positive(self):
        self.assertTrue(self.check())
    def test_closed_session_and_expiry(self):
        self.watch.alive.return_value=False
        self.assertFalse(self.check())
        self.watch.alive.return_value=True
        self.started=time.monotonic()-301
        self.assertFalse(self.check())
    def test_same_turn_and_missing_input_are_rejected(self):
        original=self.receipts[1]
        self.receipts[1]=self.receipts[0]
        self.assertFalse(self.check())
        self.receipts[1]=original
        self.journal[0]['status']='not_sent'
        self.assertFalse(self.check())
    def test_hung_ocr_is_rejected_at_child_timeout(self):
        with patch('sanma_friend_discard_recovery.subprocess.run',
                   side_effect=subprocess.TimeoutExpired('ocr',20)) as child:
            self.assertFalse(self.check())
        self.assertLessEqual(child.call_args.kwargs['timeout'],20)
    def test_altered_round_receipt_is_rejected(self):
        board=self.receipts[1]['sourceObservation']['board']['candidate']
        board['round']='east_2'
        Path(self.receipts[1]['screenshot']).with_suffix('.receipt.json').write_text(json.dumps(self.receipts[1]))
        self.assertFalse(self.check())
    def test_red_five_or_meld_or_digest_mismatch(self):
        hand=self.receipts[1]['sourceObservation']['report']['hand']['value']
        for key,value in [('candidateMelds',1),('tiles',['0s']*14)]:
            original=hand[key];hand[key]=value
            path=Path(self.receipts[1]['screenshot']).with_suffix('.receipt.json')
            path.write_text(json.dumps(self.receipts[1]))
            self.assertFalse(self.check());hand[key]=original
            path.write_text(json.dumps(self.receipts[1]))
        self.receipts[1]['digest']='0'*64
        self.assertFalse(self.check())

    def test_saved_real_candidate_reaches_next_discard_in_friend_loop(self):
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        case=ExperimentalSanmaFriendLoopTest('runTest')
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.op.args.max_iterations=3
        for receipt in self.receipts:
            receipt['candidates']={'candidates':[]}
            receipt['freshness']={'status':'identical_pixels_candidate'}
            Path(receipt['screenshot']).with_suffix('.receipt.json').write_text(json.dumps(receipt))
        case.op.inspect_sanma_self_turn.side_effect=self.receipts
        case.op.observe_sanma_friend_transition.return_value={'status':'visual_change_unconfirmed','confirmed':False}
        output={**self.journal[1]}
        def replay(before, posts, journal, **kwargs):
            # The retained frames predate this test run; use their original
            # click journal so capture-time ordering is validated as recorded.
            return candidate(before, posts, self.journal, **kwargs)
        with patch('sanma_friend_discard_recovery.MatchContinuity',return_value=self.watch), \
             patch('sanma_friend_discard_recovery.candidate',side_effect=replay), \
             patch('sanma_friend_discard_experiment.execute_friend_draw_candidate',return_value=output) as discard:
            case.run_room()
        self.assertEqual(discard.call_count,2)
        self.assertTrue(any(c.args[0]=='sanma_friend_discard_recovery_candidate' for c in case.op.log.call_args_list))

    def _real_executor_and_current_journal_with_simulated_page(self, expire=False):
        from auto_operator import utc_stamp
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        case=ExperimentalSanmaFriendLoopTest('runTest'); case.setUp(); self.addCleanup(case.doCleanups)
        case.op.args.max_iterations=3
        case.op.verified_friend_300_active=True
        case.page.is_closed.return_value=False
        geometry=self.receipts[0]['sourceObservation']['report']['handGeometry']['value']
        case.op.layout={'viewport':{'width':1920,'height':1080},'handSlots':geometry['handSlots'],
                        'drawSlot':geometry['drawSlot']}
        cases=[]
        for receipt in self.receipts:
            frame=Path(receipt['screenshot']).read_bytes()
            s=receipt['sourceObservation']['report']['handGeometry']['value']['drawSlot']
            x,y,w,h=(int(s[k]) for k in ('x','y','width','height'))
            img=Image.open(io.BytesIO(frame)).convert('RGB')
            img.paste(img.crop((x,y,x+w,y+h)),(x,y-48))
            data=io.BytesIO(); img.save(data,format='PNG')
            cases.append((frame,data.getvalue()))
        state={'index':0,'selected':False,'clicks':[]}
        def screenshot(**_):
            return cases[state['index']][int(state['selected'])]
        def click(x,y,**_):
            state['clicks'].append((x,y))
            state['selected']=not state['selected']
            if expire and len(state['clicks'])==3:
                watch,_,limit=case.op._sanma_friend_resume_guard
                case.op._sanma_friend_resume_guard=(watch,time.monotonic()-301,limit)
        case.page.screenshot.side_effect=screenshot
        case.page.mouse.click.side_effect=click
        def inspect(_):
            index=inspect.index; inspect.index+=1
            state['index']=index; state['selected']=False
            source=self.receipts[index].copy()
            source.update(scope='sanma_self_turn_observation',candidates={'candidates':[]},
                          freshness={'status':'identical_pixels_candidate'})
            image=Path(case.temp.name)/f'{utc_stamp()}.e2e.png'
            image.write_bytes(cases[index][0]); source['screenshot']=str(image)
            image.with_suffix('.receipt.json').write_text(json.dumps(source))
            return source
        inspect.index=0
        case.op.inspect_sanma_self_turn.side_effect=inspect
        case.op.observe_sanma_friend_transition.return_value={'status':'visual_change_unconfirmed','confirmed':False}
        with patch('auto_operator.classify_screen',return_value=('match',1.0)):
            case.op.run_experimental_sanma_friend(case.page)
        self.assertEqual(len(state['clicks']),3 if expire else 4)
        self.assertEqual(len(case.op._sanma_friend_attempted_targets),2)
        self.assertGreaterEqual(case.page.context.new_cdp_session.return_value.detach.call_count,2)
        events=[c for c in case.op.log.call_args_list if c.args[0]=='sanma_friend_discard_experiment']
        self.assertEqual([e.kwargs['status'] for e in events],
                         ['attempted','selection_confirmed','attempted','failed'] if expire
                         else ['attempted','selection_confirmed']*2)
        resumes=[c for c in case.op.log.call_args_list if c.args[0]=='sanma_friend_discard_recovery_candidate']
        self.assertEqual(len(resumes),1)
        self.assertLessEqual(resumes[0].kwargs['originalStart'],resumes[0].kwargs['attemptedMonotonic'])
        self.assertLessEqual(resumes[0].kwargs['attemptedMonotonic'],resumes[0].kwargs['selectedMonotonic'])
        self.assertLess(resumes[0].kwargs['selectedMonotonic'],resumes[0].kwargs['postMonotonic'][0])
        self.assertLess(resumes[0].kwargs['postMonotonic'][0],resumes[0].kwargs['postMonotonic'][1])
        self.assertLess((time.monotonic()-resumes[0].kwargs['originalStart'])*1000,300000)

    def test_real_executor_and_current_journal_with_simulated_page(self):
        self._real_executor_and_current_journal_with_simulated_page()

    def test_original_deadline_blocks_second_click_after_resume(self):
        self._real_executor_and_current_journal_with_simulated_page(expire=True)
