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
    def test_operator_restores_and_verifies_cdp_viewport(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.log = Mock()
        page = Mock()
        page.evaluate.side_effect = [
            {"width": 630, "height": 84},
            {"width": 1920, "height": 1080},
        ]

        operator.ensure_viewport(page)

        page.set_viewport_size.assert_called_once_with({"width": 1920, "height": 1080})
        operator.log.assert_called_once_with(
            "viewport_restored",
            previous={"width": 630, "height": 84},
            viewport={"width": 1920, "height": 1080},
        )

    def test_operator_leaves_matching_viewport_unchanged(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        page = Mock()
        page.evaluate.return_value = {"width": 1920, "height": 1080}

        operator.ensure_viewport(page)

        page.set_viewport_size.assert_not_called()

    def test_operator_force_sets_matching_viewport_after_cdp_attach(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.log = Mock()
        page = Mock()
        page.evaluate.side_effect = [
            {"width": 1920, "height": 1080},
            {"width": 1920, "height": 1080},
        ]

        operator.ensure_viewport(page, force=True)

        page.set_viewport_size.assert_called_once_with({"width": 1920, "height": 1080})
        page.wait_for_timeout.assert_called_once_with(250)
        operator.log.assert_not_called()

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

    def test_all_reaction_prompt_variants_use_the_certified_pass(self) -> None:
        for offered in (["chi", "pass"], ["pon", "pass"], ["kan", "pass"],
                        ["ron", "pass"], ["chi", "pon", "kan", "pass"]):
            with self.subTest(offered=offered):
                operator = PythonAutoOperator.__new__(PythonAutoOperator)
                operator.args = argparse.Namespace(mode="auto", stability_pixel_delta=1.5)
                operator.layout = {
                    "actionButtonRegions": {"pass": {"x": 10, "y": 20, "width": 100, "height": 40}},
                    "actionOperation": {"pass": {
                        "enabled": True, "templateSetFingerprint": "buttons-v1",
                    }},
                }
                operator.log = Mock()
                operator.confirm_action_button = Mock(return_value={"confirmation": "action_button_region_changed"})
                page = Mock()
                page.screenshot.return_value = Image.new("RGB", (100, 40), "black")
                buffer = io.BytesIO()
                page.screenshot.return_value.save(buffer, format="PNG")
                page.screenshot.return_value = buffer.getvalue()
                evaluation = {
                    "status": "reaction_prompt",
                    "recognition": {"safe": True, "tiles": ["1m"] * 13},
                    "availableUiActions": offered,
                    "actionButton": {"action": "pass", "present": True, "confidence": 0.99,
                                     "templateSetFingerprint": "buttons-v1", "center": {"x": 60, "y": 40}},
                }
                receipt = operator.execute_reaction_pass(page, evaluation)
                self.assertEqual(receipt["action"], "pass")
                page.mouse.click.assert_called_once_with(60, 40)

    def test_reaction_prompt_never_clicks_without_auto_and_certificate(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="advisor")
        evaluation = {"recognition": {"safe": True, "tiles": ["1m"] * 13}}
        self.assertFalse(operator.execute_reaction_pass(Mock(), evaluation)["clicked"])

    def test_force_auto_reaction_ignores_confidence_and_certificate(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", stability_pixel_delta=1.5)
        operator.layout = {"actionButtonRegions": {"pass": {"x": 10, "y": 20, "width": 100, "height": 40}}}
        operator.log = Mock()
        operator.confirm_action_button = Mock(return_value={"confirmation": "action_button_region_changed"})
        page = Mock()
        buffer = io.BytesIO()
        Image.new("RGB", (100, 40), "black").save(buffer, format="PNG")
        page.screenshot.return_value = buffer.getvalue()
        evaluation = {
            "recognition": {"safe": False, "tiles": ["1m"] * 13},
            "availableUiActions": ["chi", "pass"],
            "actionButton": {"action": "pass", "present": True, "confidence": 0.2,
                             "center": {"x": 60, "y": 40}},
        }
        receipt = operator.execute_reaction_pass(page, evaluation)
        self.assertEqual(receipt["policy"], "force_auto")
        page.mouse.click.assert_called_once_with(60, 40)

    def test_pending_discard_requires_one_exact_opponent_river_append(self) -> None:
        previous = {"opponentDiscards": [
            {"seat": "east", "discards": ["1m"]},
            {"seat": "west", "discards": ["2p"]},
        ]}
        current = {"opponentDiscards": [
            {"seat": "east", "discards": ["1m", "5s"]},
            {"seat": "west", "discards": ["2p"]},
        ]}
        self.assertEqual(PythonAutoOperator.infer_pending_discard(previous, current),
                         {"tile": "5s", "fromSeat": "east"})
        current["opponentDiscards"][1]["discards"].append("3p")
        self.assertIsNone(PythonAutoOperator.infer_pending_discard(previous, current))
        current["opponentDiscards"][0]["discards"] = ["9m", "5s"]
        current["opponentDiscards"][1]["discards"] = ["2p"]
        self.assertIsNone(PythonAutoOperator.infer_pending_discard(previous, current))

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
