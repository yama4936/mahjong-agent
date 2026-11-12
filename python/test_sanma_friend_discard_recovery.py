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

from sanma_friend_discard_recovery import candidate, MatchContinuity
from sanma_friend_freshness import check_friend_recovery_guard

ROOT = Path('/home/yama1/server/data/dev-work/jantama/evidence139')

class ContinuityDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.page=Mock();self.page.url='https://example.invalid/game';self.page.is_closed.return_value=False
        self.session=Mock();self.page.context.new_cdp_session.return_value=self.session
        self.watch=MatchContinuity(self.page)
        self.callbacks={call.args[0]:call.args[1] for call in self.session.on.call_args_list}
    def test_every_interrupt_event_records_only_its_type(self):
        for name in MatchContinuity.EVENTS:
            with self.subTest(name=name):
                self.setUp();self.callbacks[name]({'url':'private', 'payload':'private'})
                self.assertFalse(self.watch.alive())
                result=self.watch.diagnostic()
                self.assertEqual(result['reason'],name);self.assertTrue(result['invalid'])
                self.assertIsInstance(result['elapsedMs'],int);self.assertNotIn('private',str(result))
                self.callbacks['Page.frameDetached']({})
                self.assertEqual(self.watch.diagnostic()['reason'],name)
    def test_websocket_close_is_identified_without_secret_and_still_stops(self):
        request='private-request-id'
        self.callbacks['Network.webSocketClosed']({'requestId':request,'timestamp':123.0,'payload':'secret'})
        self.assertFalse(self.watch.alive())
        result=self.watch.diagnostic()
        self.assertEqual(result['network'],{'requestIdSha256':hashlib.sha256(request.encode()).hexdigest()})
        self.assertNotIn(request,str(result));self.assertNotIn('secret',str(result))
        self.assertNotIn('hostname',result['network'])
    def test_websocket_created_exposes_only_hostname_and_still_stops(self):
        self.callbacks['Network.webSocketCreated']({'requestId':'rid','url':'wss://user:pass@example.test/path?token=secret'})
        self.assertFalse(self.watch.alive())
        result=self.watch.diagnostic();self.assertEqual(result['network']['hostname'],'example.test')
        self.assertNotIn('secret',str(result));self.assertNotIn('pass',str(result));self.assertNotIn('/path',str(result))

    def test_page_change_close_and_exception_remain_fail_closed(self):
        for reason in ('page_url_changed','page_closed','observation_exception:RuntimeError'):
            with self.subTest(reason=reason):
                self.setUp()
                if reason=='page_url_changed':self.page.url='https://other.invalid/'
                elif reason=='page_closed':self.page.is_closed.return_value=True
                else:self.session.send.side_effect=RuntimeError('private detail')
                self.assertFalse(self.watch.alive());self.assertEqual(self.watch.diagnostic()['reason'],reason)
                self.assertNotIn('private',str(self.watch.diagnostic()))

class RecoveryGuardTest(unittest.TestCase):
    @unittest.skipUnless(Path('/home/yama1/server/data/dev-work/jantama/evidence167/artifacts2/frames').exists(),
                         'saved second left north unavailable')
    def test_saved_second_left_north_supports_recovery(self):
        from sanma_discard_evidence_chain import _left_second_north_additions
        root=Path('/home/yama1/server/data/dev-work/jantama/evidence167/artifacts2/frames')
        prefixes=('2026-11-04T01-42-36','2026-11-04T01-43-09','2026-11-04T01-43-20')
        with tempfile.TemporaryDirectory() as directory:
            receipts=[]
            for i,prefix in enumerate(prefixes):
                receipt=json.loads(next(root.glob(prefix+'*.sanma-self-turn.receipt.json')).read_text())
                src=Path(receipt['screenshot']);folder=Path(directory)/str(i);folder.mkdir()
                target=folder/src.name;shutil.copyfile(src,target);receipt['screenshot']=str(target)
                target.with_suffix('.receipt.json').write_text(json.dumps(receipt));receipts.append(receipt)
            self.assertEqual(_left_second_north_additions(receipts[0],receipts[1:]),1)
            self.assertEqual(_left_second_north_additions(receipts[1],receipts[1:]),0)
            self.assertEqual(_left_second_north_additions(receipts[0],[receipts[1],receipts[0]]),0)
            self.assertEqual(_left_second_north_additions(receipts[0],[receipts[1],dict(receipts[2],digest='0'*64)]),0)
            event={'tile':'1m','clickIndex':13,'clickPoint':{'x':1532,'y':996.5},'frameSha256':receipts[0]['digest']}
            journal=[dict(event,status='attempted',timestamp='2026-11-04T01:42:41.246709+00:00'),
                     dict(event,status='selection_confirmed',result='discard_not_verified',
                          timestamp='2026-11-04T01:42:42.570686+00:00')]
            watch=Mock();watch.alive.return_value=True
            check=lambda:candidate(receipts[0],receipts[1:],journal,continuity=watch,
                                   active=lambda:True,started=time.monotonic(),deadline_ms=300000)
            self.assertTrue(check())
            for post in receipts[1:]:
                post['sourceObservation']['board']['candidate']['remainingTiles']=45
                Path(post['screenshot']).with_suffix('.receipt.json').write_text(json.dumps(post))
            self.assertFalse(check())
            broken=json.loads(json.dumps(receipts[2]));path=Path(directory)/'blank-north.png'
            with Image.open(broken['screenshot']) as source:
                image=source.convert('RGB');image.paste((240,240,240),(317,661,406,713));image.save(path)
            broken['screenshot']=str(path);broken['digest']=hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(_left_second_north_additions(receipts[0],[receipts[1],broken]),0)

    @unittest.skipUnless(Path('/home/yama1/server/data/dev-work/jantama/evidence160/artifacts/frames').exists(),
                         'saved ordinary 5p match unavailable')
    def test_two_ordinary_five_pin_saved_match_reaches_candidate(self):
        root=Path('/home/yama1/server/data/dev-work/jantama/evidence160/artifacts/frames')
        prefixes=('2026-11-03T21-38-49','2026-11-03T21-39-13','2026-11-03T21-39-19')
        with tempfile.TemporaryDirectory() as directory:
            receipts=[]
            for i,prefix in enumerate(prefixes):
                receipt=json.loads(next(root.glob(prefix+'*.sanma-self-turn.receipt.json')).read_text())
                source=Path(receipt['screenshot']);folder=Path(directory)/str(i);folder.mkdir()
                target=folder/source.name;shutil.copyfile(source,target);receipt['screenshot']=str(target)
                target.with_suffix('.receipt.json').write_text(json.dumps(receipt));receipts.append(receipt)
            event={'tile':'F','clickIndex':13,'clickPoint':{'x':1532,'y':996.5},'frameSha256':receipts[0]['digest']}
            journal=[dict(event,status='attempted',timestamp='2026-11-03T21:38:54.550798+00:00'),
                     dict(event,status='selection_confirmed',result='discard_not_verified',
                          timestamp='2026-11-03T21:38:55.839931+00:00')]
            watch=Mock();watch.alive.return_value=True
            self.assertTrue(candidate(receipts[0],receipts[1:],journal,continuity=watch,
                                      active=lambda:True,started=time.monotonic(),deadline_ms=300000))
    @unittest.skipUnless(Path('/home/yama1/server/data/dev-work/jantama/evidence158/artifacts/frames').exists(),
                         'saved two opposite north match unavailable')
    def test_two_opposite_norths_support_saved_later_turn(self):
        from sanma_discard_evidence_chain import _opposite_north_additions
        root=Path('/home/yama1/server/data/dev-work/jantama/evidence158/artifacts/frames')
        prefixes=('2026-11-03T20-55-22','2026-11-03T20-55-52','2026-11-03T20-56-03')
        with tempfile.TemporaryDirectory() as directory:
            receipts=[]
            for i,prefix in enumerate(prefixes):
                receipt=json.loads(next(root.glob(prefix+'*.sanma-self-turn.receipt.json')).read_text())
                src=Path(receipt['screenshot']);folder=Path(directory)/str(i);folder.mkdir()
                target=folder/src.name;shutil.copyfile(src,target);receipt['screenshot']=str(target)
                target.with_suffix('.receipt.json').write_text(json.dumps(receipt));receipts.append(receipt)
            self.assertEqual(_opposite_north_additions(receipts[0],receipts[1:]),2)
            self.assertEqual(_opposite_north_additions(receipts[1],receipts[1:]),0)
            self.assertEqual(_opposite_north_additions(receipts[0],[receipts[1],receipts[0]]),0)
            self.assertEqual(_opposite_north_additions(receipts[0],[receipts[1],dict(receipts[2],digest='0'*64)]),0)
            event={'tile':'C','clickIndex':13,'clickPoint':{'x':1532,'y':996.5},'frameSha256':receipts[0]['digest']}
            journal=[dict(event,status='attempted',timestamp='2026-11-03T20:55:27.507162+00:00'),
                     dict(event,status='selection_confirmed',result='discard_not_verified',
                          timestamp='2026-11-03T20:55:28.782773+00:00')]
            watch=Mock();watch.alive.return_value=True
            check=lambda:candidate(receipts[0],receipts[1:],journal,continuity=watch,
                                   active=lambda:True,started=time.monotonic(),deadline_ms=300000)
            self.assertTrue(check())
            for post in receipts[1:]:
                post['sourceObservation']['board']['candidate']['remainingTiles']=48
                Path(post['screenshot']).with_suffix('.receipt.json').write_text(json.dumps(post))
            self.assertFalse(check())
            broken=json.loads(json.dumps(receipts[2]));path=Path(directory)/'non-north.png'
            with Image.open(broken['screenshot']) as src:
                image=src.convert('RGB');image.paste((240,240,240),(581,97,629,134));image.save(path)
            broken['screenshot']=str(path);broken['digest']=hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(_opposite_north_additions(receipts[0],[receipts[1],broken]),1)
    @unittest.skipUnless(Path('/home/yama1/server/data/dev-work/jantama/evidence157/artifacts/frames').exists(),
                         'saved opposite north match unavailable')
    def test_saved_opposite_north_and_reobserved_river(self):
        from sanma_discard_evidence_chain import _opposite_north_additions
        root=Path('/home/yama1/server/data/dev-work/jantama/evidence157/artifacts/frames')
        prefixes=('2026-11-03T20-40-52','2026-11-03T20-41-04','2026-11-03T20-41-10')
        with tempfile.TemporaryDirectory() as directory:
            receipts=[]
            for i,prefix in enumerate(prefixes):
                receipt=json.loads(next(root.glob(prefix+'*.sanma-self-turn.receipt.json')).read_text())
                source=Path(receipt['screenshot']); folder=Path(directory)/str(i);folder.mkdir()
                target=folder/source.name;shutil.copyfile(source,target);receipt['screenshot']=str(target)
                target.with_suffix('.receipt.json').write_text(json.dumps(receipt));receipts.append(receipt)
            self.assertEqual(_opposite_north_additions(receipts[0],receipts[1:]),1)
            self.assertEqual(_opposite_north_additions(receipts[1],receipts[1:]),0)
            self.assertEqual(_opposite_north_additions(receipts[0],[receipts[1],receipts[0]]),0)
            self.assertEqual(_opposite_north_additions(receipts[0],[receipts[1],dict(receipts[2],digest='0'*64)]),0)
            event={'tile':'C','clickIndex':12,'clickPoint':{'x':1407,'y':996.5},'frameSha256':receipts[0]['digest']}
            journal=[dict(event,status='attempted',timestamp='2026-11-03T20:40:57.389991+00:00'),
                     dict(event,status='selection_confirmed',result='discard_not_verified',
                          timestamp='2026-11-03T20:40:58.612896+00:00')]
            watch=Mock();watch.alive.return_value=True
            check=lambda posts:candidate(receipts[0],posts,journal,continuity=watch,
                                         active=lambda:True,started=time.monotonic(),deadline_ms=300000)
            self.assertFalse(check(receipts[1:]))
            # A later frame is simulated from the retained second observation,
            # changing one clock pixel while preserving the stable game state.
            later=json.loads(json.dumps(receipts[2])); folder=Path(directory)/'3';folder.mkdir()
            target=folder/'2026-11-03T20-41-16.000000+00-00.reobserved.sanma-self-turn.png'
            with Image.open(later['screenshot']) as src:
                img=src.convert('RGB');img.putpixel((1500,800),(0,0,0));img.save(target)
            digest=hashlib.sha256(target.read_bytes()).hexdigest()
            later['screenshot']=str(target);later['digest']=digest;later['sourceObservation']['digest']=digest
            later['sourceObservation']['ownRiver']['frameSha256']=digest;later['drawCandidate']['digest']=digest
            target.with_suffix('.receipt.json').write_text(json.dumps(later))
            self.assertTrue(check([receipts[2],later]))
            # The single observed north cannot explain two extra wall draws.
            for post in (receipts[2],later):
                post['sourceObservation']['board']['candidate']['remainingTiles']=48
                Path(post['screenshot']).with_suffix('.receipt.json').write_text(json.dumps(post))
            self.assertFalse(check([receipts[2],later]))
            # A light-colored non-north shape cannot substitute for its glyph.
            broken=json.loads(json.dumps(later));broken_path=folder/'wrong-north.png'
            with Image.open(later['screenshot']) as src:
                img=src.convert('RGB');img.paste((240,240,240),(535,101,575,130));img.save(broken_path)
            broken['screenshot']=str(broken_path);broken['digest']=hashlib.sha256(broken_path.read_bytes()).hexdigest()
            self.assertEqual(_opposite_north_additions(receipts[0],[receipts[2],broken]),0)
    @unittest.skipUnless(Path('/home/yama1/server/data/dev-work/jantama/evidence154/artifacts2/frames').exists(),
                         'saved red 5s match unavailable')
    def test_saved_hand_with_red_and_ordinary_5s_reaches_recovery(self):
        root=Path('/home/yama1/server/data/dev-work/jantama/evidence154/artifacts2/frames')
        prefixes=('2026-11-03T19-09-58','2026-11-03T19-10-14','2026-11-03T19-10-20')
        with tempfile.TemporaryDirectory() as directory:
            receipts=[]
            for i,prefix in enumerate(prefixes):
                receipt=json.loads(next(root.glob(prefix+'*.sanma-self-turn.receipt.json')).read_text())
                source=Path(receipt['screenshot']);folder=Path(directory)/str(i);folder.mkdir()
                target=folder/source.name;shutil.copyfile(source,target);receipt['screenshot']=str(target)
                target.with_suffix('.receipt.json').write_text(json.dumps(receipt));receipts.append(receipt)
            event={'tile':'W','clickIndex':13,'clickPoint':{'x':1532,'y':996.5},'frameSha256':receipts[0]['digest']}
            journal=[dict(event,status='attempted',timestamp='2026-11-03T19:10:03.499907+00:00'),
                     dict(event,status='selection_confirmed',result='discard_not_verified',
                          timestamp='2026-11-03T19:10:04.944922+00:00')]
            watch=Mock();watch.alive.return_value=True
            self.assertTrue(candidate(receipts[0],receipts[1:],journal,continuity=watch,
                                      active=lambda:True,started=time.monotonic(),deadline_ms=300000))
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

    @unittest.skipUnless(Path('/home/yama1/server/data/dev-work/jantama/evidence169/artifacts/frames').exists(),
                         'saved 6p lighting match unavailable')
    def test_saved_six_pin_lighting_and_wrong_tile(self):
        from sanma_concealed_conservation import consistent
        root=Path('/home/yama1/server/data/dev-work/jantama/evidence169/artifacts/frames')
        prefixes=('2026-11-04T02-38-20.599','2026-11-04T02-38-43.602','2026-11-04T02-38-55.663')
        receipts=[json.loads(next(root.glob(p+'*.sanma-self-turn.receipt.json')).read_text()) for p in prefixes]
        self.assertTrue(all(consistent(receipts[0],r,0) for r in receipts[1:]))
        journal=[dict(tile='1m',clickIndex=0,clickPoint={'x':269,'y':996.5},frameSha256=receipts[0]['digest'],status='attempted',timestamp='2026-11-04T02:38:25.551397+00:00'),
                 dict(tile='1m',clickIndex=0,clickPoint={'x':269,'y':996.5},frameSha256=receipts[0]['digest'],status='selection_confirmed',result='discard_not_verified',timestamp='2026-11-04T02:38:26.808426+00:00')]
        watch=Mock(); watch.alive.return_value=True
        self.assertTrue(candidate(receipts[0],receipts[1:],journal,continuity=watch,
                                  active=lambda:True,started=time.monotonic(),deadline_ms=300000))
        with tempfile.TemporaryDirectory() as directory:
            post=receipts[1]; g=post['sourceObservation']['report']['handGeometry']['value']
            slots=[*g['handSlots'],g['drawSlot']]
            tiles=post['sourceObservation']['report']['hand']['value']['tiles']
            destination=slots[tiles.index('6p')]
            box=lambda s:(s['x'],s['y'],s['x']+s['width'],s['y']+s['height'])
            for i,tile in enumerate(tiles):
                if tile=='6p': continue
                with self.subTest(substituted=tile):
                    with Image.open(post['screenshot']) as source:
                        image=source.convert('RGB'); origin=slots[i]
                        image.paste(image.crop(box(origin)).resize((destination['width'],destination['height'])),(destination['x'],destination['y']))
                        path=Path(directory)/'wrong.png'; image.save(path)
                    altered=dict(post,screenshot=str(path))
                    self.assertFalse(consistent(receipts[0],altered,0))

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
        guards=[]
        def execute(*args, **kwargs):
            guards.append(getattr(case.op,'_sanma_friend_resume_guard',None))
            return output
        with patch('sanma_friend_discard_recovery.MatchContinuity',return_value=self.watch), \
             patch('sanma_friend_discard_recovery.candidate',side_effect=replay), \
             patch('sanma_friend_discard_experiment.execute_friend_draw_candidate',side_effect=execute) as discard:
            case.run_room()
        self.assertEqual(discard.call_count,2)
        resume=next(c.kwargs for c in case.op.log.call_args_list if c.args[0]=='sanma_friend_discard_recovery_candidate')
        self.assertEqual(resume['resumedDeadlineStart'],resume['attemptedMonotonic'])
        self.assertIs(guards[1][0],self.watch)
        self.assertEqual(guards[1][1],resume['attemptedMonotonic'])
        self.assertEqual(guards[1][2],300000)

    def test_unresolved_transition_enters_existing_guarded_recovery(self):
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        case=ExperimentalSanmaFriendLoopTest('runTest');case.setUp();self.addCleanup(case.doCleanups)
        case.op.args.max_iterations=3
        for receipt in self.receipts:
            receipt['candidates']={'candidates':[]};receipt['freshness']={'status':'identical_pixels_candidate'}
            Path(receipt['screenshot']).with_suffix('.receipt.json').write_text(json.dumps(receipt))
        case.op.inspect_sanma_self_turn.side_effect=self.receipts
        case.op.observe_sanma_friend_transition.return_value={'status':'unresolved','reason':'transition_not_observed','confirmed':False}
        def replay(before, posts, journal, **kwargs):
            return candidate(before, posts, self.journal, **kwargs)
        with patch('sanma_friend_discard_recovery.MatchContinuity',return_value=self.watch), \
             patch('sanma_friend_discard_recovery.candidate',side_effect=replay), \
             patch('sanma_friend_discard_experiment.execute_friend_draw_candidate',return_value=self.journal[1]) as discard:
            case.run_room()
        self.assertEqual(discard.call_count,2)
        self.assertTrue(any(c.kwargs.get('reason')=='discard_transition_recovery' for c in case.op.log.call_args_list))
        self.assertTrue(any(c.args[0]=='sanma_friend_discard_recovery_candidate' for c in case.op.log.call_args_list))

    def test_unresolved_transition_disconnect_blocks_retry(self):
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        case=ExperimentalSanmaFriendLoopTest('runTest');case.setUp();self.addCleanup(case.doCleanups)
        case.op.args.max_iterations=3
        for receipt in self.receipts:
            receipt['candidates']={'candidates':[]};receipt['freshness']={'status':'identical_pixels_candidate'}
        case.op.inspect_sanma_self_turn.side_effect=self.receipts
        case.op.observe_sanma_friend_transition.return_value={'status':'unresolved','reason':'transition_not_observed','confirmed':False}
        self.watch.alive.return_value=False
        with patch('sanma_friend_discard_recovery.MatchContinuity',return_value=self.watch), \
             patch('sanma_friend_discard_experiment.execute_friend_draw_candidate',return_value=self.journal[1]) as discard:
            case.run_room()
        discard.assert_called_once()
        self.assertTrue(any(c.kwargs.get('reason')=='discard_recovery_session_or_deadline' for c in case.op.log.call_args_list))

    def test_unresolved_with_no_later_turn_never_retries_discard(self):
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        case=ExperimentalSanmaFriendLoopTest('runTest');case.setUp();self.addCleanup(case.doCleanups)
        case.op.args.max_iterations=6
        receipt=dict(self.receipts[0],candidates={'candidates':[]},
                     drawCandidate={'status':'unresolved'},freshness={'status':'identical_pixels_candidate'})
        first=dict(self.receipts[0],candidates={'candidates':[]},freshness={'status':'identical_pixels_candidate'})
        case.op.inspect_sanma_self_turn.side_effect=[first]+[receipt]*5
        case.op.observe_sanma_friend_transition.return_value={'status':'unresolved','reason':'transition_not_observed','confirmed':False}
        with patch('sanma_friend_discard_recovery.MatchContinuity',return_value=self.watch), \
             patch('sanma_friend_discard_experiment.execute_friend_draw_candidate',return_value=self.journal[1]) as discard:
            case.run_room()
        discard.assert_called_once()
        self.assertFalse(any(c.args[0]=='sanma_friend_discard_recovery_candidate' for c in case.op.log.call_args_list))

    def test_unresolved_ron_prompt_never_repeats_discard(self):
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        case=ExperimentalSanmaFriendLoopTest('runTest');case.setUp();self.addCleanup(case.doCleanups)
        case.op.args.max_iterations=4
        first=dict(self.receipts[0],candidates={'candidates':[]},freshness={'status':'identical_pixels_candidate'})
        ron=dict(self.receipts[1],candidates={'candidates':[{'action':'ron'}]},
                 drawCandidate={'status':'unresolved'},freshness={'status':'identical_pixels_candidate'})
        case.op.inspect_sanma_self_turn.side_effect=[first]+[ron]*3
        case.op.observe_sanma_friend_transition.return_value={'status':'unresolved','reason':'transition_not_observed','confirmed':False}
        with patch('sanma_friend_discard_recovery.MatchContinuity',return_value=self.watch), \
             patch('sanma_friend_discard_experiment.execute_friend_draw_candidate',return_value=self.journal[1]) as discard:
            case.run_room()
        discard.assert_called_once()
        self.assertFalse(any(c.args[0]=='sanma_friend_discard_recovery_candidate' for c in case.op.log.call_args_list))

    def test_transition_error_does_not_enter_recovery(self):
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        for reason in ('transition observation failed: disconnected', 'friend session revoked'):
            with self.subTest(reason=reason):
                case=ExperimentalSanmaFriendLoopTest('runTest');case.setUp();self.addCleanup(case.doCleanups)
                case.op.args.max_iterations=3
                case.op.inspect_sanma_self_turn.return_value=dict(self.receipts[0],candidates={'candidates':[]},freshness={'status':'identical_pixels_candidate'})
                case.op.observe_sanma_friend_transition.return_value={'status':'unresolved','reason':reason,'confirmed':False}
                with patch('sanma_friend_discard_recovery.MatchContinuity',return_value=self.watch), \
                     patch('sanma_friend_discard_experiment.execute_friend_draw_candidate',return_value=self.journal[1]) as discard:
                    case.run_room()
                discard.assert_called_once()
                self.assertTrue(any(c.kwargs.get('reason')=='transition_requires_review' for c in case.op.log.call_args_list))
                self.assertFalse(any(c.kwargs.get('reason')=='discard_transition_recovery' for c in case.op.log.call_args_list))

    def test_session_change_logs_monitor_reason_and_stops_before_new_input(self):
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        case=ExperimentalSanmaFriendLoopTest('runTest');case.setUp();self.addCleanup(case.doCleanups)
        case.op.args.max_iterations=3
        for receipt in self.receipts:
            receipt['candidates']={'candidates':[]};receipt['freshness']={'status':'identical_pixels_candidate'}
        case.op.inspect_sanma_self_turn.side_effect=self.receipts
        case.op.observe_sanma_friend_transition.return_value={'status':'visual_change_unconfirmed','confirmed':False}
        self.watch.alive.side_effect=[True,True,False]
        detail={'monitorId':'test-monitor','invalid':True,'reason':'Network.webSocketClosed','elapsedMs':10}
        self.watch.diagnostic.return_value=detail
        with patch('sanma_friend_discard_recovery.MatchContinuity',return_value=self.watch), \
             patch('sanma_friend_discard_recovery.candidate',return_value=True), \
             patch('sanma_friend_discard_experiment.execute_friend_draw_candidate',return_value=self.journal[1]) as discard:
            case.run_room()
        self.assertEqual(discard.call_count,1)
        event=next(c for c in case.op.log.call_args_list if c.kwargs.get('reason')=='discard_recovery_session_changed')
        self.assertEqual(event.kwargs['continuity'],detail)
        self.assertEqual(event.kwargs['digest'],self.receipts[2]['digest'])

    def test_reobserve_is_bounded_and_does_not_repeat_uncertain_input(self):
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        for accepted in (True,False):
            with self.subTest(accepted=accepted):
                case=ExperimentalSanmaFriendLoopTest('runTest');case.setUp();self.addCleanup(case.doCleanups)
                case.op.args.max_iterations=4 if accepted else 6
                receipts=[]
                for i in range(6):
                    r=dict(self.receipts[min(i,2)],candidates={'candidates':[]},
                           freshness={'status':'identical_pixels_candidate'},digest=str(i))
                    receipts.append(r)
                case.op.inspect_sanma_self_turn.side_effect=receipts
                case.op.observe_sanma_friend_transition.return_value={'status':'visual_change_unconfirmed','confirmed':False}
                output={**self.journal[1]}
                calls=[False,True] if accepted else [False,False,False]
                with patch('sanma_friend_discard_recovery.MatchContinuity',return_value=self.watch), \
                     patch('sanma_friend_discard_recovery.candidate',side_effect=calls) as evaluate, \
                     patch('sanma_friend_discard_experiment.execute_friend_draw_candidate',return_value=output) as discard:
                    case.run_room()
                self.assertEqual(evaluate.call_count,len(calls))
                self.assertEqual(discard.call_count,2 if accepted else 1)
                retries=[c for c in case.op.log.call_args_list if c.args[0]=='sanma_friend_discard_recovery_reobserve']
                self.assertEqual(len(retries),1 if accepted else 2)
                self.assertTrue(all(c.kwargs['operationAuthorized'] is False for c in retries))
                if not accepted:
                    self.assertTrue(any(c.kwargs.get('reason')=='discard_recovery_evidence_rejected' for c in case.op.log.call_args_list))

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
        def inspect(_, *, classified_frame=None, classified_started=None):
            self.assertIsInstance(classified_frame, bytes)
            self.assertIsInstance(classified_started, float)
            index=inspect.index; inspect.index+=1
            state['index']=index; state['selected']=False
            source=self.receipts[index].copy()
            source.update(scope='sanma_self_turn_observation',candidates={'candidates':[]},
                          freshness={'status':'identical_pixels_candidate'},
                          captureStartedMonotonic=classified_started)
            case.op._sanma_friend_discard_observation=(source,source['digest'],classified_started)
            case.op.force_auto_click_budget_ms=Mock(return_value=8000)
            image=Path(case.temp.name)/f'{utc_stamp()}.e2e.png'
            image.write_bytes(cases[index][0]); source['screenshot']=str(image)
            image.with_suffix('.receipt.json').write_text(json.dumps(source))
            return source
        inspect.index=0
        case.op.inspect_sanma_self_turn.side_effect=inspect
        case.op.observe_sanma_friend_transition.return_value={'status':'visual_change_unconfirmed','confirmed':False}
        with patch('auto_operator.classify_screen',return_value=('match',1.0)):
            case.op.run_experimental_sanma_friend(case.page)
        self.assertEqual(len(state['clicks']),3 if expire else 4, repr(case.op.log.call_args_list[-5:]))
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

    def test_resumed_deadline_blocks_second_click_after_resume(self):
        self._real_executor_and_current_journal_with_simulated_page(expire=True)

class Evidence194LoopTest(unittest.TestCase):
    @unittest.skipUnless(Path('/home/yama1/server/data/dev-work/jantama/evidence194/attempt/artifacts/frames').exists(), 'evidence194 unavailable')
    def test_unresolved_real_frames_pass_actual_generated_journal(self):
        from datetime import datetime, timezone
        from test_experimental_sanma_friend_loop import ExperimentalSanmaFriendLoopTest
        root=Path('/home/yama1/server/data/dev-work/jantama/evidence194/attempt/artifacts/frames')
        paths=[next(root.glob('*'+stamp+'*.sanma-self-turn.receipt.json'), None)
               for stamp in ('13-59-12','14-00-03','14-00-07')]
        if any(path is None for path in paths):
            self.skipTest('individual evidence194 receipts unavailable')
        receipts=[json.loads(path.read_text()) for path in paths]
        if any(not Path(receipt.get('screenshot','')).is_file() for receipt in receipts):
            self.skipTest('individual evidence194 images unavailable')
        case=ExperimentalSanmaFriendLoopTest('runTest');case.setUp();self.addCleanup(case.doCleanups)
        case.op.args.max_iterations=3
        case.op.inspect_sanma_self_turn.side_effect=receipts
        case.op.observe_sanma_friend_transition.return_value={'status':'unresolved','reason':'transition_not_observed','confirmed':False}
        watch=Mock();watch.alive.return_value=True
        output={'status':'selection_confirmed','result':'discard_not_verified','tile':'P','clickIndex':13,
                'clickPoint':{'x':1532,'y':996.5},'frameSha256':receipts[0]['digest'],
                'blankDrawIdentityUnknown':True}
        times=[datetime(2026,11,12,13,59,17,637067,tzinfo=timezone.utc),
               datetime(2026,11,12,13,59,18,989190,tzinfo=timezone.utc)]
        with patch('auto_operator.datetime', wraps=datetime) as clock, \
             patch('sanma_friend_discard_recovery.MatchContinuity',return_value=watch), \
             patch('sanma_friend_discard_experiment.execute_friend_draw_candidate',return_value=output) as discard:
            clock.now.side_effect=times+[times[-1]]*10
            case.run_room()
        self.assertEqual(discard.call_count,2)
        self.assertTrue(any(c.args[0]=='sanma_friend_discard_recovery_candidate' for c in case.op.log.call_args_list))


class Evidence196DeadlineTest(unittest.TestCase):
    @unittest.skipUnless(Path('/home/yama1/server/data/dev-work/jantama/evidence196/operator.log').exists(), 'evidence196 unavailable')
    def test_real_later_turn_evidence_and_conservative_attempt_bound(self):
        path=Path('/home/yama1/server/data/dev-work/jantama/evidence196/operator.log')
        rows=[json.loads(line) for line in path.read_text().splitlines() if line.startswith('{')]
        resume=next(row for row in rows if row.get('event')=='sanma_friend_discard_recovery_candidate')
        stop=next(row for row in rows if row.get('reason')=='discard_recovery_session_or_deadline')
        screenshots=resume['screenshots']
        receipts=[json.loads(Path(p).with_suffix('.receipt.json').read_text()) for p in screenshots]
        watch=Mock(); watch.alive.return_value=True
        # Replay real pixels/recognition while supplying a current test clock.
        self.assertTrue(candidate(receipts[0],receipts[1:],resume['journal'],continuity=watch,
                                  active=lambda:True,started=time.monotonic(),deadline_ms=300000))
        self.assertGreaterEqual(stop['deadlineElapsedMs'],300000)
        self.assertLess(stop['originalStart'],resume['attemptedMonotonic'])
        self.assertLess(resume['attemptedMonotonic'],resume['selectedMonotonic'])
        self.assertLess(resume['selectedMonotonic'],resume['postMonotonic'][0])
        # At the observed stop, this stricter-than-new-turn bound was live.
        stopped_at=stop['originalStart']+stop['deadlineElapsedMs']/1000
        self.assertLess((stopped_at-resume['attemptedMonotonic'])*1000,300000)
