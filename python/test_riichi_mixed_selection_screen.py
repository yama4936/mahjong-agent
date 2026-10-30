"""Exact 93f9fac mixed selectable/dim faces must survive JPEG55, not relax safety.

The two full frames are byte-for-byte native recordings. Only the explicit
negative river-append case reconstructs a counterfactual full frame from an
actual appended-river crop. Modeled times are not recovered live metadata.
"""
import base64
import hashlib
import io
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

import test_riichi_confirmation_receipt_budget as receipt_tests
from auto_operator import SelectionStateUncertainAbort, crop_screenshot, raised_tile_confirmation_point
from auto_operator import river_structure_delta, send_discard_click
from screen_state import _distance, _has_bottom_tile_faces, _is_cherry_blossom_lobby
from screen_state import _is_reference_supported_riichi_selection, classify_screen


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "test/fixtures"
CONTROL = (1387, 798, 1497, 899)
ROW = (223, 930, 1454, 1065)
HUD = (800, 310, 1140, 535)


def opened(raw):
    with Image.open(io.BytesIO(raw)) as image:
        return image.convert("RGB")


def png(image):
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def row_evidence(image):
    pixels = list(image.crop(ROW).getdata())
    muted = sum(110 <= min(pixel) <= 165 and max(pixel) - min(pixel) < 30 for pixel in pixels) / len(pixels)
    bright = sum(min(pixel) > 180 for pixel in pixels) / len(pixels)
    ink = sum(max(pixel) < 100 for pixel in pixels) / len(pixels)
    return muted, bright, ink


class RiichiMixedSelectionScreenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import json
        fixture = json.loads((FIXTURES / "riichi-mixed-selection-93f9fac-20261030.json").read_text())
        cls.raw = {}
        for part in fixture["parts"]:
            raw = base64.b64decode("".join(part["base64Chunks"]), validate=True)
            assert hashlib.sha256(raw).hexdigest() == part["sha256"]
            with Image.open(io.BytesIO(raw)) as image:
                assert image.size == tuple(part["size"])
                assert image.format == part["format"]
                assert hashlib.sha256(image.convert("RGB").tobytes()).hexdigest() == part["rgbSha256"]
            cls.raw[part["name"]] = raw
        cls.before = opened(cls.raw["before"])
        cls.receipt = opened(cls.raw["receipt"])
        cls.reference = opened((FIXTURES / "riichi-selection-calibrated-match-20260920.jpg").read_bytes())
        cls.references = {"native-calibrated-match": ("match", cls.reference)}

    def supported(self, image, references=None, maximum_distance=.16):
        return _is_reference_supported_riichi_selection(
            image, self.references if references is None else references, maximum_distance)

    def probe(self):
        probe = receipt_tests.RiichiConfirmationReceiptBudgetTest()
        probe.native = {"before": self.raw["before"], "raised": self.raw["receipt"]}
        self.addCleanup(probe.doCleanups)
        probe.setUp()
        probe.op.screen_references = self.references
        return probe

    def test_exact_native_pair_and_same_before_jpeg55_reproduce_old_lobby_collision(self):
        self.assertEqual(classify_screen(self.raw["before"], self.references), ("match", 1.0))
        self.assertTrue(_has_bottom_tile_faces(self.before))
        output = io.BytesIO()
        self.before.save(output, format="JPEG", quality=55)
        for raw in (self.raw["receipt"], output.getvalue()):
            image = opened(raw)
            with self.subTest(kind="recorded" if raw is self.raw["receipt"] else "same_before_jpeg55"):
                self.assertFalse(_has_bottom_tile_faces(image))
                muted, bright, ink = row_evidence(image)
                self.assertLess(muted, .45)  # old all-dim branch cannot explain this positive
                self.assertGreaterEqual(muted, .40)
                self.assertGreaterEqual(bright, .12)
                self.assertGreaterEqual(muted + bright, .58)
                self.assertGreaterEqual(ink, .04)
                self.assertTrue(_is_cherry_blossom_lobby(image))
                self.assertTrue(self.supported(image))
                self.assertLessEqual(_distance(image, self.reference), .085)
                self.assertLessEqual(_distance(image.crop(HUD), self.reference.crop(HUD)), .05)
                with patch("screen_state._is_reference_supported_riichi_selection", return_value=False):
                    self.assertEqual(classify_screen(raw, self.references), ("lobby", 1.0))
                self.assertEqual(classify_screen(raw, self.references), ("match", 1.0))

    def test_codec_crosses_original_130_threshold_without_changing_ui(self):
        for point in ((245, 945), (345, 945)):
            self.assertEqual(self.before.getpixel(point), (134, 134, 132))
            self.assertEqual(self.receipt.getpixel(point), (133, 134, 129))
        self.assertAlmostEqual(row_evidence(self.receipt)[0], .42663296928122274)
        self.assertAlmostEqual(row_evidence(self.receipt)[1], .16811384902367843)

    def test_mixed_branch_requires_substantial_muted_bright_combined_and_ink(self):
        # These are negative unit controls, not native-positive evidence.
        width, height = ROW[2] - ROW[0], ROW[3] - ROW[1]
        count = width * height
        for muted, bright, rest in ((.39, .20, (20, 30, 40)), (.42, .11, (20, 30, 40)),
                                     (.42, .15, (20, 30, 40)), (.42, .26, (20, 30, 40)),
                                     (.42, .18, (170, 170, 170))):
            pixels = ([(127, 127, 127)] * int(count * muted)
                      + [(220, 220, 220)] * int(count * bright))
            pixels += [rest] * (count - len(pixels))
            row = Image.new("RGB", (width, height))
            row.putdata(pixels)
            image = self.receipt.copy()
            image.paste(row, ROW)
            with self.subTest(muted=muted, bright=bright, rest=rest):
                self.assertFalse(self.supported(image))

    def test_uniform_strips_and_missing_or_flat_return_control_are_not_evidence(self):
        for box in (ROW, CONTROL):
            for fill in ((127, 127, 127), (220, 220, 220), (20, 30, 40), (220, 170, 90)):
                image = self.receipt.copy()
                image.paste(fill, box)
                with self.subTest(box=box, fill=fill):
                    self.assertFalse(self.supported(image))

    def test_mixed_row_cannot_override_real_lobby_even_with_native_control(self):
        lobby = opened((FIXTURES / "black-recovered-lobby-20261021.png").read_bytes())
        for boxes in ((ROW,), (CONTROL,), (ROW, CONTROL)):
            image = lobby.copy()
            for box in boxes:
                image.paste(self.receipt.crop(box), box)
            self.assertFalse(self.supported(image), str(boxes))

    def test_native_geometry_and_a_complete_match_reference_remain_required(self):
        for references in ({}, {"lobby": ("lobby", self.reference)},
                           {"partial": ("match", self.reference.crop((0, 0, 1920, 900)))}):
            self.assertFalse(self.supported(self.receipt, references))
        for image in (self.receipt.resize((1280, 720)), self.receipt.resize((1919, 1080)),
                      self.receipt.crop((0, 0, 1920, 900))):
            self.assertFalse(self.supported(image))
        self.assertFalse(self.supported(self.receipt, maximum_distance=.05))

    def test_hud_and_whole_frame_evidence_must_belong_to_the_same_reference(self):
        no_hud = self.reference.copy()
        no_hud.paste((127, 127, 127), HUD)
        hud_only = Image.new("RGB", (1920, 1080), (190, 190, 190))
        hud_only.paste(self.reference.crop(HUD), HUD)
        self.assertLess(_distance(self.receipt, no_hud), .085)
        self.assertGreater(_distance(self.receipt.crop(HUD), no_hud.crop(HUD)), .05)
        self.assertFalse(self.supported(self.receipt, {
            "whole-only": ("match", no_hud), "hud-only": ("match", hud_only)}))
        image = self.receipt.copy()
        image.paste((127, 127, 127), HUD)
        self.assertFalse(self.supported(image))

    def test_real_non_match_and_blank_frames_do_not_gain_reference_support(self):
        paths = ("black-recovered-lobby-20261021.png", "startup-away-20261029.jpg",
                 "round-terminal-recovery-away-20261023.png", "lobby-loading-after-ranked-result-20261020.png")
        for name in paths:
            image = opened((FIXTURES / name).read_bytes())
            self.assertFalse(self.supported(image), name)
        for name in ("draw-tenpai-result-20260928.png", "south4-loss-result-20260928.png"):
            image = opened((ROOT / "artifacts/live" / name).read_bytes())
            self.assertFalse(self.supported(image), name)
        for fill in ("black", "white", (127, 127, 127)):
            self.assertFalse(self.supported(Image.new("RGB", (1920, 1080), fill)))
        self.assertEqual(classify_screen(FIXTURES / paths[0], self.references), ("lobby", 1.0))

    def test_ordinary_native_fast_path_and_rejected_control_remain_lazy(self):
        with patch("screen_state._is_reference_supported_riichi_selection", side_effect=AssertionError("fast path")):
            self.assertEqual(classify_screen(self.raw["before"], self.references), ("match", 1.0))
        image = self.receipt.copy()
        image.paste((20, 30, 40), CONTROL)
        with patch("screen_state._distance", side_effect=AssertionError("rejected control")):
            self.assertFalse(self.supported(image))

    def test_exact_raised_9s_can_finish_only_with_its_coupled_second_click_certificate(self):
        probe = self.probe()
        point = raised_tile_confirmation_point(self.raw["before"], self.raw["receipt"], probe.op.layout,
            12, {"x": 1407, "y": 996.5}, 1.5)
        self.assertEqual((point["x"], point["y"], point["lift"]), (1407, 948.5, 48))
        probe.clock["now"] = 105.3
        mouse = Mock()
        send_discard_click(mouse, {"x": 1407, "y": 996.5}, probe.op.layout["viewport"],
            lambda _: probe.clock.update(now=106.783), self.raw["before"], lambda _: probe.receipt.frame,
            probe.op.layout, 12, 1.5, lambda: probe.certify(), probe.op.record_unverified_selection)
        self.assertEqual(mouse.click.call_count, 2)
        self.assertEqual(mouse.click.call_args.args, (1407, 948.5))
        self.assertEqual((probe.op.action_evidence_started_at, probe.op.action_budget_started_at), (100, 100))

    def test_classifier_recovery_does_not_hide_real_river_append_or_reuse_adjacent_hitbox(self):
        probe = self.probe()
        image = self.receipt.copy()
        image.paste(opened(self.raw["confirmed-river"]), (750, 535, 1160, 760))
        changed = png(image)
        self.assertEqual(classify_screen(changed, self.references), ("match", 1.0))
        self.assertGreater(river_structure_delta(probe.base.own_river,
            crop_screenshot(changed, probe.op.river_clip)), .1)
        probe.receipt = replace(probe.receipt, frame=changed)
        probe.native = {**probe.native, "raised": changed}
        mouse = Mock()
        probe.clock["now"] = 105.3
        with self.assertRaisesRegex(SelectionStateUncertainAbort, "river_changed"):
            send_discard_click(mouse, {"x": 1407, "y": 996.5}, probe.op.layout["viewport"],
                lambda _: probe.clock.update(now=106.783), self.raw["before"], lambda _: changed,
                probe.op.layout, 12, 1.5, lambda: probe.certify(), probe.op.record_unverified_selection)
        mouse.click.assert_called_once_with(1407, 996.5)
        # The observed 9s lift cannot certify the adjacent physical 8s.
        self.assertIsNone(raised_tile_confirmation_point(self.raw["before"], self.raw["receipt"],
            probe.op.layout, 11, {"x": 1312, "y": 996.5}, 1.5))

    def test_new_mixed_match_cannot_extend_original_clock_or_final_image_reserve(self):
        for reason, now, stamp, first_click, deadline in (
            ("global", 105.1, 104.8, 104.5, 5000),
            ("ten_seconds", 110.1, 109.9, 105.3, 300000),
            ("reserve", 109.4, 109.2, 105.3, 300000),
        ):
            probe = self.probe()
            probe.op.args.action_deadline_ms = deadline
            probe.base = replace(probe.base, deadline_ms=deadline)
            probe.receipt = replace(probe.receipt, captured_at=stamp)
            probe.clock["now"] = first_click
            mouse = Mock()
            with self.subTest(reason=reason), self.assertRaises(SelectionStateUncertainAbort):
                send_discard_click(mouse, {"x": 1407, "y": 996.5}, probe.op.layout["viewport"],
                    lambda _: probe.clock.update(now=now), self.raw["before"], lambda _: probe.receipt.frame,
                    probe.op.layout, 12, 1.5,
                    lambda: probe.certify(first_click_at=first_click), probe.op.record_unverified_selection)
            mouse.click.assert_called_once_with(1407, 996.5)


if __name__ == "__main__":
    unittest.main()
