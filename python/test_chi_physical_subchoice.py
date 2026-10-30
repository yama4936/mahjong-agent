"""Regression for 2 physical chi selectors versus 1 structural legal action.

Native selector ROI is exact decoded RGB from the continued recorded UI, not
the unsaved first failure receipt. Counterfactual edits are explicit negatives.
"""
import base64
import hashlib
import io
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from auto_operator import (PythonAutoOperator, RetryableSafetyAbort,
                           force_auto_chi_choice_points, selected_chi_choice_point)


ROOT = Path(__file__).resolve().parents[1]
VIEWPORT = {"width": 1920, "height": 1080}


def encoded(image, format="PNG", **kwargs):
    output = io.BytesIO()
    image.save(output, format=format, **kwargs)
    return output.getvalue()


class ChiPhysicalSubchoiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((ROOT / "test/fixtures/chi-physical-sou-20261030.json").read_text())
        roi = cls.fixture["selector"]
        with Image.open(io.BytesIO(base64.b64decode(roi["pngBase64"]))) as image:
            cls.roi = image.convert("RGB")
        assert hashlib.sha256(cls.roi.tobytes()).hexdigest() == roi["rgbSha256"]
        cls.image = Image.new("RGB", (1920, 1080))
        cls.image.paste(cls.roi, roi["sourceBox"][:2])
        cls.native = encoded(cls.image)
        cls.points = force_auto_chi_choice_points(cls.native, VIEWPORT)
        cls.selected = cls.fixture["selectedAction"]

    def pick(self, raw=None, selected=None, legal=None, points=None, viewport=None):
        return selected_chi_choice_point(
            self.points if points is None else points,
            self.selected if selected is None else selected,
            [self.selected, {"id": "pass", "action": "pass"}] if legal is None else legal,
            screenshot=self.native if raw is None else raw,
            viewport=VIEWPORT if viewport is None else viewport,
        )

    def test_exact_native_reproduces_structural_count_mismatch_then_selects_red(self):
        self.assertEqual(self.points, [{"x": 839.5, "y": 794.0}, {"x": 1039.5, "y": 794.0}])
        self.assertEqual(len([self.selected]), 1)  # old len(points) != len(chi_actions)
        self.assertEqual(self.pick(), self.points[0])
        self.assertIsNone(selected_chi_choice_point(self.points, self.selected, [self.selected]))

    def test_exact_normal_physical_request_is_not_silently_changed_to_red(self):
        selected = {**self.selected, "consumedTiles": ["5s", "6s"]}
        self.assertEqual(self.pick(selected=selected), self.points[1])
        self.assertEqual(self.pick(selected={**selected, "consumedTiles": ["6s", "5s"]}), self.points[1])

    def test_physical_choices_order_does_not_establish_ui_order(self):
        selected = {**self.selected, "consumedTileChoices": list(reversed(self.selected["consumedTileChoices"]))}
        self.assertEqual(self.pick(selected=selected, legal=[selected]), self.points[0])
        swapped = self.image.copy()
        swapped.paste(self.image.crop((960, 707, 1120, 827)), (760, 707))
        swapped.paste(self.image.crop((760, 707, 920, 827)), (960, 707))
        self.assertEqual(self.pick(raw=encoded(swapped)), self.points[1])
        self.assertEqual(self.pick(points=list(reversed(self.points))), self.points[0])

    def test_native_png_and_jpeg55_90_have_same_exact_physical_selection(self):
        for quality in (55, 90):
            with self.subTest(quality=quality):
                raw = encoded(self.image, "JPEG", quality=quality)
                points = force_auto_chi_choice_points(raw, VIEWPORT)
                self.assertEqual(self.pick(raw=raw, points=points), points[0])

    def test_missing_duplicate_occluded_or_blank_choices_are_not_guessed(self):
        for kind in ("missing", "duplicate", "occluded", "blank"):
            image = self.image.copy()
            if kind == "missing":
                image.paste((0, 0, 0), (960, 707, 1120, 827))
            elif kind == "duplicate":
                image.paste(self.image.crop((760, 707, 920, 827)), (960, 707))
            elif kind == "occluded":
                image.paste((0, 0, 0), (775, 733, 820, 810))
            else:
                image.paste((240, 240, 240), (760, 707, 1120, 827))
            with self.subTest(kind=kind):
                self.assertIsNone(self.pick(raw=encoded(image)))
        self.assertIsNone(self.pick(points=self.points[:1]))
        self.assertIsNone(self.pick(points=self.points + self.points[:1]))

    def test_second_tile_glyph_change_and_wrong_normal_glyph_rejected(self):
        for source, destination in (((967, 730, 1033, 820), (847, 730)),
                                    ((847, 730, 913, 820), (967, 730))):
            image = self.image.copy()
            image.paste(image.crop(source), destination)
            self.assertIsNone(self.pick(raw=encoded(image)))

    def test_malformed_or_unproven_physical_alternatives_rejected(self):
        variants = [
            {**self.selected, "consumedTiles": ["0s", "8s"]},
            {**self.selected, "id": "other"},
            {**self.selected, "tile": "4s"},
            {**self.selected, "action": "pon"},
        ]
        for selected in variants:
            with self.subTest(selected=selected):
                self.assertIsNone(self.pick(selected=selected))
        for pairs in ([], [["0s", "6s"]], [["0s", "6s"], ["0s", "6s"]],
                      [["0s", "6s"], ["5s", "8s"]], [None, ["5s", "6s"]]):
            legal = [{**self.selected, "consumedTileChoices": pairs}]
            self.assertIsNone(self.pick(legal=legal))
        self.assertIsNone(self.pick(legal=[self.selected, {"id": "chi_other", "action": "chi"}]))

    def test_unknown_geometry_partial_image_and_invalid_points_rejected(self):
        self.assertIsNone(self.pick(viewport={"width": 1280, "height": 720}))
        self.assertIsNone(self.pick(raw=encoded(self.roi)))
        for point in ({"x": float("nan"), "y": 794.0}, {"x": True, "y": 794.0},
                      {"x": False, "y": 794.0},
                      {"x": 839.5, "y": 795.0}, {"x": 879.5, "y": 794.0}):
            self.assertIsNone(self.pick(points=[point, self.points[1]]))

    def test_legacy_nonambiguous_structural_choice_order_unchanged(self):
        selected = {"id": "chi_b", "action": "chi", "tile": "3s", "consumedTiles": ["4s", "0s"]}
        legal = [{"id": "chi_a", "action": "chi"}, selected]
        self.assertEqual(selected_chi_choice_point(self.points, selected, legal), self.points[1])
        self.assertIsNone(selected_chi_choice_point(self.points, None, legal))
        self.assertEqual(selected_chi_choice_point(self.points[:1], None, []), self.points[0])

    def execution_fixture(self):
        op = PythonAutoOperator.__new__(PythonAutoOperator)
        op.args = SimpleNamespace(mode="force-auto", accept_single_call=True, confirmation_timeout=3)
        op.layout = {"viewport": VIEWPORT}
        op.hand_clip = {"x": 200, "y": 900, "width": 1250, "height": 175}
        op.require_force_auto_click_budget = Mock()
        op.require_action_deadline = Mock()
        op.log = Mock()
        op.screencast_sequence = 0
        op.latest_screencast_frame = None
        op.action_evidence_started_at = 98
        op.action_budget_started_at = 98
        op.action_evidence_kind = "reaction"
        page = Mock()
        page.screenshot.return_value = self.native
        button = {"action": "chi", "center": {"x": 1022, "y": 821.5}}
        return op, page, button

    def test_execute_uses_the_current_selector_pixels_without_changing_clocks(self):
        op, page, button = self.execution_fixture()
        # End the existing confirmation loop immediately after its subchoice;
        # this test proves wiring, not that a static selector completed a call.
        with patch("auto_operator.force_auto_call_buttons", return_value=[button]), \
                patch("auto_operator.time.monotonic", side_effect=[100, 100, 100.1, 104]):
            with self.assertRaisesRegex(RetryableSafetyAbort, "hand and own meld did not change"):
                op.execute_force_auto_call(page, self.native, button, self.selected, [self.selected],
                                           evaluated_captured_at=99)
        self.assertEqual(page.mouse.click.call_args_list[1].args, (839.5, 794.0))
        self.assertEqual(page.mouse.click.call_count, 2)
        self.assertEqual([call.kwargs["phase"] for call in op.require_force_auto_click_budget.call_args_list],
                         ["before_reaction_call_click", "before_chi_choice_click"])
        self.assertEqual([call.args for call in op.require_force_auto_click_budget.call_args_list], [(99,), (99,)])
        self.assertEqual(op.require_action_deadline.call_count, 2)
        self.assertEqual((op.action_evidence_started_at, op.action_budget_started_at,
                          op.action_evidence_kind), (98, 98, "reaction"))

    def test_expired_original_image_or_global_deadline_prevents_second_click(self):
        for guard in ("require_force_auto_click_budget", "require_action_deadline"):
            op, page, button = self.execution_fixture()
            getattr(op, guard).side_effect = [None, RetryableSafetyAbort("original clock expired")]
            with self.subTest(guard=guard), \
                    patch("auto_operator.force_auto_call_buttons", return_value=[button]), \
                    patch("auto_operator.time.monotonic", side_effect=[100, 100, 100.1]):
                with self.assertRaisesRegex(RetryableSafetyAbort, "original clock expired"):
                    op.execute_force_auto_call(page, self.native, button, self.selected, [self.selected],
                                               evaluated_captured_at=99)
            self.assertEqual(page.mouse.click.call_count, 1)
            self.assertEqual((op.action_evidence_started_at, op.action_budget_started_at,
                              op.action_evidence_kind), (98, 98, "reaction"))

    def test_fixture_and_runtime_templates_share_exact_native_pixels(self):
        template = json.loads((ROOT / "templates/screens/chi-physical-sou-20261030.json").read_text())
        self.assertEqual(template["provenance"], self.fixture["provenance"])
        for part in template["pairs"]:
            with Image.open(io.BytesIO(base64.b64decode(part["pngBase64"]))) as image:
                rgb = image.convert("RGB")
            self.assertEqual(hashlib.sha256(rgb.tobytes()).hexdigest(), part["rgbSha256"])
            self.assertEqual(rgb.tobytes(), self.image.crop(part["sourceBox"]).tobytes())


if __name__ == "__main__":
    unittest.main()
