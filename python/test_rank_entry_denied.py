import argparse
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from PIL import Image, ImageDraw
from auto_operator import PythonAutoOperator
from screen_state import classify_screen

class RankEntryDeniedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get("JANTAMA_ARCHIVE_ROOT")
        if not root: raise unittest.SkipTest("archive not configured")
        cls.live = Path(root) / "live"
        cls.denied = (cls.live / "b2a16a7-copper-menu-20261015.png").read_bytes()

    def test_distinct_saved_denial_and_normal_screens(self):
        for name in ("b2a16a7-copper-menu-20261015.png", "copper-room-fc882f1-20261003.png", "bronze-84230ae-bronze-menu-20260930.png"):
            with self.subTest(name=name): self.assertEqual(classify_screen(self.live / name, {}), ("rank_entry_denied",1.0))
        for name in ("48925ca-copper-preflight-20261015.png", "login-screen-20261005.png"):
            with self.subTest(name=name): self.assertNotEqual(classify_screen(self.live / name, {})[0], "rank_entry_denied")
        image = Image.open(io.BytesIO(self.denied)).convert("RGB")
        ImageDraw.Draw(image).rectangle((600,450,1320,560),fill=(20,30,50))
        data = io.BytesIO(); image.save(data,format="PNG")
        self.assertNotEqual(classify_screen(data.getvalue(), {})[0], "rank_entry_denied")
        data = io.BytesIO(); image.resize((1280,720)).save(data,format="PNG")
        self.assertNotEqual(classify_screen(data.getvalue(), {})[0], "rank_entry_denied")

    def test_denial_logs_evidence_stops_without_any_click(self):
        op=PythonAutoOperator.__new__(PythonAutoOperator)
        op.args=argparse.Namespace(ranked_loop=True, mode="force-auto")
        op.log=Mock();op.observe_ranked_match_screen=Mock();op.guard_black_recovery_outcome=Mock(return_value=False)
        page=Mock()
        with tempfile.TemporaryDirectory() as directory:
            op.frames=Path(directory)
            with self.assertRaisesRegex(RuntimeError,"rank_entry_denied"):
                op.handle_early_non_gameplay_screen(page,"rank_entry_denied",1.0,screenshot=self.denied)
            evidence=next(Path(directory).glob("*.rank-entry-denied.png"))
            self.assertEqual(evidence.read_bytes(),self.denied)
        page.mouse.click.assert_not_called()
        self.assertEqual(op.log.call_args.args[0],"blocking_dialog_stop")
        self.assertEqual(op.log.call_args.kwargs["gameplayClicks"],0)

    def test_operator_run_stops_in_stream_and_synchronous_paths_even_when_retry_enabled(self):
        for mode in ("force-auto", "advisor"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                op=PythonAutoOperator.__new__(PythonAutoOperator)
                op.args=argparse.Namespace(mode=mode, ranked_loop=True, max_iterations=1, poll=.001,
                                            stop_on_error=False, board_metadata=False)
                op.layout={"viewport":{"width":1920,"height":1080}, "drawSlot":{"x":1486,"y":921,"width":92,"height":151}}
                op.frames=Path(directory);op.screen_references={};op.latest_screencast_frame=self.denied
                op.screencast_session=Mock() if mode=="force-auto" else None
                op.screencast_sequence=1;op.cached_public_observation=None
                op.log=Mock();op.ensure_viewport=Mock();op.start_screencast_gate=Mock()
                op.poll_public_recognition=Mock();op.capture_self_win_result=Mock(return_value=False)
                op.guard_black_recovery_outcome=Mock(return_value=False)
                op.observe_ranked_match_screen=Mock();op.schedule_periodic_public_recognition=Mock()
                page=Mock();page.url="https://game.mahjongsoul.com/index.html";page.screenshot.return_value=self.denied
                with self.assertRaisesRegex(RuntimeError,"rank_entry_denied"):
                    op.run(page)
                self.assertEqual(len(list(Path(directory).glob("*.rank-entry-denied.png"))),1)
                events=[call.args[0] for call in op.log.call_args_list]
                self.assertIn("blocking_dialog_stop",events);self.assertIn("safety_stop",events)
                page.mouse.click.assert_not_called()
