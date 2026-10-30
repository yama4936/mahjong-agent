"""Real prompt with synthetic countdown-only changes; no browser input."""
import io
import hashlib
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image,ImageDraw
from sanma_friend_freshness import friend_frame_changes,friend_frame_stable,latch_friend_action_target
from sanma_friend_discard_experiment import execute_friend_discard

IMAGE=Path('/home/yama1/sanma-independent-20261031/20-turn.png')


def modified(frame, box):
    with Image.open(io.BytesIO(frame)) as source:
        image=source.convert('RGB')
    ImageDraw.Draw(image).rectangle(box,fill=(11,44,99))
    output=io.BytesIO();image.save(output,format='PNG');return output.getvalue()


@unittest.skipUnless(IMAGE.exists(),'independent frame unavailable')
class SanmaFriendFreshnessTests(unittest.TestCase):
    def setUp(self): self.frame=IMAGE.read_bytes()
    def test_clock_only_change_is_recorded_and_visible_areas_still_match(self):
        newer=modified(self.frame,(1500,780,1550,830))
        self.assertNotEqual(self.frame,newer)
        self.assertEqual(friend_frame_changes(self.frame,newer),{'hand':False,'actions':False,'fullFrame':False,'clock':True})
        self.assertTrue(friend_frame_stable(self.frame,newer))
    def test_action_latch_ignores_clock_and_rejects_repeat(self):
        for action in ("kita", "tsumo", "discard"):
            with self.subTest(action=action):
                operator=Mock()
                latch_friend_action_target(operator,self.frame,action)
                with self.assertRaisesRegex(RuntimeError,"outcome unknown"):
                    latch_friend_action_target(operator,modified(self.frame,(1500,780,1550,830)),action)
                latch_friend_action_target(operator,modified(self.frame,(900,800,910,810)),action)

    def test_hand_button_river_and_clock_boundary_changes_fail(self):
        for box in [(1500,900,1510,910),(900,800,910,810),(1000,500,1010,510),(1424,780,1424,780),(1500,870,1500,870)]:
            with self.subTest(box=box): self.assertFalse(friend_frame_stable(self.frame,modified(self.frame,box)))

    @patch('sanma_friend_discard_experiment.send_discard_click',return_value={'lift':48})
    def test_discard_dispatch_accepts_only_clock_change_from_bound_frame(self,send):
        point={'x':300,'y':1000}; digest=hashlib.sha256(self.frame).hexdigest()
        session={'mode':'cpu_friend','rules':'sanma','clock':'300+0','actionDeadlineMs':300000,
                 'ranked':False,'cpuCount':2,'roomVerified':True}
        observation={'status':'candidate','phase':'self_turn','promptStatus':'none','handStatus':'candidate',
                     'layoutStatus':'candidate','slots':[{'tile':'1m',**point}],
                     'frameSha256':digest,'referenceFrame':self.frame}
        plan={'scope':'offline_untrusted_sanma_discard_plan','operationAuthorized':False,'tile':'1m','clickIndex':0,'clickPoint':point}
        page=Mock();page.screenshot.return_value=modified(self.frame,(1500,780,1550,830))
        kw={'session':session,'observation':observation,'plan':plan,'layout':{'viewport':{'width':1920,'height':1080}},
            'log':lambda event:None,'turn_started_monotonic':100,'clock':lambda:101}
        self.assertEqual(execute_friend_discard(page,**kw)['result'],'discard_not_verified')
        send.assert_called_once()
        send.reset_mock();page.screenshot.return_value=modified(self.frame,(900,800,910,810))
        with self.assertRaisesRegex(ValueError,'frame changed'):execute_friend_discard(page,**kw)
        send.assert_not_called()
