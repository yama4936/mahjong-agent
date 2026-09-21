import io
import hashlib
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

import argparse
import tempfile
import json
import time
from unittest.mock import Mock, patch

from auto_operator import PythonAutoOperator, RetryableSafetyAbort, away_resume_geometry, closed_concealed_row_visible, crop_screenshot, discard_point_in_hand_geometry, force_auto_call_buttons, force_auto_reaction_win_button, force_auto_self_action_buttons, geometric_open_meld_count, is_away_resume_dialog, is_contextual_reaction_pass, is_draw_slot_occupied, is_force_auto_pass_prompt, load_json, load_secret_environment, local_discard_allowed, mean_pixel_delta, merge_public_observations, open_hand_draw_slot, own_meld_surface_visible, post_call_transition, send_discard_click, should_guard_tenpai_reaction, should_process_reaction_prompt, stable_hand_comparison_region, stable_hand_delta
from screen_state import classify_screen, load_references


class RecordingMouse:
    def __init__(self) -> None:
        self.calls = []

    def click(self, x, y, **kwargs) -> None:
        self.calls.append((x, y, kwargs))

    def move(self, x, y) -> None:
        self.calls.append(("move", x, y))


class AwayDialogDetectionTest(unittest.TestCase):
    def test_screencast_rejects_resized_frame_and_clears_stale_gate(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = {
            "viewport": {"width": 1920, "height": 1080},
            "drawSlot": {"x": 1600, "y": 900, "width": 100, "height": 100},
        }
        operator.latest_screencast_frame = b"stale calibrated frame"
        operator.screencast_sequence = 4
        operator.screencast_draw_occupied = True
        operator.screencast_draw_generation = 2
        operator.rejected_screencast_size = None
        operator.log = Mock()
        resized = io.BytesIO()
        Image.new("RGB", (1058, 1080), "white").save(resized, format="JPEG")

        self.assertFalse(operator.accept_screencast_frame(resized.getvalue()))

        self.assertIsNone(operator.latest_screencast_frame)
        self.assertIsNone(operator.screencast_draw_occupied)
        self.assertEqual(operator.screencast_draw_generation, 2)
        self.assertEqual(operator.screencast_sequence, 5)
        operator.log.assert_called_once_with(
            "screencast_frame_rejected", expected=[1920, 1080], actual=[1058, 1080],
        )

    def test_screencast_accepts_calibrated_frame_after_resize(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = {
            "viewport": {"width": 1920, "height": 1080},
            "drawSlot": {"x": 1600, "y": 900, "width": 100, "height": 100},
        }
        operator.latest_screencast_frame = None
        operator.screencast_sequence = 1
        operator.screencast_draw_occupied = None
        operator.screencast_draw_generation = 0
        operator.rejected_screencast_size = (1058, 1080)
        operator.log = Mock()
        calibrated = io.BytesIO()
        Image.new("RGB", (1920, 1080), "white").save(calibrated, format="JPEG")

        self.assertTrue(operator.accept_screencast_frame(calibrated.getvalue()))

        self.assertEqual(operator.latest_screencast_frame, calibrated.getvalue())
        self.assertTrue(operator.screencast_draw_occupied)
        self.assertEqual(operator.screencast_draw_generation, 1)
        self.assertIsNone(operator.rejected_screencast_size)

    def test_silent_screencast_is_seeded_from_exact_size_screenshot_once(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = {
            "viewport": {"width": 1920, "height": 1080},
            "drawSlot": {"x": 1600, "y": 900, "width": 100, "height": 100},
        }
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = None
        operator.screencast_sequence = 0
        operator.screencast_draw_occupied = None
        operator.screencast_draw_generation = 0
        operator.rejected_screencast_size = None
        operator.log = Mock()
        frame = io.BytesIO()
        Image.new("RGB", (1920, 1080), "white").save(frame, format="PNG")
        page = Mock()
        page.screenshot.return_value = frame.getvalue()

        self.assertTrue(operator.seed_silent_screencast_gate(page))
        self.assertFalse(operator.seed_silent_screencast_gate(page))

        self.assertEqual(operator.latest_screencast_frame, frame.getvalue())
        self.assertEqual(operator.screencast_sequence, 1)
        page.screenshot.assert_called_once_with(animations="disabled")
        operator.log.assert_called_once_with(
            "screencast_gate_seeded", source="one_shot_screenshot",
        )

    def test_real_stream_frame_wins_seed_race_without_duplicate_gate_event(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = None
        operator.screencast_sequence = 0
        operator.log = Mock()
        page = Mock()

        def stream_arrives(**_kwargs):
            operator.latest_screencast_frame = b"stream"
            operator.screencast_sequence = 1
            return b"screenshot"

        page.screenshot.side_effect = stream_arrives

        self.assertFalse(operator.seed_silent_screencast_gate(page))
        self.assertEqual(operator.latest_screencast_frame, b"stream")
        self.assertEqual(operator.screencast_sequence, 1)
        operator.log.assert_not_called()

    def test_stalled_stream_refreshes_to_captured_closed_hand_reaction_prompt(self) -> None:
        project = Path(__file__).resolve().parents[1]
        prompt = (project / "artifacts" / "debug-300-monitor.png").read_bytes()
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(stability_pixel_delta=1.5)
        operator.layout = load_json(project / "config" / "layout.json")
        operator.screencast_session = Mock()
        operator.screencast_sequence = 7
        stale = io.BytesIO()
        Image.new("RGB", (1920, 1080), (25, 55, 85)).save(stale, format="PNG")
        operator.latest_screencast_frame = stale.getvalue()
        operator.screencast_draw_occupied = False
        operator.screencast_draw_generation = 0
        operator.rejected_screencast_size = None
        operator.log = Mock()
        page = Mock()
        page.screenshot.return_value = prompt

        self.assertTrue(operator.refresh_silent_screencast_gate(page))

        pass_region = operator.layout["actionButtonRegions"]["pass"]
        calls = force_auto_call_buttons(operator.latest_screencast_frame, operator.layout["viewport"])
        self.assertTrue(calls)
        self.assertTrue(is_contextual_reaction_pass(
            operator.latest_screencast_frame, pass_region, len(calls),
        ))
        self.assertEqual(operator.screencast_sequence, 8)

    def test_run_loop_routes_existing_jpeg_prompt_immediately_after_startup(self) -> None:
        project = Path(__file__).resolve().parents[1]
        prompt_image = Image.open(project / "artifacts" / "debug-300-after-hash-fix.png").convert("RGB")
        prompt_buffer = io.BytesIO()
        prompt_image.save(prompt_buffer, format="JPEG", quality=55)
        prompt = prompt_buffer.getvalue()
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(
                mode="force-auto", max_iterations=2, poll=0.001,
                accept_single_call=False, action_templates="", stability_pixel_delta=1.5,
            )
            operator.layout = load_json(project / "config" / "layout.json")
            operator.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
            operator.action_clip = None
            operator.frames = Path(directory)
            operator.screen_references = {}
            operator.screencast_session = Mock()
            operator.latest_screencast_frame = prompt
            operator.screencast_sequence = 1
            operator.screencast_draw_occupied = False
            operator.screencast_draw_generation = 0
            operator.rejected_screencast_size = None
            operator.cached_public_observation = None
            operator.cached_concealed_tiles = None
            operator.cached_open_melds = 0
            operator.dynamic_layout_required = False
            operator.pending_post_call_discard = False
            operator.pending_post_call_started_at = None
            operator.restart_open_hand_probe_hash = None
            operator.open_meld_candidate = None
            operator.open_meld_candidate_frames = set()
            operator.last_processed_hand = None
            operator.armed = True
            operator.previous_public_observation = None
            operator.last_shanten = 1
            operator.poll_public_recognition = Mock()
            operator.ensure_viewport = Mock()
            operator.start_screencast_gate = Mock()
            operator.schedule_periodic_public_recognition = Mock()
            operator.resume_if_away = Mock(return_value=False)
            operator.advance_ranked_loop = Mock(return_value=False)
            operator.recognize_resident = Mock(return_value={"tiles": ["1m"] * 13})
            operator.execute_reaction_pass = Mock(return_value={"clicked": True, "action": "pass"})
            operator.log = Mock()
            page = Mock()
            page.url = "https://game.mahjongsoul.com/index.html"
            page.screenshot.return_value = prompt

            with patch("auto_operator.classify_screen", return_value=("match", 1.0)):
                operator.run(page)

            self.assertGreaterEqual(operator.execute_reaction_pass.call_count, 1)
            reaction = operator.execute_reaction_pass.call_args_list[0].args[1]
            self.assertEqual(reaction["status"], "reaction_prompt")
            self.assertEqual(reaction["actionButton"]["action"], "pass")
            self.assertTrue(any(
                call.args and call.args[0] == "reaction_gate_candidate"
                for call in operator.log.call_args_list
            ))

    def test_public_cache_only_grows_rivers_and_preserves_riichi(self) -> None:
        previous = {
            "doraIndicators": ["4m"], "ownDiscards": ["1p"], "ownRiichiDeclared": True,
            "ownMeldTiles": [], "ownMelds": [],
            "opponentDiscards": [
                {"seat": "south", "discards": ["E"], "riichiDeclared": True, "melds": []},
            ],
        }
        current = {
            "doraIndicators": [], "ownDiscards": ["1p", "2p"], "ownRiichiDeclared": False,
            "ownMeldTiles": [], "ownMelds": [],
            "opponentDiscards": [
                {"seat": "south", "discards": [], "riichiDeclared": False, "melds": []},
            ],
            "capturedAt": "now", "recognitionLatencyMs": 350,
            "handPlan": {"planId": "tanyao", "confidence": 0.7},
        }

        merged = merge_public_observations(previous, current)

        self.assertEqual(merged["doraIndicators"], ["4m"])
        self.assertEqual(merged["ownDiscards"], ["1p", "2p"])
        self.assertEqual(merged["opponentDiscards"][0]["discards"], ["E"])
        self.assertTrue(merged["opponentDiscards"][0]["riichiDeclared"])
        self.assertTrue(merged["ownRiichiDeclared"])
        self.assertEqual(merged["handPlan"]["planId"], "tanyao")

    def test_public_board_scan_runs_periodically_on_any_turn(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(public_cache=True, public_scan_interval=2.0)
        operator.public_recognition_server = Mock()
        operator.last_public_scan_at = 0.0
        operator.schedule_public_recognition = Mock()

        self.assertTrue(operator.schedule_periodic_public_recognition(b"first", now=10.0))
        self.assertFalse(operator.schedule_periodic_public_recognition(b"too-soon", now=11.9))
        self.assertTrue(operator.schedule_periodic_public_recognition(b"second", now=12.0))
        self.assertEqual(operator.schedule_public_recognition.call_count, 2)
        self.assertEqual(operator.schedule_public_recognition.call_args_list[0].args, (b"first",))
        self.assertEqual(operator.schedule_public_recognition.call_args_list[1].args, (b"second",))

    def test_draw_slot_presence_distinguishes_own_and_opponent_turns(self) -> None:
        region = {"x": 100, "y": 50, "width": 100, "height": 100}
        own_turn = io.BytesIO()
        image = Image.new("RGB", (300, 200), (25, 55, 85))
        ImageDraw.Draw(image).rectangle((100, 50, 200, 150), fill=(230, 225, 210))
        image.save(own_turn, format="PNG")
        self.assertTrue(is_draw_slot_occupied(own_turn.getvalue(), region))

        opponent_turn = io.BytesIO()
        Image.new("RGB", (300, 200), (25, 55, 85)).save(opponent_turn, format="PNG")
        self.assertFalse(is_draw_slot_occupied(opponent_turn.getvalue(), region))

    def test_open_hand_draw_slot_shifts_three_tile_pitches_per_meld(self) -> None:
        layout = {
            "viewport": {"width": 1920, "height": 1080},
            "handSlots": [
                {"x": 223, "y": 926, "width": 92, "height": 146},
                {"x": 318, "y": 926, "width": 92, "height": 146},
                {"x": 413, "y": 926, "width": 92, "height": 146},
            ],
            "drawSlot": {"x": 1486, "y": 926, "width": 92, "height": 146},
        }

        self.assertEqual(open_hand_draw_slot(layout, 1), {
            "x": 1201.0, "y": 926.0, "width": 92.0, "height": 146.0,
        })
        self.assertEqual(open_hand_draw_slot(layout, 2), {
            "x": 916.0, "y": 926.0, "width": 92.0, "height": 146.0,
        })
        self.assertIsNone(open_hand_draw_slot(layout, 0))

    def test_winning_animation_does_not_look_like_verified_new_round(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        frames = project / "artifacts" / "friend-5-20" / "frames"
        for name in (
            "2026-09-21T05-41-02.311448+00-00.jpg",
            "2026-09-21T05-41-03.461291+00-00.jpg",
            "2026-09-21T05-41-04.636486+00-00.jpg",
            "2026-09-21T05-41-06.397759+00-00.jpg",
            "2026-09-21T05-41-07.758711+00-00.jpg",
        ):
            self.assertFalse(closed_concealed_row_visible((frames / name).read_bytes(), layout), name)
        self.assertTrue(closed_concealed_row_visible(
            (frames / "2026-09-21T05-41-16.298972+00-00.jpg").read_bytes(), layout,
        ))

    def test_shifted_open_hand_draw_slot_does_not_match_empty_opponent_turn(self) -> None:
        region = {"x": 1201, "y": 926, "width": 92, "height": 146}
        own_turn = io.BytesIO()
        image = Image.new("RGB", (1920, 1080), (25, 55, 85))
        ImageDraw.Draw(image).rectangle((1201, 926, 1293, 1072), fill=(230, 225, 210))
        image.save(own_turn, format="PNG")
        self.assertTrue(is_draw_slot_occupied(own_turn.getvalue(), region))

        opponent_turn = io.BytesIO()
        Image.new("RGB", (1920, 1080), (25, 55, 85)).save(opponent_turn, format="PNG")
        self.assertFalse(is_draw_slot_occupied(opponent_turn.getvalue(), region))

    def test_live_compact_hand_geometry_recovers_unpromoted_own_meld(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        frame = (project / "artifacts" / "debug-300-live-now2.png").read_bytes()

        self.assertEqual(geometric_open_meld_count(frame, layout), 1)

    def test_restart_geometry_recovers_three_melds_despite_closed_slot_overlap(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        frames = project / "artifacts" / "friend-5-20" / "frames"
        for name in (
            "2026-09-21T05-46-30.872131+00-00.jpg",
            "2026-09-21T05-46-33.088404+00-00.jpg",
        ):
            self.assertEqual(geometric_open_meld_count((frames / name).read_bytes(), layout), 3)

    def test_closed_new_round_requires_two_frames_and_clears_prior_meld_evidence(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        frames = project / "artifacts" / "friend-5-20" / "frames"
        first = (frames / "2026-09-21T06-15-22.969232+00-00.jpg").read_bytes()
        second = (frames / "2026-09-21T06-15-24.317758+00-00.jpg").read_bytes()
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = layout
        operator.closed_new_round_candidate_frames = set()

        self.assertFalse(operator.stable_closed_new_round(first))
        self.assertTrue(operator.stable_closed_new_round(second))
        # An open hand in the same round must not satisfy the reset proof.
        open_frame = (frames / "2026-09-21T05-46-33.088404+00-00.jpg").read_bytes()
        self.assertFalse(operator.stable_closed_new_round(open_frame))

    def test_restart_after_call_has_stable_meld_surface_without_closed_round_proof(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        frames = project / "artifacts" / "friend-5-20" / "frames"
        first = (frames / "2026-09-21T06-21-57.847655+00-00.jpg").read_bytes()
        second = (frames / "2026-09-21T06-22-00.877593+00-00.jpg").read_bytes()
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = layout
        operator.cached_open_melds = 0
        operator.open_meld_candidate = None
        operator.open_meld_candidate_frames = set()

        started = time.monotonic()
        self.assertTrue(own_meld_surface_visible(first, layout))
        self.assertTrue(own_meld_surface_visible(second, layout))
        self.assertFalse(closed_concealed_row_visible(first, layout))
        compact_region = stable_hand_comparison_region(layout, 2)
        self.assertLess(mean_pixel_delta(
            crop_screenshot(first, compact_region), crop_screenshot(second, compact_region),
        ), 1.5)
        self.assertFalse(operator.stable_open_meld_count(2, first))
        self.assertEqual(operator.stable_open_meld_count(2, second), 2)
        self.assertTrue(discard_point_in_hand_geometry({"x": 838, "y": 996.5}, layout, 2))
        self.assertLess(time.monotonic() - started, 5.0)

    def test_run_loop_reaches_post_pon_next_draw_with_trusted_open_meld_count(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        frame = (project / "artifacts" / "debug-300-current5.png").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(mode="force-auto", max_iterations=2, poll=0.001)
            operator.layout = layout
            operator.hand_clip = {
                "x": 223, "y": 926, "width": 1355, "height": 146,
            }
            operator.action_clip = None
            operator.frames = Path(directory)
            operator.screen_references = {}
            operator.screencast_session = Mock()
            operator.latest_screencast_frame = frame
            operator.screencast_sequence = 1
            operator.screencast_draw_occupied = False
            operator.screencast_draw_generation = 0
            operator.cached_public_observation = None
            operator.cached_concealed_tiles = None
            operator.cached_open_melds = 1
            operator.dynamic_layout_required = False
            operator.pending_post_call_discard = False
            operator.pending_post_call_started_at = None
            operator.restart_open_hand_probe_hash = None
            operator.last_processed_hand = None
            operator.armed = True
            operator.previous_public_observation = None
            operator.last_shanten = None
            operator.poll_public_recognition = Mock()
            operator.ensure_viewport = Mock()
            operator.start_screencast_gate = Mock()
            operator.schedule_periodic_public_recognition = Mock()
            operator.resume_if_away = Mock(return_value=False)
            operator.advance_ranked_loop = Mock(return_value=False)
            operator.recognize_resident = Mock(return_value={"status": "not_ready"})
            operator.force_auto_reaction_fallback = Mock(return_value=None)
            operator.log = Mock()
            page = Mock()
            page.url = "https://mahjongsoul.game.yo-star.com/"

            with patch("auto_operator.classify_screen", return_value=("match", 1.0)):
                operator.run(page)

            operator.recognize_resident.assert_called_once()
            self.assertEqual(operator.recognize_resident.call_args.kwargs["open_melds"], 1)
            self.assertTrue(operator.dynamic_layout_required)
            self.assertEqual(operator.cached_open_melds, 1)
            self.assertTrue(any(
                call.args and call.args[0] == "open_hand_geometry_gate"
                for call in operator.log.call_args_list
            ))

    def test_restarted_run_loop_acts_after_two_live_three_meld_frames(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        frames = project / "artifacts" / "friend-5-20" / "frames"
        first = (frames / "2026-09-21T05-46-30.872131+00-00.jpg").read_bytes()
        second = (frames / "2026-09-21T05-46-33.088404+00-00.jpg").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(mode="force-auto", max_iterations=2, poll=0.001,
                                               stop_on_error=True)
            operator.layout = layout
            operator.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
            operator.action_clip = None
            operator.frames = Path(directory)
            operator.screen_references = {}
            operator.screencast_session = Mock()
            operator.latest_screencast_frame = second
            operator.screencast_sequence = 2
            operator.screencast_draw_occupied = False
            operator.screencast_draw_generation = 1
            operator.cached_public_observation = None
            operator.cached_concealed_tiles = None
            operator.cached_open_melds = 0
            operator.dynamic_layout_required = False
            operator.pending_post_call_discard = False
            operator.pending_post_call_started_at = None
            operator.restart_open_hand_probe_hash = None
            operator.open_meld_candidate = 3
            operator.open_meld_candidate_frames = {hashlib.sha256(first).hexdigest()}
            operator.last_processed_hand = None
            operator.armed = True
            operator.previous_public_observation = None
            operator.last_shanten = None
            operator.round_terminal_latched = False
            operator.poll_public_recognition = Mock()
            operator.ensure_viewport = Mock()
            operator.start_screencast_gate = Mock()
            operator.schedule_periodic_public_recognition = Mock()
            operator.resume_if_away = Mock(return_value=False)
            operator.advance_ranked_loop = Mock(return_value=False)
            operator.force_auto_reaction_fallback = Mock(return_value=None)
            operator.recognize_resident = Mock(return_value={
                "status": "decision", "openMelds": 3,
                "recognition": {"tiles": ["1p"] * 5},
                "decision": {"selectedAction": {"action": "discard", "tile": "1p"}},
                "clickIndex": 0,
            })
            operator.execute = Mock(return_value={
                "clicked": True, "confirmation": "hand_and_own_river_changed",
            })
            operator.record_replay = Mock(return_value=Path(directory) / "replay.json")
            operator.log = Mock()
            page = Mock()
            page.url = "https://mahjongsoul.game.yo-star.com/"

            started = time.monotonic()
            with patch("auto_operator.classify_screen", return_value=("match", 1.0)):
                operator.run(page)

            operator.execute.assert_called_once()
            self.assertEqual(operator.cached_open_melds, 3)
            self.assertLess(time.monotonic() - started, 5.0)

    def test_compact_geometry_rejects_opponent_turn_without_own_meld_surface(self) -> None:
        layout = {
            "viewport": {"width": 1920, "height": 1080},
            "handSlots": [
                {"x": 223 + index * 95, "y": 926, "width": 92, "height": 146}
                for index in range(13)
            ],
            "drawSlot": {"x": 1486, "y": 926, "width": 92, "height": 146},
        }
        frame = io.BytesIO()
        image = Image.new("RGB", (1920, 1080), (25, 55, 85))
        draw = ImageDraw.Draw(image)
        for slot in layout["handSlots"][:10]:
            draw.rectangle((
                slot["x"], slot["y"], slot["x"] + slot["width"], slot["y"] + slot["height"],
            ), fill=(230, 225, 210))
        image.save(frame, format="PNG")

        self.assertIsNone(geometric_open_meld_count(frame.getvalue(), layout))

    def test_force_auto_pass_prompt_requires_dark_button_and_warm_neutral_text(self) -> None:
        region = {"x": 100, "y": 50, "width": 200, "height": 80}
        image = Image.new("RGB", (400, 200), (25, 55, 85))
        draw = ImageDraw.Draw(image)
        draw.rectangle((100, 50, 300, 130), fill=(35, 40, 45))
        draw.rectangle((140, 75, 170, 90), fill=(180, 150, 70))
        draw.rectangle((190, 75, 250, 90), fill=(150, 145, 90))
        output = io.BytesIO()
        image.save(output, format="PNG")
        self.assertTrue(is_force_auto_pass_prompt(output.getvalue(), region))

        empty = io.BytesIO()
        Image.new("RGB", (400, 200), (25, 55, 85)).save(empty, format="PNG")
        self.assertFalse(is_force_auto_pass_prompt(empty.getvalue(), region))

    def test_force_auto_call_buttons_only_find_green_action_buttons(self) -> None:
        viewport = {"width": 1600, "height": 900}
        image = Image.new("RGB", (1600, 900), (25, 55, 85))
        draw = ImageDraw.Draw(image)
        draw.rectangle((893, 650, 1131, 743), fill=(45, 130, 70))
        output = io.BytesIO()
        image.save(output, format="PNG")
        buttons = force_auto_call_buttons(output.getvalue(), viewport)
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0]["action"], "chi")
        self.assertEqual(buttons[0]["center"], {"x": 1012.0, "y": 696.5})

        orange = Image.new("RGB", (1600, 900), (25, 55, 85))
        ImageDraw.Draw(orange).rectangle((893, 650, 1131, 743), fill=(190, 110, 35))
        output = io.BytesIO()
        orange.save(output, format="PNG")
        self.assertEqual(force_auto_call_buttons(output.getvalue(), viewport), [])

    def test_force_auto_call_buttons_keep_multiple_choices_ambiguous(self) -> None:
        viewport = {"width": 1600, "height": 900}
        image = Image.new("RGB", (1600, 900), (25, 55, 85))
        draw = ImageDraw.Draw(image)
        draw.rectangle((650, 650, 790, 743), fill=(45, 130, 70))
        draw.rectangle((850, 650, 990, 743), fill=(25, 145, 180))
        # Bamboo-colored pixels in the concealed-hand row must not merge with
        # the cyan pon button above them.
        draw.rectangle((870, 780, 930, 899), fill=(30, 120, 100))
        output = io.BytesIO()
        image.save(output, format="PNG")
        buttons = force_auto_call_buttons(output.getvalue(), viewport)
        self.assertEqual(len(buttons), 2)
        self.assertEqual([button["action"] for button in buttons], ["chi", "pon"])
        self.assertLess(max(button["height"] for button in buttons), 100)

    def test_tenpai_guard_allows_pass_when_a_green_call_is_visible(self) -> None:
        self.assertTrue(should_guard_tenpai_reaction(0, []))
        self.assertFalse(should_guard_tenpai_reaction(0, [{"center": {"x": 100, "y": 100}}]))
        self.assertFalse(should_guard_tenpai_reaction(1, []))

    def test_force_auto_self_action_button_finds_visible_riichi_colored_button(self) -> None:
        viewport = {"width": 1600, "height": 900}
        image = Image.new("RGB", (1600, 900), (25, 55, 85))
        ImageDraw.Draw(image).rectangle((893, 700, 1131, 780), fill=(190, 110, 35))
        output = io.BytesIO()
        image.save(output, format="PNG")
        buttons = force_auto_self_action_buttons(output.getvalue(), viewport)
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0]["center"], {"x": 1012.0, "y": 740.0})

    def test_force_auto_reaction_win_requires_pass_and_one_orange_button(self) -> None:
        viewport = {"width": 1600, "height": 900}
        pass_region = {"x": 1170, "y": 650, "width": 275, "height": 105}
        image = Image.new("RGB", (1600, 900), (25, 55, 85))
        draw = ImageDraw.Draw(image)
        draw.rectangle((850, 650, 1050, 743), fill=(190, 90, 35))
        draw.rectangle((1170, 650, 1445, 755), fill=(35, 40, 45))
        draw.rectangle((1210, 675, 1240, 690), fill=(180, 150, 70))
        draw.rectangle((1260, 675, 1320, 690), fill=(150, 145, 90))
        output = io.BytesIO()
        image.save(output, format="PNG")
        button = force_auto_reaction_win_button(output.getvalue(), viewport, pass_region)
        self.assertIsNotNone(button)
        self.assertEqual(button["center"], {"x": 950.0, "y": 696.5})

    def test_single_call_arms_compact_hand_discard_after_button_disappears(self) -> None:
        viewport = {"width": 1600, "height": 900}
        prompt = Image.new("RGB", (1600, 900), (25, 55, 85))
        ImageDraw.Draw(prompt).rectangle((893, 650, 1131, 743), fill=(45, 130, 70))
        ImageDraw.Draw(prompt).rectangle((100, 780, 700, 899), fill=(230, 225, 210))
        ImageDraw.Draw(prompt).rectangle((20, 700, 180, 770), fill=(25, 55, 85))
        prompt_bytes = io.BytesIO()
        prompt.save(prompt_bytes, format="PNG")
        table_bytes = io.BytesIO()
        table = Image.new("RGB", (1600, 900), (25, 55, 85))
        ImageDraw.Draw(table).rectangle((100, 780, 500, 899), fill=(230, 225, 210))
        ImageDraw.Draw(table).rectangle((20, 700, 180, 770), fill=(230, 225, 210))
        # A completed meld can still contain enough cyan/green pixels to look
        # like an action button. Visual hand+meld change remains authoritative.
        ImageDraw.Draw(table).rectangle((900, 650, 1080, 743), fill=(25, 145, 180))
        table.save(table_bytes, format="PNG")
        button = force_auto_call_buttons(prompt_bytes.getvalue(), viewport)[0]

        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(
            mode="force-auto", accept_single_call=True, confirmation_timeout=1, action_pixel_delta=3,
        )
        operator.layout = {"viewport": viewport, "publicTileRegions": {
            "ownMelds": {"x": 20, "y": 700, "width": 160, "height": 70},
        }}
        operator.hand_clip = {"x": 100, "y": 780, "width": 600, "height": 120}
        operator.screencast_sequence = 0
        operator.latest_screencast_frame = None
        operator.cached_concealed_tiles = ["1m"] * 13
        operator.cached_open_melds = 1
        operator.dynamic_layout_required = False
        operator.pending_post_call_discard = False
        operator.last_processed_hand = "old"
        operator.armed = False
        operator.log = Mock()
        page = Mock()
        page.screenshot.return_value = table_bytes.getvalue()

        receipt = operator.execute_force_auto_call(page, prompt_bytes.getvalue(), button)

        self.assertEqual(receipt["confirmation"], "hand_and_own_meld_changed")
        self.assertEqual(receipt["action"], "chi")
        self.assertEqual(receipt["nextAction"], "discard")
        self.assertEqual(operator.cached_open_melds, 2)
        self.assertTrue(operator.pending_post_call_discard)
        self.assertIsNotNone(operator.pending_post_call_started_at)
        self.assertTrue(operator.dynamic_layout_required)
        self.assertTrue(operator.armed)
        page.mouse.click.assert_called_once_with(1012.0, 696.5)

    def test_post_call_transition_distinguishes_discard_and_rinshan_draw(self) -> None:
        self.assertEqual(post_call_transition("pon", 1), {
            "openMelds": 2, "dynamicLayoutRequired": True, "pendingPostCallDiscard": True,
        })
        self.assertEqual(post_call_transition("minkan", 2), {
            "openMelds": 3, "dynamicLayoutRequired": True, "pendingPostCallDiscard": False,
        })
        self.assertFalse(should_process_reaction_prompt(True))
        self.assertTrue(should_process_reaction_prompt(False))

    def test_restart_accepts_compact_hand_with_complete_visible_meld(self) -> None:
        observation = {
            "ownMelds": [{
                "type": "pon", "tiles": ["5p", "5p", "5p"], "confidence": 0.93,
            }],
            "ownMeldTiles": ["5p", "5p", "5p"],
        }

        self.assertEqual(
            PythonAutoOperator.verified_visible_open_meld_count(1, observation), 1,
        )
        self.assertTrue(PythonAutoOperator.compact_hand_is_proven(1, False, observation))

    def test_restart_rejects_compact_hand_with_incomplete_or_ambiguous_meld(self) -> None:
        incomplete = {
            "ownMelds": [],
            "ownMeldTiles": ["5p", "5p", "5p"],
        }
        unexplained_tile = {
            "ownMelds": [{
                "type": "pon", "tiles": ["5p", "5p", "5p"], "confidence": 0.93,
            }],
            "ownMeldTiles": ["5p", "5p", "5p", "7s"],
        }

        for observation in (None, incomplete, unexplained_tile):
            with self.subTest(observation=observation):
                self.assertIsNone(
                    PythonAutoOperator.verified_visible_open_meld_count(1, observation),
                )
                self.assertFalse(PythonAutoOperator.compact_hand_is_proven(1, False, observation))

    def test_restart_open_discard_gate_accepts_only_self_turn_tile_count(self) -> None:
        observation = {
            "ownMelds": [{
                "type": "pon", "tiles": ["5p", "5p", "5p"], "confidence": 0.93,
            }],
            "ownMeldTiles": ["5p", "5p", "5p"],
        }

        self.assertEqual(
            PythonAutoOperator.restart_open_discard_meld_count(11, observation), 1,
        )
        # Ten concealed tiles is the stable post-discard/opponent-turn state.
        self.assertIsNone(
            PythonAutoOperator.restart_open_discard_meld_count(10, observation),
        )

    def test_restart_open_discard_gate_rejects_incomplete_meld_evidence(self) -> None:
        observation = {
            "ownMelds": [],
            "ownMeldTiles": ["5p", "5p", "5p"],
        }

        self.assertIsNone(
            PythonAutoOperator.restart_open_discard_meld_count(11, observation),
        )

    def test_force_auto_reaction_fallback_requires_thirteen_concealed_tiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(mode="force-auto", action_templates="", evaluation_timeout=30)
            operator.root = Path(directory)
            operator.layout_path = Path(directory) / "layout.json"
            operator.templates = Path(directory) / "templates"
            operator.evaluator_env = {}
            operator.layout = {"actionButtonRegions": {"pass": {"x": 100, "y": 50, "width": 200, "height": 80}}}
            image = Image.new("RGB", (400, 200), (25, 55, 85))
            draw = ImageDraw.Draw(image)
            draw.rectangle((100, 50, 300, 130), fill=(35, 40, 45))
            draw.rectangle((140, 75, 170, 90), fill=(180, 150, 70))
            draw.rectangle((190, 75, 250, 90), fill=(150, 145, 90))
            screenshot = Path(directory) / "reaction.png"
            image.save(screenshot)
            operator.recognize_resident = Mock(return_value={"tiles": ["1m"] * 13})
            result = operator.force_auto_reaction_fallback(screenshot)

            self.assertEqual(result["status"], "reaction_prompt")
            self.assertEqual(result["actionButton"]["center"], {"x": 200.0, "y": 90.0})
            operator.recognize_resident.assert_called_once_with(screenshot, concealed_only=True)

    def test_live_open_hand_chi_skip_prompt_uses_contextual_reaction_gate(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frame = (project / "artifacts" / "debug-300-current-end.png").read_bytes()
        layout = load_json(project / "config" / "layout.json")
        pass_region = layout["actionButtonRegions"]["pass"]
        calls = force_auto_call_buttons(frame, layout["viewport"])

        self.assertTrue(calls)
        self.assertFalse(is_force_auto_pass_prompt(frame, pass_region))
        self.assertTrue(is_contextual_reaction_pass(frame, pass_region, len(calls)))
        self.assertFalse(is_contextual_reaction_pass(frame, pass_region, 0))

    def test_contextual_open_hand_pass_accepts_compact_concealed_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(mode="force-auto", action_templates="")
            operator.layout = {"actionButtonRegions": {
                "pass": {"x": 100, "y": 50, "width": 200, "height": 80},
            }}
            operator.cached_open_melds = 1
            operator.recognize_resident = Mock(return_value={"tiles": ["1m"] * 10})
            screenshot = Path(directory) / "prompt.png"
            Image.new("RGB", (400, 200), "navy").save(screenshot)

            result = operator.force_auto_reaction_fallback(
                screenshot, contextual_prompt_verified=True,
            )

            self.assertEqual(result["status"], "reaction_prompt")
            self.assertEqual(result["actionButton"]["action"], "pass")

    def test_force_auto_post_discard_verifier_keeps_exact_multiset_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.frames = Path(directory)
            operator.root = Path(directory)
            operator.layout_path = Path(directory) / "layout.json"
            operator.templates = Path(directory) / "templates"
            operator.evaluator_env = {}
            operator.args = argparse.Namespace(mode="force-auto", evaluation_timeout=30)
            completed = argparse.Namespace(returncode=0, stdout=json.dumps({
                "verified": True,
                "force": True,
                "expected": ["1m"] * 13,
                "actual": ["1m"] * 13,
            }), stderr="")

            with patch("auto_operator.subprocess.run", return_value=completed) as run:
                result = operator.verify_post_discard(b"png", ["1m"] * 14, 0)

            self.assertTrue(result["verified"])
            self.assertIn("--force", run.call_args.args[0])

    def test_force_auto_confirmation_uses_visual_change_without_repeating_recognition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            operator = PythonAutoOperator.__new__(PythonAutoOperator)
            operator.args = argparse.Namespace(
                mode="force-auto", confirmation_timeout=1,
                action_pixel_delta=1, river_pixel_delta=1,
            )
            operator.frames = Path(directory)
            operator.hand_clip = {"x": 0, "y": 0, "width": 10, "height": 10}
            operator.river_clip = {"x": 10, "y": 0, "width": 10, "height": 10}
            operator.verify_post_discard = Mock(side_effect=AssertionError("must not re-recognize"))
            black = io.BytesIO()
            Image.new("RGB", (10, 10), "black").save(black, format="PNG")
            white = io.BytesIO()
            Image.new("RGB", (10, 10), "white").save(white, format="PNG")
            full = io.BytesIO()
            Image.new("RGB", (20, 10), "navy").save(full, format="PNG")
            page = Mock()
            page.screenshot.side_effect = lambda **kwargs: white.getvalue() if kwargs.get("clip") else full.getvalue()

            receipt = operator.confirm_discard(
                page, black.getvalue(), black.getvalue(), ["1m"] * 14, 0,
            )

            self.assertEqual(receipt["confirmation"], "hand_and_own_river_changed")
            self.assertTrue(Path(receipt["screenshot"]).exists())
            operator.verify_post_discard.assert_not_called()

    def test_terminal_reveal_waits_for_result_instead_of_rejecting_empty_slots(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(
            confirmation_timeout=0.1, terminal_transition_timeout=1,
            action_pixel_delta=1, river_pixel_delta=1,
        )
        operator.hand_clip = {"x": 0, "y": 0, "width": 10, "height": 10}
        operator.river_clip = {"x": 10, "y": 0, "width": 10, "height": 10}
        operator.screen_references = {}
        operator.verify_post_discard = Mock(return_value={"verified": False, "actual": []})
        operator.log = Mock()
        black = io.BytesIO()
        Image.new("RGB", (10, 10), "black").save(black, format="PNG")
        changed = io.BytesIO()
        Image.new("RGB", (10, 10), "white").save(changed, format="PNG")
        result_image = Image.new("RGB", (1920, 1080), (25, 55, 85))
        draw = ImageDraw.Draw(result_image)
        draw.rectangle((1650, 950, 1849, 1045), fill=(35, 40, 45))
        draw.rectangle((1650, 950, 1749, 1045), fill=(55, 70, 115))
        draw.rectangle((1680, 975, 1780, 1005), fill=(190, 165, 100))
        terminal = io.BytesIO()
        result_image.save(terminal, format="PNG")
        page = Mock()
        page.screenshot.side_effect = lambda **kwargs: (
            changed.getvalue() if kwargs.get("clip") else terminal.getvalue()
        )

        receipt = operator.confirm_discard(
            page, black.getvalue(), black.getvalue(), ["1m"] * 14, 0,
        )

        self.assertEqual(receipt["confirmation"], "discard_followed_by_terminal_result")
        self.assertEqual(receipt["terminalScreenState"], "round_result")
        operator.log.assert_called_once_with("terminal_transition_wait", verification={"verified": False, "actual": []})

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

    def test_operator_restarts_screencast_after_viewport_restore(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        operator.log = Mock()
        operator.screencast_session = Mock()
        operator.restart_screencast_gate = Mock()
        page = Mock()
        page.evaluate.side_effect = [
            {"width": 1920, "height": 1119},
            {"width": 1920, "height": 1080},
        ]

        operator.ensure_viewport(page)

        operator.restart_screencast_gate.assert_called_once_with(page)

    def test_restart_screencast_replaces_silent_subscription(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        old_session = Mock()
        operator.screencast_session = old_session
        operator.latest_screencast_frame = b"stale"
        operator.screencast_draw_occupied = True
        operator.start_screencast_gate = Mock()
        page = Mock()

        operator.restart_screencast_gate(page)

        old_session.send.assert_called_once_with("Page.stopScreencast")
        old_session.detach.assert_called_once_with()
        self.assertIsNone(operator.screencast_session)
        self.assertIsNone(operator.latest_screencast_frame)
        self.assertIsNone(operator.screencast_draw_occupied)
        operator.start_screencast_gate.assert_called_once_with(page)

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

    def test_force_auto_rejects_a_hand_that_changed_since_evaluation_without_rerecognition(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(
            mode="force-auto", allow_local_discard=False, consensus_frames=3,
            stability_ms=10, stability_pixel_delta=1.5, evaluation_timeout=30,
        )
        operator.hand_clip = {"x": 0, "y": 0, "width": 10, "height": 10}
        operator.layout = {
            "clickPoints": [{"x": 5, "y": 5}] * 14,
            "viewport": {"width": 1920, "height": 1080},
        }
        black = io.BytesIO()
        white = io.BytesIO()
        full = io.BytesIO()
        Image.new("RGB", (10, 10), "black").save(black, format="PNG")
        Image.new("RGB", (10, 10), "white").save(white, format="PNG")
        Image.new("RGB", (1920, 1080), "white").save(full, format="PNG")
        page = Mock()
        page.screenshot.side_effect = lambda **kwargs: white.getvalue() if kwargs.get("clip") else full.getvalue()
        evaluation = {
            "decision": {"executable": True, "selectedAction": {"action": "discard", "tile": "1m"}},
            "recognition": {"tiles": ["1m"] * 14, "safe": False},
            "clickIndex": 0,
        }

        with patch("auto_operator.subprocess.run") as run:
            with self.assertRaisesRegex(RuntimeError, "changed since evaluation"):
                operator.execute(page, evaluation, evaluated_hand=black.getvalue())

        run.assert_not_called()
        page.mouse.click.assert_not_called()

    def test_live_open_hand_stream_reaches_discard_receipt_with_equivalent_capture(self) -> None:
        project = Path(__file__).resolve().parents[1]
        source = Image.open(project / "artifacts" / "debug-300-live-now2.png").convert("RGB")
        encoded = io.BytesIO()
        source.save(encoded, format="JPEG", quality=55)
        streamed_full = encoded.getvalue()
        hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        evaluated_hand = crop_screenshot(streamed_full, hand_clip)

        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(
            mode="force-auto", allow_local_discard=False,
            stability_pixel_delta=1.5,
        )
        operator.hand_clip = hand_clip
        operator.river_clip = {"x": 740, "y": 520, "width": 430, "height": 300}
        operator.layout = load_json(project / "config" / "layout.json")
        operator.cached_open_melds = 1
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = streamed_full
        operator.screencast_draw_generation = 4
        operator.log = Mock()
        operator.confirm_discard = Mock(return_value={
            "confirmation": "hand_and_own_river_changed",
            "tileMultisetVerification": {"verified": True},
        })
        page = Mock()
        evaluation = {
            "decision": {
                "selectedAction": {"action": "discard", "tile": "3s"},
            },
            "recognition": {"tiles": ["4m", "1p", "2p", "3p", "4p", "5p",
                                      "6p", "7p", "8s", "8s", "3s"], "safe": True},
            "clickIndex": 10,
            "clickPoint": {"x": 1247, "y": 999},
            "openMelds": 1,
        }

        receipt = operator.execute(
            page, evaluation,
            evaluated_hand=evaluated_hand,
            evaluated_full=streamed_full,
            evaluated_draw_generation=4,
        )

        self.assertTrue(receipt["clicked"])
        self.assertEqual(receipt["confirmation"], "hand_and_own_river_changed")
        self.assertTrue(receipt["tileMultisetVerification"]["verified"])
        operator.confirm_discard.assert_called_once()
        page.mouse.click.assert_called_once_with(1247, 999, click_count=2, delay=80)

    def test_post_pon_animation_uses_stable_tile_faces_and_discards_within_clock(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frames = project / "artifacts" / "friend-5-20" / "frames"
        evaluated_full = (frames / "2026-09-21T06-08-02.365938+00-00.jpg").read_bytes()
        current_full = (frames / "2026-09-21T06-08-04.655959+00-00.jpg").read_bytes()
        layout = load_json(project / "config" / "layout.json")
        hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        stable_region = stable_hand_comparison_region(layout, 1)
        self.assertIsNotNone(stable_region)
        self.assertGreater(
            mean_pixel_delta(crop_screenshot(evaluated_full, hand_clip),
                             crop_screenshot(current_full, hand_clip)),
            5.0,
        )
        self.assertLess(
            mean_pixel_delta(crop_screenshot(evaluated_full, stable_region),
                             crop_screenshot(current_full, stable_region)),
            1.5,
        )
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = layout
        operator.hand_clip = hand_clip
        operator.river_clip = {"x": 740, "y": 520, "width": 430, "height": 300}
        operator.cached_open_melds = 1
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = current_full
        operator.screencast_draw_generation = 7
        operator.log = Mock()
        operator.confirm_discard = Mock(return_value={"confirmation": "hand_and_own_river_changed"})
        page = Mock()
        evaluation = {
            "decision": {"selectedAction": {"action": "discard", "tile": "C"}},
            "recognition": {"tiles": ["1m"] * 10 + ["C"], "safe": False},
            "clickIndex": 10,
            "clickPoint": {"x": 1217.5, "y": 996.5},
            "openMelds": 1,
        }

        started = time.monotonic()
        receipt = operator.execute(
            page, evaluation,
            evaluated_hand=crop_screenshot(evaluated_full, hand_clip),
            evaluated_full=evaluated_full,
            evaluated_draw_generation=7,
        )

        self.assertTrue(receipt["clicked"])
        self.assertLess(time.monotonic() - started, 5.0)
        page.mouse.click.assert_called_once_with(1217.5, 996.5, click_count=2, delay=80)

    def test_three_meld_relighting_uses_glyph_structure_and_discards_within_clock(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frames = project / "artifacts" / "friend-5-20" / "frames"
        evaluated_full = (frames / "2026-09-21T06-33-10.603818+00-00.jpg").read_bytes()
        current_full = (frames / "2026-09-21T06-33-12.833862+00-00.jpg").read_bytes()
        layout = load_json(project / "config" / "layout.json")
        hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        stable_region = stable_hand_comparison_region(layout, 3)
        self.assertIsNotNone(stable_region)
        evaluated_faces = crop_screenshot(evaluated_full, stable_region)
        current_faces = crop_screenshot(current_full, stable_region)
        self.assertGreater(mean_pixel_delta(evaluated_faces, current_faces), 1.5)
        self.assertLess(stable_hand_delta(evaluated_faces, current_faces, 3), 1.5)

        changed = io.BytesIO()
        Image.new("RGB", (454, 108), "black").save(changed, format="PNG")
        unchanged = io.BytesIO()
        Image.new("RGB", (454, 108), "white").save(unchanged, format="PNG")
        self.assertGreater(stable_hand_delta(changed.getvalue(), unchanged.getvalue(), 3), 1.5)

        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = layout
        operator.hand_clip = hand_clip
        operator.river_clip = {"x": 740, "y": 520, "width": 430, "height": 300}
        operator.cached_open_melds = 3
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = current_full
        operator.screencast_draw_generation = 11
        operator.log = Mock()
        operator.confirm_discard = Mock(return_value={"confirmation": "hand_and_own_river_changed"})
        page = Mock()
        evaluation = {
            "decision": {"selectedAction": {"action": "discard", "tile": "5p"}},
            "recognition": {"tiles": ["1p", "2p", "3p", "4p", "5p"], "safe": True},
            "clickIndex": 0,
            "clickPoint": {"x": 268.5, "y": 999.5},
            "openMelds": 3,
        }

        started = time.monotonic()
        receipt = operator.execute(
            page, evaluation,
            evaluated_hand=crop_screenshot(evaluated_full, hand_clip),
            evaluated_full=evaluated_full,
            evaluated_draw_generation=11,
        )

        self.assertTrue(receipt["clicked"])
        self.assertLess(time.monotonic() - started, 5.0)
        page.mouse.click.assert_called_once_with(268.5, 999.5, click_count=2, delay=80)

    def test_live_over_inferred_meld_count_and_out_of_hand_click_are_rejected(self) -> None:
        project = Path(__file__).resolve().parents[1]
        layout = load_json(project / "config" / "layout.json")
        self.assertFalse(discard_point_in_hand_geometry(
            {"x": 1612.5, "y": 821.5}, layout, 1,
        ))

        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = layout
        operator.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        operator.river_clip = {"x": 740, "y": 520, "width": 430, "height": 300}
        operator.cached_open_melds = 1
        operator.screencast_session = Mock()
        frame = (project / "artifacts" / "debug-300" / "frames" /
                 "2026-09-21T04-23-11.396987+00-00.jpg").read_bytes()
        operator.latest_screencast_frame = frame
        operator.screencast_draw_generation = 2
        operator.log = Mock()
        page = Mock()
        evaluation = {
            "decision": {"selectedAction": {"action": "discard", "tile": "6p"}},
            "recognition": {"tiles": ["6p", "6p"], "safe": False},
            "clickIndex": 1,
            "clickPoint": {"x": 1612.5, "y": 821.5},
            "openMelds": 4,
        }

        with self.assertRaisesRegex(RetryableSafetyAbort, "does not match confirmed open meld count"):
            operator.execute(
                page, evaluation,
                evaluated_hand=crop_screenshot(frame, operator.hand_clip),
                evaluated_full=frame,
                evaluated_draw_generation=2,
            )
        page.mouse.click.assert_not_called()

    def test_live_frame_anchors_pre_click_meld_count_to_confirmed_call(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frame = (project / "artifacts" / "debug-300" / "frames" /
                 "2026-09-21T05-03-29.704020+00-00.jpg").read_bytes()
        hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = load_json(project / "config" / "layout.json")
        operator.hand_clip = hand_clip
        operator.river_clip = {"x": 740, "y": 520, "width": 430, "height": 300}
        operator.cached_open_melds = 1
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = frame
        operator.screencast_draw_generation = 9
        operator.log = Mock()
        operator.confirm_discard = Mock(return_value={"confirmation": "live-frame-confirmed"})
        page = Mock()
        evaluation = {
            "decision": {"selectedAction": {"action": "discard", "tile": "7m"}},
            # Eleven tiles prove the compact one-meld self-turn geometry even
            # though the old generic proposal promoted the top-level count.
            "recognition": {"tiles": ["1m"] * 10 + ["7m"], "safe": True},
            "clickIndex": 10,
            "clickPoint": {"x": 1247, "y": 999},
            "openMelds": 4,
        }

        receipt = operator.execute(
            page, evaluation,
            evaluated_hand=crop_screenshot(frame, hand_clip),
            evaluated_full=frame,
            evaluated_draw_generation=9,
        )

        self.assertTrue(receipt["clicked"])
        operator.log.assert_any_call(
            "open_meld_revalidation_anchored",
            confirmedOpenMelds=1,
            rejectedInferredOpenMelds=4,
            recognizedConcealedTiles=11,
        )
        page.mouse.click.assert_called_once_with(1247, 999, click_count=2, delay=80)

    def test_pre_click_meld_anchor_rejects_genuine_compact_geometry_change(self) -> None:
        project = Path(__file__).resolve().parents[1]
        frame = (project / "artifacts" / "debug-300" / "frames" /
                 "2026-09-21T05-03-29.704020+00-00.jpg").read_bytes()
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = load_json(project / "config" / "layout.json")
        operator.hand_clip = {"x": 223, "y": 926, "width": 1355, "height": 146}
        operator.river_clip = {"x": 740, "y": 520, "width": 430, "height": 300}
        operator.cached_open_melds = 1
        operator.screencast_session = Mock()
        operator.latest_screencast_frame = frame
        operator.screencast_draw_generation = 10
        operator.log = Mock()
        page = Mock()
        evaluation = {
            "decision": {"selectedAction": {"action": "discard", "tile": "7m"}},
            "recognition": {"tiles": ["1m"] * 8, "safe": True},
            "clickIndex": 7,
            "clickPoint": {"x": 1100, "y": 999},
            "openMelds": 2,
        }

        with self.assertRaisesRegex(RetryableSafetyAbort, "expected 11 concealed tiles, recognized 8"):
            operator.execute(
                page, evaluation,
                evaluated_hand=crop_screenshot(frame, operator.hand_clip),
                evaluated_full=frame,
                evaluated_draw_generation=10,
            )
        page.mouse.click.assert_not_called()

    def test_open_meld_count_requires_distinct_frames_and_rejects_jump(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.cached_open_melds = 0
        operator.open_meld_candidate = None
        operator.open_meld_candidate_frames = set()
        self.assertIsNone(operator.stable_open_meld_count(1, b"frame-a"))
        self.assertIsNone(operator.stable_open_meld_count(1, b"frame-a"))
        self.assertEqual(operator.stable_open_meld_count(1, b"frame-b"), 1)
        operator.cached_open_melds = 1
        self.assertIsNone(operator.stable_open_meld_count(2, b"frame-c"))

    def test_private_env_loader_passes_only_jev_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.local"
            path.write_text(
                "TYPESAFE_API_KEY=test-secret\nIGNORED=value\nJEV_MODEL=test-model\n"
                "JEV_FORCE_AUTO_DEADLINE_MS=2300\nFORCE_AUTO_CLICK_BUDGET_MS=2600\n",
                encoding="utf-8",
            )
            path.chmod(0o600)
            environment = load_secret_environment(Path(directory), ".env.local")
            self.assertEqual(environment["TYPESAFE_API_KEY"], "test-secret")
            self.assertEqual(environment["JEV_MODEL"], "test-model")
            self.assertEqual(environment["JEV_FORCE_AUTO_DEADLINE_MS"], "2300")
            self.assertEqual(environment["FORCE_AUTO_CLICK_BUDGET_MS"], "2600")
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

    def test_successful_tsumo_arms_round_terminal_latch(self) -> None:
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(mode="force-auto", allow_local_discard=False,
                                           stability_pixel_delta=1.5)
        operator.layout = {
            "viewport": {"width": 1920, "height": 1080},
            "clickPoints": [],
            "publicTileRegions": {},
        }
        operator.hand_clip = {"x": 0, "y": 0, "width": 10, "height": 10}
        operator.river_clip = {"x": 10, "y": 0, "width": 10, "height": 10}
        operator.screencast_session = Mock()
        frame_buffer = io.BytesIO()
        Image.new("RGB", (1920, 1080), "navy").save(frame_buffer, format="JPEG")
        frame = frame_buffer.getvalue()
        operator.latest_screencast_frame = frame
        operator.screencast_draw_generation = 4
        operator.log = Mock()
        operator.confirm_action_button = Mock(return_value={"confirmation": "action_button_region_changed"})
        button_buffer = io.BytesIO()
        Image.new("RGB", (100, 40), "orange").save(button_buffer, format="PNG")
        page = Mock()
        page.screenshot.return_value = button_buffer.getvalue()
        evaluation = {
            "decision": {"selectedAction": {"action": "tsumo"}},
            "recognition": {"tiles": ["2p", "2p"], "safe": False},
            "actionButton": {
                "action": "tsumo", "x": 1087, "y": 788, "width": 352, "height": 57,
                "center": {"x": 1263, "y": 816.5},
            },
        }

        receipt = operator.execute(
            page, evaluation,
            evaluated_hand=crop_screenshot(frame, operator.hand_clip),
            evaluated_draw_generation=4,
        )

        self.assertTrue(receipt["clicked"])
        self.assertTrue(operator.round_terminal_latched)
        self.assertFalse(operator.round_terminal_result_observed)

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

    def test_ranked_loop_click_points_cover_bronze_east_navigation_only(self) -> None:
        viewport = {"width": 1920, "height": 1080}
        self.assertEqual(PythonAutoOperator.ranked_loop_click_point("lobby", viewport),
                         {"x": 1390.08, "y": 324.0})
        self.assertEqual(PythonAutoOperator.ranked_loop_click_point("ranked_menu", viewport),
                         {"x": 1390.08, "y": 410.4})
        self.assertEqual(PythonAutoOperator.ranked_loop_click_point("ranked_room", viewport),
                         {"x": 1390.08, "y": 405.0})
        self.assertIsNone(PythonAutoOperator.ranked_loop_click_point("matchmaking", viewport))
        self.assertIsNone(PythonAutoOperator.ranked_loop_click_point("match", viewport))

    def test_compact_hand_requires_a_previously_observed_call(self) -> None:
        self.assertTrue(PythonAutoOperator.compact_hand_is_proven(0, False))
        self.assertTrue(PythonAutoOperator.compact_hand_is_proven(1, True))
        self.assertTrue(PythonAutoOperator.compact_hand_is_proven(4, True))
        self.assertFalse(PythonAutoOperator.compact_hand_is_proven(1, False))
        self.assertFalse(PythonAutoOperator.compact_hand_is_proven(3, False))

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

    def test_round_result_uses_confirm_button_geometry_before_whole_frame_reference(self) -> None:
        image = Image.new("RGB", (1920, 1080), (25, 55, 85))
        draw = ImageDraw.Draw(image)
        draw.rectangle((1650, 950, 1849, 1045), fill=(35, 40, 45))
        draw.rectangle((1650, 950, 1749, 1045), fill=(55, 70, 115))
        draw.rectangle((1680, 975, 1780, 1005), fill=(190, 165, 100))
        output = io.BytesIO()
        image.save(output, format="PNG")

        self.assertEqual(classify_screen(output.getvalue(), {}), ("round_result", 1.0))


if __name__ == "__main__":
    unittest.main()
