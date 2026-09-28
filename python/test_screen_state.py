from pathlib import Path
import unittest

from screen_state import classify_screen


class RiichiSelectionScreenTest(unittest.TestCase):
    def test_dimmed_riichi_selection_remains_match(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(classify_screen(root / "artifacts/live/riichi-selection-dimmed-20260928.png", {}), ("match", 1.0))

    def test_friend_menu_without_tile_faces_is_not_match(self):
        root = Path(__file__).resolve().parents[1]
        self.assertNotEqual(classify_screen(root / "artifacts/live/friend-menu-no-hand-20260928.png", {})[0], "match")


if __name__ == "__main__":
    unittest.main()
