import io
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

import argparse
import tempfile
import json
from unittest.mock import Mock, patch

from auto_operator import PythonAutoOperator, away_resume_geometry, is_away_resume_dialog, load_json, load_secret_environment, local_discard_allowed, send_discard_click
from screen_state import classify_screen, load_references


class RecordingMouse:
    def __init__(self) -> None:
        self.calls = []

    def click(self, x, y, **kwargs) -> None:
        self.calls.append((x, y, kwargs))

    def move(self, x, y) -> None:
        self.calls.append(("move", x, y))


class AwayDialogDetectionTest(unittest.TestCase):
    def test_replay_records_execution_and_receives_round_and_match_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.replays = Path(directory) / "replays"
            operator.replays.mkdir()
            operator.frames = Path(directory) / "frames"
            operator.frames.mkdir()
            operator.log_path = Path(directory) / "operator.jsonl"
            operator.pending_round_replays = []
            operator.pending_match_replays = []
            screenshot = operator.frames / "decision.png"
            screenshot.write_bytes(b"decision")
            evaluation = {
                "state": {"round": "east_1"},
                "recognition": {"backend": "template", "tiles": ["1m"], "confidence": 1,
                                "ambiguityMargin": 1, "safe": True},
                "decision": {"selectedActionId": "discard_1m", "recommendedAction": "discard"},
            }
            replay = operator.record_replay(evaluation, screenshot, execution={
                "clicked": True,
                "confirmation": "hand_and_own_river_changed",
                "tileMultisetVerification": {"verified": True},
            })
            self.assertEqual(load_json(replay)["executionEvidence"]["status"], "verified")

            self.assertEqual(operator.attach_outcome("round", b"round", 0.99), 1)
            self.assertEqual(operator.attach_outcome("match", b"match", 0.98), 1)
            result = load_json(replay)["actualResult"]
            self.assertEqual(result["round"]["screenState"], "round_result")
            self.assertEqual(result["match"]["screenState"], "match_result")
            jsonl_record = json.loads((operator.replays / "decisions.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(jsonl_record["actualResult"]["round"]["screenState"], "round_result")
            self.assertEqual(jsonl_record["actualResult"]["match"]["screenState"], "match_result")
            self.assertEqual(operator.attach_outcome("round", b"duplicate", 1), 0)

    def test_fresh_recognition_disagreement_prevents_click(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(mode="auto", allow_local_discard=False,
                consensus_frames=3, stability_ms=10, evaluation_timeout=30)
            operator.frames = Path(directory)
            operator.root = Path(directory)
            operator.layout_path = Path(directory) / "layout.json"
            operator.templates = Path(directory) / "templates"
            operator.evaluator_env = {}
            page = Mock()
            page.screenshot.return_value = b"image"
            evaluation = {"decision": {"executable": True}, "recognition": {"tiles": ["1m"], "safe": True}}
            for fresh in ({"safe": True, "tiles": ["2m"]}, {"safe": False, "tiles": ["1m"]}):
                with patch("auto_operator.subprocess.run", return_value=argparse.Namespace(returncode=0, stdout=json.dumps(fresh))):
                    with self.assertRaisesRegex(RuntimeError, "disagrees"):
                        operator.execute(page, evaluation)
                page.mouse.click.assert_not_called()

    def test_private_env_loader_passes_only_jev_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.local"
            path.write_text("TYPESAFE_API_KEY=test-secret\nIGNORED=value\nJEV_MODEL=test-model\n", encoding="utf-8")
            path.chmod(0o600)
            environment = load_secret_environment(Path(directory), ".env.local")
            self.assertEqual(environment["TYPESAFE_API_KEY"], "test-secret")
            self.assertEqual(environment["JEV_MODEL"], "test-model")
            self.assertNotIn("IGNORED", environment)

    def test_env_loader_rejects_group_readable_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.local"
            path.write_text("TYPESAFE_API_KEY=test-secret\n", encoding="utf-8")
            path.chmod(0o640)
            with patch("auto_operator.sys.platform", "linux"):
                with self.assertRaisesRegex(RuntimeError, "group/world"):
                    load_secret_environment(Path(directory), ".env.local")

    def test_env_loader_uses_acl_managed_secret_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.local"
            path.write_text("TYPESAFE_API_KEY=test-secret\n", encoding="utf-8")
            with patch("auto_operator.sys.platform", "win32"):
                environment = load_secret_environment(Path(directory), ".env.local")
            self.assertEqual(environment["TYPESAFE_API_KEY"], "test-secret")

    def test_detects_dark_popup_with_gold_resume_button(self) -> None:
        viewport = {"width": 1920, "height": 1080}
        image = Image.new("RGB", (1920, 1080), (20, 40, 70))
        button, popup = away_resume_geometry(viewport)
        draw = ImageDraw.Draw(image)
        draw.rectangle((popup["x"], popup["y"], popup["x"] + popup["width"], popup["y"] + popup["height"]), fill=(40, 45, 60))
        draw.rectangle((button["x"], button["y"], button["x"] + button["width"], button["y"] + button["height"]), fill=(230, 190, 90))
        output = io.BytesIO()
        image.save(output, format="PNG")
        self.assertTrue(is_away_resume_dialog(output.getvalue(), viewport))

    def test_rejects_normal_dark_table_without_gold_button(self) -> None:
        viewport = {"width": 1920, "height": 1080}
        image = Image.new("RGB", (1920, 1080), (20, 40, 70))
        output = io.BytesIO()
        image.save(output, format="PNG")
        self.assertFalse(is_away_resume_dialog(output.getvalue(), viewport))

    def test_local_discard_requires_explicit_flag_and_safe_discard(self) -> None:
        evaluation = {"decision": {"recommendedAction": "discard", "confidence": 0.55, "safety": {"allowed": True}}}
        self.assertTrue(local_discard_allowed(argparse.Namespace(allow_local_discard=True, mode="advisor"), evaluation))
        self.assertFalse(local_discard_allowed(argparse.Namespace(allow_local_discard=False, mode="advisor"), evaluation))
        evaluation["decision"]["safety"]["allowed"] = False
        self.assertFalse(local_discard_allowed(argparse.Namespace(allow_local_discard=True, mode="advisor"), evaluation))

    def test_discard_selects_and_confirms_the_same_guarded_coordinate(self) -> None:
        mouse = RecordingMouse()
        send_discard_click(mouse, {"x": 933, "y": 996.5}, {"width": 1920, "height": 1080})
        self.assertEqual(mouse.calls, [
            (933, 996.5, {"click_count": 2, "delay": 80}),
            ("move", 960, 777.6),
        ])

    def test_saved_screens_are_classified_and_unknown_fails_closed(self) -> None:
        expected_files = {
            "login": "result-step-1.png",
            "account_modal": "login-step-1.png",
            "lobby": "lobby-ready.png",
            "ranked_menu": "ranked-menu.png",
            "ranked_room": "ranked-copper.png",
            "matchmaking": "ranked-matchmaking.png",
            "match": "login-step-3.png",
            "away": "away-dialog.png",
            "round_result": "round-result.png",
            "match_result": "match-result.png",
            "exit_confirm": "exit-dialog.png",
        }
        with tempfile.TemporaryDirectory() as directory:
            reference_dir = Path(directory)
            for index, filename in enumerate(expected_files.values(), start=1):
                Image.new("RGB", (64, 36), (index * 17 % 255, index * 31 % 255, index * 47 % 255)).save(reference_dir / filename)
            references = load_references(reference_dir)
            for expected, filename in expected_files.items():
                self.assertEqual(classify_screen(reference_dir / filename, references), (expected, 1))
            blank = io.BytesIO()
            Image.new("RGB", (1920, 1080), "white").save(blank, format="PNG")
            self.assertEqual(classify_screen(blank.getvalue(), references), ("unknown", 0.0))


if __name__ == "__main__":
    unittest.main()
