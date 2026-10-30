"""Native/JPEG call bounds, calibrated skip body, and exact failure receipts."""
import base64
import copy
import hashlib
import io
import random
import stat
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

import test_optional_reaction_budget_pass as budget_tests
from auto_operator import (
    RetryableSafetyAbort, calibrated_skip_body_comparison, force_auto_call_buttons,
    load_json, mean_pixel_delta, supported_call_palette_mask,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/reaction-palette-timer-20261030.json"


class ReactionPaletteTimerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = load_json(FIXTURE)
        cls.layout = load_json(ROOT / "config/layout.json")
        cls.pixels = {}
        for frame in cls.fixture["frames"]:
            raw = base64.b64decode(frame["pngBase64"], validate=True)
            if hashlib.sha256(raw).hexdigest() != frame["sha256"]:
                raise AssertionError("fixture hash mismatch")
            cls.pixels[frame["name"]] = raw

    @staticmethod
    def png(image):
        output = io.BytesIO()
        image.save(output, "PNG")
        return output.getvalue()

    def frame(self, name):
        item = next(frame for frame in self.fixture["frames"] if frame["name"] == name)
        full = Image.new("RGB", (1920, 1080), (20, 40, 70))
        full.paste(Image.open(io.BytesIO(self.pixels[name])), tuple(item["box"][:2]))
        return self.png(full)

    def probe(self):
        probe = budget_tests.OptionalReactionBudgetPassTest()
        self.addCleanup(probe.doCleanups)
        probe.setUp()
        return probe

    def test_native_and_recorded_stream_call_centers_fit_unchanged_twelve_pixel_guard(self):
        native = self.frame("native_stall")
        streamed = self.frame("stream_stall")
        viewport = self.layout["viewport"]
        actual = force_auto_call_buttons(native, viewport)
        expected = force_auto_call_buttons(streamed, viewport)
        self.assertEqual(len(actual), 1)
        self.assertEqual(len(expected), 1)
        self.assertEqual(actual[0]["action"], "chi")
        self.assertEqual(actual[0]["center"], {"x": 1012.0, "y": 825.5})
        self.assertEqual(expected[0]["center"], {"x": 1022.0, "y": 821.5})
        for axis in ("x", "y"):
            self.assertLessEqual(abs(actual[0]["center"][axis] - expected[0]["center"][axis]), 12)
        # Exact native palette values become the recorded isolated green
        # JPEG pixel without moving any UI element.
        image = Image.open(io.BytesIO(native)).convert("RGB")
        self.assertEqual(image.getpixel((1006, 734)), (181, 181, 179))
        output = io.BytesIO()
        image.save(output, "JPEG", quality=55)
        lossy = Image.open(io.BytesIO(output.getvalue())).convert("RGB")
        self.assertEqual(lossy.getpixel((1006, 734)), (171, 187, 176))
        self.assertEqual(force_auto_call_buttons(output.getvalue(), viewport), expected)

    def test_singletons_and_small_floating_components_do_not_shift_real_call(self):
        original = self.frame("native_stall")
        expected = force_auto_call_buttons(original, self.layout["viewport"])
        image = Image.open(io.BytesIO(original)).convert("RGB")
        draw = ImageDraw.Draw(image)
        for point in ((1006, 734), (1020, 748), (1035, 910)):
            draw.point(point, fill=(0, 200, 0))
        draw.rectangle((1040, 740, 1041, 741), fill=(0, 200, 0))  # 4px component
        self.assertEqual(force_auto_call_buttons(self.png(image), self.layout["viewport"]), expected)

    def test_thin_label_and_detached_body_components_remain_intact(self):
        mask = Image.new("L", (40, 40))
        draw = ImageDraw.Draw(mask)
        draw.rectangle((10, 25, 30, 35), fill=255)  # body
        draw.line((15, 5, 19, 5), fill=255)  # detached 1px-high 5px label
        draw.line((20, 10, 20, 14), fill=255)  # detached 1px-wide 5px label
        draw.line((1, 15, 5, 19), fill=255)  # 8-connected diagonal
        self.assertEqual(supported_call_palette_mask(mask).tobytes(), mask.tobytes())
        native = Image.open(io.BytesIO(self.frame("native_stall"))).convert("RGB")
        # Detached 1px-wide label has enough *column* support, and must still
        # contribute its original upper bound rather than be eroded away.
        ImageDraw.Draw(native).line((1000, 750, 1000, 754), fill=(0, 200, 0))
        call = force_auto_call_buttons(self.png(native), self.layout["viewport"])[0]
        self.assertEqual(call["y"], 750)

    def test_raw_five_pixel_column_keeps_thin_connected_label_bridge(self):
        # Four real connected label pixels plus one remote noise pixel still
        # satisfy the *original* column gate. Reapplying >=5 after cleanup
        # would drop the bridge and split the real button into two narrow
        # false negatives, as happened with the tracked pon/kan native UI.
        viewport = {"width": 1000, "height": 1000}
        for color, action in (((50, 140, 80), "chi"), ((50, 150, 180), "pon")):
            image = Image.new("RGB", (1000, 1000), "black")
            draw = ImageDraw.Draw(image)
            draw.rectangle((400, 720, 440, 760), fill=color)
            draw.rectangle((460, 720, 500, 760), fill=color)
            draw.line((440, 736, 460, 736), fill=color)
            draw.line((450, 735, 450, 738), fill=color)
            draw.point((450, 680), fill=color)
            with self.subTest(action=action):
                self.assertEqual(force_auto_call_buttons(self.png(image), viewport), [{
                    "action": action, "x": 400, "y": 720, "width": 100, "height": 40,
                    "center": {"x": 450.0, "y": 740.0},
                }])

    def test_two_dimensional_support_matches_small_component_oracle(self):
        rng = random.Random(24030)
        for _ in range(60):
            values = [255 if rng.random() < .2 else 0 for _ in range(24 * 20)]
            expected = values.copy()
            pending = {index for index, value in enumerate(values) if value}
            while pending:
                start = pending.pop()
                component, stack = [start], [start]
                while stack:
                    index = stack.pop()
                    x, y = index % 24, index // 24
                    for dx in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            neighbour = (y + dy) * 24 + x + dx
                            if 0 <= x + dx < 24 and 0 <= y + dy < 20 and neighbour in pending:
                                pending.remove(neighbour)
                                stack.append(neighbour)
                                component.append(neighbour)
                if len(component) < 5:
                    for index in component:
                        expected[index] = 0
            mask = Image.new("L", (24, 20))
            mask.putdata(values)
            self.assertEqual(list(supported_call_palette_mask(mask).getdata()), expected)

    def test_both_recorded_timer_pairs_use_body_without_relaxing_stability_threshold(self):
        for index, recorded in enumerate(self.fixture["originalRejects"], 1):
            before, after = self.pixels[f"timer{index}_before"], self.pixels[f"timer{index}_confirmed"]
            with self.subTest(pair=index):
                self.assertAlmostEqual(mean_pixel_delta(before, after), recorded["rawDelta"])
                result = calibrated_skip_body_comparison(before, after, self.layout)
                self.assertIsNotNone(result)
                self.assertAlmostEqual(result["buttonPixelDelta"], recorded["bodyDelta"])
                self.assertLess(result["buttonPixelDelta"], 1.5)
                self.assertEqual(result["comparisonLocalBox"], [0, 0, 248, 105])
                self.assertGreaterEqual(min(result["labelSimilarities"]), .98)

    def test_unknown_geometry_partial_or_unknown_label_does_not_exclude_any_pixels(self):
        before, after = self.pixels["timer1_before"], self.pixels["timer1_confirmed"]
        for case in ("viewport", "region_x", "region_width", "partial", "unknown_label"):
            layout = copy.deepcopy(self.layout)
            current = after
            if case == "viewport":
                layout["viewport"]["width"] = 1919
            elif case == "region_x":
                layout["actionButtonRegions"]["pass"]["x"] += 1
            elif case == "region_width":
                layout["actionButtonRegions"]["pass"]["width"] -= 1
            elif case == "partial":
                current = self.png(Image.open(io.BytesIO(after)).crop((0, 0, 274, 105)))
            else:
                current = self.png(Image.new("RGB", (275, 105), (120, 105, 60)))
            with self.subTest(case=case):
                self.assertIsNone(calibrated_skip_body_comparison(before, current, layout))

    def test_missing_or_corrupt_label_reference_keeps_full_comparison(self):
        before, after = self.pixels["timer1_before"], self.pixels["timer1_confirmed"]
        with patch("auto_operator.load_json", side_effect=OSError("reference missing")):
            self.assertIsNone(calibrated_skip_body_comparison(before, after, self.layout))
        data = load_json(ROOT / "templates/screens/reaction-skip-body.json")
        data["sha256"] = "0" * 64
        with patch("auto_operator.load_json", return_value=data):
            self.assertIsNone(calibrated_skip_body_comparison(before, after, self.layout))

    def test_real_timer_pair_stream_pass_uses_calibrated_body_with_old_clock_unchanged(self):
        probe = self.probe()
        before = Image.open(io.BytesIO(self.frame("native_stall"))).convert("RGB")
        before.paste(Image.open(io.BytesIO(self.pixels["timer1_before"])), (1170, 775))
        after = before.copy()
        after.paste(Image.open(io.BytesIO(self.pixels["timer1_confirmed"])), (1170, 775))
        evaluated = probe.directory / "evaluated.png"
        evaluated.write_bytes(self.png(before))
        probe.operator.latest_screencast_frame = self.png(after)
        probe.operator.latest_screencast_captured_at = 103.0
        evaluation = {"reactionFrame": str(evaluated), "actionButton": {
            "action": "pass", "source": "force_auto_fixed_geometry", "center": {"x": 1307.5, "y": 827.5}}}
        receipt = probe.operator.execute_reaction_pass(probe.page, evaluation, evaluated_captured_at=102.8)
        self.assertTrue(receipt["clicked"])
        probe.page.screenshot.assert_not_called()
        probe.page.mouse.click.assert_called_once_with(1307.5, 827.5)
        self.assertEqual(probe.original_clock_at_click, [(100.0, 100.0)])
        event = next(call for call in probe.operator.log.call_args_list
                     if call.args[0] == "reaction_pass_calibrated_body_comparison")
        self.assertAlmostEqual(event.kwargs["rawButtonPixelDelta"], self.fixture["originalRejects"][0]["rawDelta"])
        self.assertAlmostEqual(event.kwargs["buttonPixelDelta"], self.fixture["originalRejects"][0]["bodyDelta"])

    def test_moved_changed_or_withdrawn_label_still_fails_original_one_point_five_guard(self):
        original = self.pixels["timer1_before"]
        for case in ("move1", "move4", "move_y", "changed_label", "withdrawn"):
            image = Image.open(io.BytesIO(original)).convert("RGB")
            if case.startswith("move"):
                shifted = Image.new("RGB", image.size, (20, 40, 70))
                shifted.paste(image, (0, 4) if case == "move_y" else (1 if case == "move1" else 4, 0))
                image = shifted
            elif case == "changed_label":
                ImageDraw.Draw(image).rectangle((100, 20, 140, 70), fill=(20, 40, 70))
            else:
                image = Image.new("RGB", image.size, (20, 40, 70))
            current = self.png(image)
            comparison = calibrated_skip_body_comparison(original, current, self.layout)
            delta = comparison["buttonPixelDelta"] if comparison else mean_pixel_delta(original, current)
            with self.subTest(case=case):
                self.assertGreater(delta, 1.5)

    def test_actual_stream_center_can_confirm_native_full_pair_without_clock_reset(self):
        probe = self.probe()
        native = self.frame("native_stall")
        expected = force_auto_call_buttons(self.frame("stream_stall"), self.layout["viewport"])[0]
        probe.capture_images = [native, native]
        evaluation = {"actionButton": {"action": "pass", "source": "force_auto_fixed_geometry",
                                       "center": {"x": 1307.5, "y": 827.5}}}
        with patch("auto_operator.classify_screen", return_value=("match", 1)):
            receipt = probe.operator.execute_reaction_pass(
                probe.page, evaluation, evaluated_captured_at=100, expired_optional_call=expected)
        self.assertTrue(receipt["clicked"])
        probe.page.mouse.click.assert_called_once_with(1307.5, 827.5)
        self.assertEqual(probe.original_clock_at_click, [(100.0, 100.0)])

    def test_real_call_movement_still_fails_and_records_exact_first_receipt_and_flags(self):
        probe = self.probe()
        native = self.frame("native_stall")
        expected = force_auto_call_buttons(native, self.layout["viewport"])[0]
        moved = Image.open(io.BytesIO(native)).convert("RGB")
        call = moved.crop((875, 775, 1145, 880))
        moved.paste((20, 40, 70), (875, 775, 1145, 880))
        moved.paste(call, (925, 775))
        raw = self.png(moved)
        probe.capture_images = [raw]
        with patch("auto_operator.classify_screen", return_value=("match", 1)), \
                self.assertRaisesRegex(RetryableSafetyAbort, "call or skip prompt changed"):
            probe.operator.confirm_expired_optional_call_pass(probe.page, expected)
        probe.page.mouse.click.assert_not_called()
        event = next(call for call in probe.operator.log.call_args_list
                     if call.args[0] == "expired_optional_pass_confirmation_rejected")
        self.assertEqual(event.kwargs["reason"], "call_center_changed")
        self.assertEqual(event.kwargs["stage"], "first")
        self.assertEqual(event.kwargs["expectedCall"], expected)
        flags = event.kwargs["observations"][0]
        self.assertTrue(flags["callCountMatches"])
        self.assertTrue(flags["callActionMatches"])
        self.assertFalse(flags["callCenterMatches"])
        self.assertFalse(flags["drawVisible"])
        self.assertFalse(flags["orangeButtons"])
        self.assertTrue(flags["plainPass"] or flags["contextualPass"])
        snapshot = event.kwargs["snapshots"][0]
        path = Path(snapshot["screenshot"])
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(snapshot["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_second_frame_win_records_both_exact_full_receipts_without_pass(self):
        probe = self.probe()
        ron = probe.native_frame("ron")
        with self.assertRaisesRegex(RetryableSafetyAbort, "win or changed screen"):
            probe.execute_native_pair(ron)
        probe.page.mouse.click.assert_not_called()
        event = next(call for call in probe.operator.log.call_args_list
                     if call.args[0] == "expired_optional_pass_confirmation_rejected")
        self.assertEqual(event.kwargs["reason"], "orange_present")
        self.assertEqual(event.kwargs["stage"], "second")
        self.assertEqual(len(event.kwargs["snapshots"]), 2)
        for snapshot, raw in zip(event.kwargs["snapshots"], (probe.native_frame("chi"), ron)):
            self.assertEqual(Path(snapshot["screenshot"]).read_bytes(), raw)
            self.assertEqual(snapshot["sha256"], hashlib.sha256(raw).hexdigest())

    def test_full_receipt_save_failure_or_recorder_failure_never_hides_original_guard(self):
        for case in ("disk_full", "recorder_failure"):
            probe = self.probe()
            ron = probe.native_frame("ron")
            write = Path.write_bytes
            def fail_receipt(path, pixels):
                if ".expired-pass-" in path.name:
                    raise OSError("diagnostic disk full")
                return write(path, pixels)
            if case == "recorder_failure":
                probe.operator.record_expired_optional_pass_failure = Mock(side_effect=OSError("diagnostic failure"))
            with self.subTest(case=case), patch.object(Path, "write_bytes", fail_receipt), \
                    self.assertRaisesRegex(RetryableSafetyAbort, "win or changed screen"):
                probe.execute_native_pair(ron)
            probe.page.mouse.click.assert_not_called()
            self.assertEqual(probe.operator.action_budget_started_at, 100.0)
            if case == "disk_full":
                event = next(call for call in probe.operator.log.call_args_list
                             if call.args[0] == "expired_optional_pass_confirmation_rejected")
                self.assertTrue(all("evidenceSaveError" in snap for snap in event.kwargs["snapshots"]))


if __name__ == "__main__":
    unittest.main()
