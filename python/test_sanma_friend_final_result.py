"""Replay a saved CPU-friend final result without navigation or input."""
import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from auto_operator import PythonAutoOperator
from screen_state import classify_screen,load_references

IMAGE=Path('/home/yama1/.codex/sanma-run-d0ff500-20261031/final-result.png')
REFS=Path('/home/yama1/projects/jantama-auto/artifacts/live')
@unittest.skipUnless(IMAGE.exists() and REFS.exists(),'friend result evidence unavailable')
class SanmaFriendFinalResultTest(unittest.TestCase):
 def test_saved_result_is_logged_and_stops_without_input(self):
  frame=IMAGE.read_bytes();refs=load_references(REFS)
  self.assertEqual(classify_screen(frame,refs),('match_result',1.0))
  with tempfile.TemporaryDirectory() as directory:
   op=object.__new__(PythonAutoOperator);op.frames=Path(directory);op.log=Mock();op.screen_references=refs
   op.args=SimpleNamespace(rules='sanma',mode='force-auto',experimental_sanma_friend=True,
       action_deadline_ms=300000,ranked_loop=False,start_reviewed_friend_room='reviewed',max_iterations=2)
   op.verified_friend_300_active=True;page=Mock();page.screenshot.return_value=frame
   op.run_experimental_sanma_friend(page)
   outcomes=[c for c in op.log.call_args_list if c.args[0]=='sanma_friend_result_observed']
   self.assertEqual(len(outcomes),1);self.assertEqual(outcomes[0].kwargs['screenState'],'match_result')
   self.assertFalse(outcomes[0].kwargs['confirmed']);self.assertEqual(Path(outcomes[0].kwargs['screenshot']).read_bytes(),frame)
   self.assertTrue(any(c.kwargs.get('reason')=='match_result_observed' for c in op.log.call_args_list))
   page.mouse.click.assert_not_called()
