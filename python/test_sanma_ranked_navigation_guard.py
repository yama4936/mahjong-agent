import argparse
import os
import unittest
from pathlib import Path
from unittest.mock import Mock
from PIL import Image
from auto_operator import PythonAutoOperator

class SanmaRankedNavigationGuardTests(unittest.TestCase):
    def test_sanma_or_unrecognized_rules_never_use_yonma_targets(self):
        viewport = {"width": 1920, "height": 1080}
        for state in ("lobby", "ranked_menu", "ranked_room"):
            self.assertIsNotNone(PythonAutoOperator.ranked_loop_click_point(state, viewport))
            for rules in ("sanma", "unknown", ""):
                with self.subTest(state=state, rules=rules):
                    self.assertIsNone(PythonAutoOperator.ranked_loop_click_point(state, viewport, rules=rules))

    def test_sanma_advance_never_clicks_even_with_strong_screen_candidate(self):
        operator = PythonAutoOperator.__new__(PythonAutoOperator)
        operator.args = argparse.Namespace(ranked_loop=True, rules="sanma")
        operator.layout = {"viewport": {"width": 1920, "height": 1080}}
        page = Mock()
        for state in ("lobby", "ranked_menu", "ranked_room"):
            self.assertFalse(operator.advance_ranked_loop(page, state, 1.0))
        page.mouse.click.assert_not_called()

    def test_saved_bronze_menu_four_player_target_points_at_four_player_east(self):
        root = os.environ.get("SANMA_PREFLIGHT_ROOT")
        if not root: self.skipTest("archive not configured")
        path = Path(root) / "jantama-bronze-menu.png"
        with Image.open(path) as image: self.assertEqual(image.size, (1920, 1080))
        point = PythonAutoOperator.ranked_loop_click_point("ranked_room", {"width":1920,"height":1080}, rules="yonma")
        # Manually reviewed rectangles from this single screenshot, not OCR.
        self.assertTrue(1145 <= point["x"] < 1650 and 334 <= point["y"] < 480)
        self.assertFalse(1145 <= point["x"] < 1650 and 670 <= point["y"] < 810)
        self.assertIsNone(PythonAutoOperator.ranked_loop_click_point("ranked_room", {"width":1920,"height":1080}, rules="sanma"))
