from pathlib import Path
import unittest

from PIL import Image, ImageDraw

from screen_state import _matches_blocking_dialog, classify_screen


class RiichiSelectionScreenTest(unittest.TestCase):
    def test_live_rank_progress_and_reward_are_not_matchmaking(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(classify_screen(root / "artifacts/live/ranked-rank-progress-20261006.png", {}),
                         ("rank_progress", 1.0))
        self.assertEqual(classify_screen(root / "artifacts/live/ranked-post-match-reward-20261006.png", {}),
                         ("post_match_reward", 1.0))

    def test_informational_dialog_is_not_a_connection_error(self):
        reference = Image.new("RGB", (1920, 1080), (26, 37, 67))
        message = (595, 455, 1335, 584)
        other_message = reference.copy()
        ImageDraw.Draw(other_message).rectangle(message, fill=(46, 57, 87))
        self.assertTrue(_matches_blocking_dialog(reference, reference))
        self.assertFalse(_matches_blocking_dialog(other_message, reference))

    def test_login_screen_is_not_matchmaking(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(classify_screen(root / "artifacts/live/login-screen-20261005.png", {}), ("login", 1.0))

    def test_authentication_dialog_is_not_matchmaking(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(classify_screen(root / "artifacts/live/account-modal-20261005.png", {}),
                         ("account_modal", 1.0))

    def test_dimmed_riichi_selection_remains_match(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(classify_screen(root / "artifacts/live/riichi-selection-dimmed-20260928.png", {}), ("match", 1.0))

    def test_friend_menu_without_tile_faces_is_not_match(self):
        root = Path(__file__).resolve().parents[1]
        self.assertNotEqual(classify_screen(root / "artifacts/live/friend-menu-no-hand-20260928.png", {})[0], "match")


if __name__ == "__main__":
    unittest.main()
