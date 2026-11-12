import copy
import json
import hashlib
import io
import tempfile
from PIL import Image
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from sanma_friend_kita_rearm import rearm_friend_kita_candidate
from sanma_friend_freshness import friend_action_target_key

REPLAY=Path('/home/yama1/projects/jantama-test-tmp/kita-observe-replay.jsonl')
DATA88=Path('/home/yama1/server/data/dev-work/jantama/data88-run3/frames')

@unittest.skipUnless(Path('/home/yama1/server/data/dev-work/jantama/evidence162/artifacts/frames').exists(),
                     'saved three north match unavailable')
class ThirdNorthTests(unittest.TestCase):
    def setUp(self):
        root=Path('/home/yama1/server/data/dev-work/jantama/evidence162/artifacts/frames')
        self.before,self.after=[json.loads(next(root.glob(prefix+'*.sanma-self-turn.receipt.json')).read_text())
                                for prefix in ('2026-11-03T22-48-02','2026-11-03T22-48-44')]
        self.op=Mock();self.op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
        self.op.verified_friend_300_active=True;self.op._sanma_friend_kita_rearmed=True;self.op._sanma_friend_kita_rearmed_twice=False
        self.op._sanma_friend_attempted_targets={friend_action_target_key(Path(self.before['screenshot']).read_bytes(),'kita')}
    def test_saved_third_north_candidate_rearms_once(self):
        self.assertTrue(rearm_friend_kita_candidate(self.op,self.before,self.after))
        self.assertTrue(self.op._sanma_friend_kita_rearmed_twice)
        self.assertFalse(rearm_friend_kita_candidate(self.op,self.before,self.after))
    def test_geometry_diagnostics_are_recomputed_and_tampering_rejected(self):
        from sanma_friend_freshness import friend_frame_changes
        for receipt in (self.before, self.after):
            fresh = receipt['freshness']
            details = {}
            changes = friend_frame_changes(Path(receipt['screenshot']).read_bytes(),
                Path(fresh['screenshot']).read_bytes(),
                report=receipt['sourceObservation']['report'], diagnostic=details)
            fresh['handRegionDiagnostics'] = details
            fresh['regionsChanged'] = {k:v for k,v in changes.items() if k != 'clock'}
        self.after['freshness']['handRegionDiagnostics']['operationAuthorized'] = True
        self.assertFalse(rearm_friend_kita_candidate(self.op,self.before,self.after))
        self.after['freshness']['handRegionDiagnostics']['operationAuthorized'] = False
        self.assertTrue(rearm_friend_kita_candidate(self.op,self.before,self.after))

    def test_missing_changed_reversed_or_ranked_evidence_is_rejected(self):
        for kind in ('same','reversed','no_target','wrong_tile','ranked','already_twice'):
            with self.subTest(kind=kind):
                self.setUp();before=copy.deepcopy(self.before);after=copy.deepcopy(self.after)
                if kind=='same':after=before
                if kind=='reversed':before,after=after,before
                if kind=='no_target':self.op._sanma_friend_attempted_targets.clear()
                if kind=='wrong_tile':after['sourceObservation']['report']['hand']['value']['tiles'][11]='S'
                if kind=='ranked':self.op.args.ranked_loop=True
                if kind=='already_twice':self.op._sanma_friend_kita_rearmed_twice=True
                self.assertFalse(rearm_friend_kita_candidate(self.op,before,after))
    def test_blank_or_spurious_second_north_fragment_is_rejected(self):
        for color in ((255,255,255),(40,70,110)):
            with self.subTest(color=color), tempfile.TemporaryDirectory() as tmp:
                self.setUp();after=copy.deepcopy(self.after)
                with Image.open(after['screenshot']) as source:
                    image=source.convert('RGB');image.paste(color,(1324,765,1359,790));path=Path(tmp)/'altered.png';image.save(path)
                digest=hashlib.sha256(path.read_bytes()).hexdigest()
                after['screenshot']=str(path);after['digest']=digest
                after['sourceObservation']['digest']=digest;after['sourceObservation']['report']['digest']=digest
                after['drawCandidate']['digest']=digest
                after['freshness'].update(screenshot=str(path),digest=digest,status='identical_pixels_candidate',
                    clockChanged=False,regionsChanged={'hand':False,'actions':False,'fullFrame':False})
                self.assertFalse(rearm_friend_kita_candidate(self.op,self.before,after))

@unittest.skipUnless(DATA88.exists(), 'independent live capture unavailable')
class Data88GuardReplayTests(unittest.TestCase):
    def test_real_guard_accepts_recorded_north_change_but_rejects_same_and_reversed(self):
        paths=sorted(DATA88.glob('*.sanma-self-turn.receipt.json'))
        self.assertGreaterEqual(len(paths), 2)
        before, after=(json.loads(p.read_text()) for p in paths[-2:])
        def operator():
            op=Mock()
            op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
            op.verified_friend_300_active=True
            op._sanma_friend_kita_rearmed=False
            op._sanma_friend_attempted_targets={friend_action_target_key(Path(before['screenshot']).read_bytes(),'kita')}
            return op
        self.assertTrue(rearm_friend_kita_candidate(operator(), before, after))
        self.assertFalse(rearm_friend_kita_candidate(operator(), before, before))
        self.assertFalse(rearm_friend_kita_candidate(operator(), after, before))

@unittest.skipUnless(REPLAY.exists(), 'recorded friend replay missing')
class KitaRearmTests(unittest.TestCase):
    def setUp(self):
        data=[json.loads(line) for line in REPLAY.read_text().splitlines()]
        self.before=data[0]['r'];self.after=data[3]['r']
        self.before['screenshot']=data[0]['file'];self.after['screenshot']=data[3]['file']
        # Offline replay freshness files were temporary. Restore only paths whose
        # existing bytes match the recorded digest; these are not live observations.
        for r in (self.before, self.after):
            frame=Path(r['screenshot'])
            if hashlib.sha256(frame.read_bytes()).hexdigest() != r['freshness']['digest']:
                self.skipTest('recorded replay freshness content unavailable')
            r['freshness']['screenshot']=str(frame)
        self.op=Mock();self.op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
        self.op.verified_friend_300_active=True;self.op._sanma_friend_kita_rearmed=False
        self.op._sanma_friend_attempted_targets={friend_action_target_key(Path(data[0]['file']).read_bytes(),'kita')}
    def test_offline_replay_restored_by_digest_rearms_without_live_observation_or_confirmation(self):
        self.assertTrue(rearm_friend_kita_candidate(self.op,self.before,self.after))
        self.assertFalse(self.op.log.call_args.kwargs['confirmed'])
        self.assertFalse(rearm_friend_kita_candidate(self.op,self.before,self.after))
    def test_offline_replay_rejects_missing_swapped_and_inconsistent_freshness(self):
        for case in ('missing', 'wrong_digest', 'swapped', 'changed', 'wrong_status', 'wrong_regions', 'wrong_clock'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                self.setUp(); before=copy.deepcopy(self.before); after=copy.deepcopy(self.after)
                f=after['freshness']
                if case=='missing': f['screenshot']=str(Path(tmp)/'missing.png')
                if case=='wrong_digest': f['digest']='0'*64
                if case=='swapped': f['screenshot']=before['screenshot'];f['digest']=before['digest']
                if case=='changed':
                    image=Image.open(f['screenshot']).convert('RGB')
                    pixel=image.getpixel((800,600)); image.putpixel((800,600),tuple(v^255 for v in pixel))
                    buf=io.BytesIO(); image.save(buf,format='PNG'); changed=buf.getvalue()
                    path=Path(tmp)/'changed.png'; path.write_bytes(changed)
                    f['screenshot']=str(path); f['digest']=hashlib.sha256(changed).hexdigest()
                if case=='wrong_status': f['status']='stable_except_clock_candidate'
                if case=='wrong_regions': f['regionsChanged']['hand']=True
                if case=='wrong_clock': f['clockChanged']=True
                self.assertFalse(rearm_friend_kita_candidate(self.op,before,after))

    def test_same_frame_stale_weak_draw_and_ranked_rejected(self):
        for case in ('same','stale','draw','ranked','north'):
            self.setUp();before=copy.deepcopy(self.before);after=copy.deepcopy(self.after)
            if case=='same':after=before
            if case=='stale':after['freshness']['status']='changed'
            if case=='draw':after['sourceObservation']['report']['hand']['value']['matches'][-1]['confidence']=.7
            if case=='ranked':self.op.args.ranked_loop=True
            if case=='north':after['sourceObservation']['report']['hand']['value']['tiles'][11]='S'
            with self.subTest(case=case):self.assertFalse(rearm_friend_kita_candidate(self.op,before,after))

class SyntheticFreshnessReceiptTests(unittest.TestCase):
    """Fabricated observations exercise freshness checks, not independent live captures."""

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.receipts=[]
        for i, tiles in enumerate((
            ['N','N','1p','2p','3p','4p','5p','6p','7p','8p','9p','1s','2s','3s'],
            ['N','1p','2p','3p','4p','5p','6p','7p','8p','9p','1s','2s','3s','4s'],
        )):
            image=Image.new('RGB',(1920,1080),'black')
            if i:
                with Image.open(Path(__file__).parent/'fixtures'/'sanma-friend-first-north-visible.png') as north:
                    image.paste(north.convert('RGB'),(1390,765))
            path=Path(self.tmp.name)/f'{i}.png'; image.save(path)
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            hand={'tiles':tiles,'matches':[{'tile':t,'confidence':.99,'runnerUpConfidence':.1} for t in tiles]}
            self.receipts.append({'scope':'sanma_self_turn_observation','operationAuthorized':False,
                'screenshot':str(path),'digest':digest,
                'sourceObservation':{'operationAuthorized':False,'digest':digest,
                    'report':{'digest':digest,'hand':{'status':'candidate','value':hand}}},
                'freshness':{'status':'identical_pixels_candidate','operationAuthorized':False,
                    'elapsedMs':1,'screenshot':str(path),'digest':digest,'clockChanged':False,
                    'regionsChanged':{'hand':False,'actions':False,'fullFrame':False}},
                'drawCandidate':{'status':'candidate','index':13,'tile':tiles[-1],'digest':digest}})
        self.op=Mock(); self.op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
        self.op.verified_friend_300_active=True; self.op._sanma_friend_kita_rearmed=False
        self.op._sanma_friend_attempted_targets={friend_action_target_key(Path(self.receipts[0]['screenshot']).read_bytes(),'kita')}

    def test_fabricated_receipts_are_consistent_without_claiming_live_confirmation(self):
        self.assertTrue(rearm_friend_kita_candidate(self.op,*self.receipts))
        self.assertFalse(self.op.log.call_args.kwargs['confirmed'])

    def test_non_friend_deadline_rejected_before_rearm(self):
        self.op.args.action_deadline_ms = 299999
        self.assertFalse(rearm_friend_kita_candidate(self.op, *self.receipts))

    def test_unchanged_receipt_cannot_rearm(self):
        before = self.receipts[0]
        self.assertFalse(rearm_friend_kita_candidate(self.op, before, copy.deepcopy(before)))

    def test_reversed_candidate_cannot_rearm(self):
        self.assertFalse(rearm_friend_kita_candidate(self.op, self.receipts[1], self.receipts[0]))

    def test_glyph_status_rechecks_pixels_and_does_not_trust_receipt(self):
        before, after = copy.deepcopy(self.receipts)
        f = after['freshness']
        with Image.open(f['screenshot']) as original:
            image = original.convert('RGB')
        image.putpixel((800, 600), (255, 255, 255))
        path = Path(self.tmp.name) / 'fresh-changed.png'
        image.save(path)
        f['screenshot'] = str(path)
        f['digest'] = hashlib.sha256(path.read_bytes()).hexdigest()
        from sanma_friend_freshness import friend_frame_changes
        changes = friend_frame_changes(Path(after['screenshot']).read_bytes(), path.read_bytes())
        f['status'] = 'stable_kita_glyph_candidate'
        f['clockChanged'] = changes['clock']
        f['regionsChanged'] = {k: v for k, v in changes.items() if k != 'clock'}
        with patch('auto_operator.experimental_kita_glyph_stability', return_value=False) as guard:
            self.assertFalse(rearm_friend_kita_candidate(self.op, before, after))
            guard.assert_called_once()
        with patch('auto_operator.experimental_kita_glyph_stability', return_value=True) as guard:
            self.assertTrue(rearm_friend_kita_candidate(self.op, before, after))
            guard.assert_called_once()

    def test_fabricated_receipts_reject_missing_swapped_and_contradictory_freshness(self):
        for case in ('missing','digest','swapped','pixels','status','regions','clock'):
            with self.subTest(case=case):
                self.setUp(); before,after=copy.deepcopy(self.receipts); f=after['freshness']
                if case=='missing': f['screenshot']=str(Path(self.tmp.name)/'missing.png')
                elif case=='digest': f['digest']='0'*64
                elif case=='swapped': f['screenshot']=before['screenshot'];f['digest']=before['digest']
                elif case=='pixels':
                    with Image.open(f['screenshot']) as original: image=original.convert('RGB')
                    image.putpixel((800,600),(255,255,255)); path=Path(self.tmp.name)/'changed.png';image.save(path)
                    f['screenshot']=str(path);f['digest']=hashlib.sha256(path.read_bytes()).hexdigest()
                elif case=='status': f['status']='stable_except_clock_candidate'
                elif case=='regions': f['regionsChanged']['hand']=True
                elif case=='clock': f['clockChanged']=True
                self.assertFalse(rearm_friend_kita_candidate(self.op,before,after))

class Evidence195FourthNorthTests(unittest.TestCase):
    def setUp(self):
        root=Path('/home/yama1/server/data/dev-work/jantama/evidence195/attempt/artifacts/frames')
        receipts=list(root.glob('*.sanma-self-turn.receipt.json'))
        wanted=('a1d83a810a8fc9f0904ac3a905b8f4020b3760bed9333c46d7ff9b0f6cc5be55','26be72a73f501e59b4b05099e890aabdd15d379d972d9672f4f8559771eb009a')
        records={}
        for path in receipts:
            receipt=json.loads(path.read_text())
            if receipt.get('digest') in wanted: records[receipt['digest']]=receipt
        if any(k not in records for k in wanted):self.skipTest('195 screenshots unavailable')
        self.before,self.after=[records[k] for k in wanted]
        if any(not Path(r['screenshot']).is_file() or not Path(r['freshness']['screenshot']).is_file() for r in (self.before,self.after)):
            self.skipTest('195 screenshots unavailable')
        self.op=Mock();self.op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False)
        self.op.verified_friend_300_active=True;self.op._sanma_friend_kita_rearmed=True;self.op._sanma_friend_kita_rearmed_twice=True;self.op._sanma_friend_kita_rearmed_thrice=False
        self.op._sanma_friend_attempted_targets={friend_action_target_key(Path(self.before['screenshot']).read_bytes(),'kita')}
        self.watch=Mock();self.watch.alive.return_value=True
    def test_real_fourth_north_and_no_duplicate(self):
        self.assertTrue(rearm_friend_kita_candidate(self.op,self.before,self.after,continuity=self.watch))
        self.assertFalse(rearm_friend_kita_candidate(self.op,self.before,self.after,continuity=self.watch))
    def test_no_connection_different_round_or_hand_fail(self):
        for case in ('disconnect','round','count','score','different_tile','same','reversed','north_limit'):
            with self.subTest(case=case):
                self.setUp();before=copy.deepcopy(self.before);after=copy.deepcopy(self.after)
                if case=='disconnect':self.watch.alive.return_value=False
                if case=='round':after['sourceObservation']['board']['candidate']['round']='east_2'
                if case=='count':after['sourceObservation']['board']['candidate']['remainingTiles']-=1
                if case=='different_tile':after['sourceObservation']['report']['hand']['value']['tiles'][-1]='S'
                if case=='score':after['sourceObservation']['board']['candidate']['scores']['south']-=1000
                if case=='north_limit':self.op._sanma_friend_kita_rearmed_thrice=True
                if case=='same':after=before
                if case=='reversed':before,after=after,before
                self.assertFalse(rearm_friend_kita_candidate(self.op,before,after,continuity=self.watch))

    def test_live_loop_rearms_only_after_watched_third_input(self):
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        case=ExperimentalSanmaFriendLoopTest('runTest');case.setUp();self.addCleanup(case.doCleanups)
        case.op.args.max_iterations=3
        case.op._sanma_friend_kita_rearmed=True;case.op._sanma_friend_kita_rearmed_twice=True;case.op._sanma_friend_kita_rearmed_thrice=False
        case.op._sanma_friend_attempted_targets=set();case.op._sanma_friend_attempted_frames=set()
        case.op.inspect_sanma_self_turn.side_effect=[self.before,self.after]
        case.op.observe_sanma_friend_transition.return_value={'status':'visual_change_unconfirmed','confirmed':False}
        calls=[]
        def execute(page,receipt):
            calls.append(receipt['digest'])
            case.op._sanma_friend_attempted_targets.add(friend_action_target_key(Path(receipt['screenshot']).read_bytes(),'kita'))
            return {'clicked':True,'confirmation':'unknown'}
        case.op.execute_sanma_friend_kita_candidate.side_effect=execute
        with patch('sanma_friend_discard_recovery.MatchContinuity',return_value=self.watch):
            case.run_room()
        self.assertEqual(calls,[self.before['digest'],self.after['digest']],repr(case.op.log.call_args_list[-5:]))
        self.assertTrue(case.op._sanma_friend_kita_rearmed_thrice)
        self.assertGreaterEqual(self.watch.alive.call_count,2)

    def test_disconnect_between_latch_and_click_stops_actual_executor(self):
        import time
        from auto_operator import PythonAutoOperator
        op=object.__new__(PythonAutoOperator)
        op.args=SimpleNamespace(experimental_sanma_friend=True,rules='sanma',mode='force-auto',action_deadline_ms=300000,ranked_loop=False,force_auto_click_budget_ms=8000)
        op.verified_friend_300_active=True;op.verified_friend_300_started_at=time.monotonic()
        op.log=Mock();op.screen_references={}
        with tempfile.TemporaryDirectory() as tmp:
            op.frames=Path(tmp)
            receipt=copy.deepcopy(self.after);receipt['captureStartedMonotonic']=time.monotonic()
            op._sanma_friend_discard_observation=(receipt,receipt['digest'],receipt['captureStartedMonotonic'])
            self.watch.alive.side_effect=[True,False]
            op._sanma_friend_resume_guard=(self.watch,op.verified_friend_300_started_at,300000)
            page=Mock();page.screenshot.return_value=Path(receipt['screenshot']).read_bytes()
            with patch('auto_operator.classify_screen',return_value=('match',1.0)):
                with self.assertRaisesRegex(RuntimeError,'continuity'):
                    op.execute_sanma_friend_kita_candidate(page,receipt)
            page.mouse.click.assert_not_called()

    def test_ron_or_tsumo_takes_priority_over_fourth_north(self):
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        for action in ('ron','tsumo'):
            with self.subTest(action=action):
                case=ExperimentalSanmaFriendLoopTest('runTest');case.setUp();self.addCleanup(case.doCleanups)
                case.op.args.max_iterations=3
                case.op._sanma_friend_kita_rearmed=True;case.op._sanma_friend_kita_rearmed_twice=True;case.op._sanma_friend_kita_rearmed_thrice=False
                case.op._sanma_friend_attempted_targets=set();case.op._sanma_friend_attempted_frames=set()
                after=copy.deepcopy(self.after);after['candidates']['candidates'].insert(0,{'action':action})
                case.op.inspect_sanma_self_turn.side_effect=[self.before,after]
                case.op.observe_sanma_friend_transition.return_value={'status':'visual_change_unconfirmed','confirmed':False}
                case.op.execute_sanma_friend_ron_candidate=Mock(return_value={'clicked':True})
                case.op.execute_sanma_friend_tsumo_candidate=Mock(return_value={'clicked':True})
                def execute(page,receipt):
                    case.op._sanma_friend_attempted_targets.add(friend_action_target_key(Path(receipt['screenshot']).read_bytes(),'kita'))
                    return {'clicked':True}
                case.op.execute_sanma_friend_kita_candidate.side_effect=execute
                with patch('sanma_friend_discard_recovery.MatchContinuity',return_value=self.watch):case.run_room()
                case.op.execute_sanma_friend_kita_candidate.assert_called_once()
                getattr(case.op,'execute_sanma_friend_'+action+'_candidate').assert_called_once()

    def test_forged_third_extracted_north_is_rejected(self):
        after=copy.deepcopy(self.after)
        with tempfile.TemporaryDirectory() as tmp:
            with Image.open(after['screenshot']) as source:
                image=source.convert('RGB');image.paste((255,255,255),(1258,765,1293,790))
                path=Path(tmp)/'altered.png';image.save(path)
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            after['screenshot']=str(path);after['digest']=digest
            after['sourceObservation']['digest']=digest;after['sourceObservation']['report']['digest']=digest
            after['drawCandidate']['digest']=digest
            after['freshness'].pop('handRegionDiagnostics',None)
            after['freshness'].update(screenshot=str(path),digest=digest,status='identical_pixels_candidate',
                clockChanged=False,regionsChanged={'hand':False,'actions':False,'fullFrame':False})
            self.assertFalse(rearm_friend_kita_candidate(self.op,self.before,after,continuity=self.watch))

    def test_fourth_preclick_rejection_restores_guard_and_reobserves(self):
        from auto_operator import SanmaKitaPreclickChanged
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        case=ExperimentalSanmaFriendLoopTest('runTest');case.setUp();self.addCleanup(case.doCleanups)
        case.op.args.max_iterations=4
        case.op._sanma_friend_kita_rearmed=True;case.op._sanma_friend_kita_rearmed_twice=True;case.op._sanma_friend_kita_rearmed_thrice=False
        case.op._sanma_friend_attempted_targets=set();case.op._sanma_friend_attempted_frames=set()
        case.op.inspect_sanma_self_turn.side_effect=[self.before,self.after,self.after]
        case.op.observe_sanma_friend_transition.return_value={'status':'visual_change_unconfirmed','confirmed':False}
        calls=[]
        def execute(page,receipt):
            calls.append(receipt['digest'])
            if len(calls)==2:raise SanmaKitaPreclickChanged('no input sent')
            case.op._sanma_friend_attempted_targets.add(friend_action_target_key(Path(receipt['screenshot']).read_bytes(),'kita'))
            return {'clicked':True,'confirmation':'unknown'}
        case.op.execute_sanma_friend_kita_candidate.side_effect=execute
        with patch('sanma_friend_discard_recovery.MatchContinuity',return_value=self.watch), \
             patch('auto_operator.may_reobserve_unsent_kita',return_value=True):
            case.run_room()
        self.assertEqual(calls,[self.before['digest'],self.after['digest'],self.after['digest']],repr(case.op.log.call_args_list[-6:]))
        self.assertTrue(case.op._sanma_friend_kita_rearmed_thrice)

    def test_third_preclick_rejection_closes_watch_and_rearms_again(self):
        from auto_operator import SanmaKitaPreclickChanged
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        case=ExperimentalSanmaFriendLoopTest('runTest');case.setUp();self.addCleanup(case.doCleanups)
        case.op.args.max_iterations=4
        case.op._sanma_friend_kita_rearmed=True;case.op._sanma_friend_kita_rearmed_twice=False;case.op._sanma_friend_kita_rearmed_thrice=False
        old=friend_action_target_key(Path(self.before['screenshot']).read_bytes(),'kita')
        case.op._sanma_friend_attempted_targets=set();case.op._sanma_friend_attempted_frames=set()
        case.op.inspect_sanma_self_turn.side_effect=[self.before,self.after,self.after]
        case.op.observe_sanma_friend_transition.return_value={'status':'visual_change_unconfirmed','confirmed':False}
        calls=[];watches=[Mock(),Mock()]
        for w in watches:w.alive.return_value=True
        def execute(page,receipt):
            calls.append(receipt['digest'])
            if len(calls)==2:raise SanmaKitaPreclickChanged('no input sent')
            case.op._sanma_friend_attempted_targets.add(friend_action_target_key(Path(receipt['screenshot']).read_bytes(),'kita'))
            return {'clicked':True,'confirmation':'unknown'}
        def rearm(op,before,after):
            op._sanma_friend_attempted_targets.remove(old);op._sanma_friend_kita_rearmed_twice=True;return True
        case.op.execute_sanma_friend_kita_candidate.side_effect=execute
        with patch('sanma_friend_kita_rearm.rearm_friend_kita_candidate',side_effect=rearm), \
             patch('sanma_friend_discard_recovery.MatchContinuity',side_effect=watches), \
             patch('auto_operator.may_reobserve_unsent_kita',return_value=True):
            case.run_room()
        self.assertEqual(calls,[self.before['digest'],self.after['digest'],self.after['digest']],repr(case.op.log.call_args_list[-6:]))
        watches[0].close.assert_called_once()
        self.assertTrue(case.op._sanma_friend_kita_rearmed_twice)
