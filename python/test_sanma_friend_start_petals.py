"""Offline evidence184/187 replay; image binding, not independent ready OCR.

Fixtures are retained native screenshots, not generated positive examples.
Negative examples erase real glyphs or occupied slot content in those frames.
No browser, operator, live configuration or start click is used.
"""

import io
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from PIL import Image, ImageDraw

from friend_start import await_reviewed_friend_room, verified_friend_room


FIXTURES = Path(__file__).resolve().parents[1] / "test/fixtures/friend-start-petals"
PAIRS = (("184-reviewed.png", "184-current.png"),
         ("187-reviewed.png", "187-current.png"),
         ("187-reviewed-2.png", "187-current-2.png"))


def erased(frame, box):
    with Image.open(io.BytesIO(frame)) as source:
        image = source.convert("RGB")
    ImageDraw.Draw(image).rectangle(box, fill="black")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class SanmaFriendPetalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Deliberately no skip: committed evidence must be available in CI.
        cls.room184 = ((FIXTURES / PAIRS[0][0]).read_bytes(),
                       (FIXTURES / PAIRS[0][1]).read_bytes())
        cls.pairs = [(name, (FIXTURES / name).read_bytes(),
                      (FIXTURES / current).read_bytes()) for name, current in PAIRS[1:]]
        cls.next_frames = {
            "187-reviewed.png": (FIXTURES / "187-next.png").read_bytes(),
            "187-reviewed-2.png": (FIXTURES / "187-next-2.png").read_bytes(),
        }

    def test_fixtures_match_retained_evidence_hashes(self):
        manifest = json.loads((FIXTURES / "sources.json").read_text())
        self.assertEqual(set(manifest), {path.name for path in FIXTURES.glob("*.png")})
        for name, record in manifest.items():
            with self.subTest(fixture=name):
                self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(),
                                 record["sha256"])

    def test_petal_over_rule_glyph_is_not_accepted_as_background(self):
        # evidence184's petal overlaps 飛び; accepting it would weaken rule binding.
        reviewed, current = self.room184
        self.assertFalse(verified_friend_room(current, reviewed, sanma=True))
        self.assertFalse(verified_friend_room(reviewed, current, sanma=True))

    def test_retained_petals_match_in_both_directions(self):
        for name, reviewed, current in self.pairs:
            with self.subTest(evidence=name):
                self.assertNotEqual(reviewed, current)
                self.assertTrue(verified_friend_room(current, reviewed, sanma=True))
                self.assertTrue(verified_friend_room(reviewed, current, sanma=True))

    def test_original_decoration_masks_reproduce_187_rejections(self):
        original_boxes = ((1642, 367, 1674, 395), (1834, 335, 1866, 351))
        with patch("friend_start._SANMA_SETTINGS_DECORATION", original_boxes):
            for name, reviewed, current in self.pairs:
                with self.subTest(evidence=name):
                    self.assertFalse(verified_friend_room(current, reviewed, sanma=True))
                    self.assertFalse(verified_friend_room(reviewed, current, sanma=True))

    def test_each_room_digit_and_setting_remains_bound(self):
        changes = {
            **{f"room_digit_{index + 1}": (970 + index * 24, 72,
                                          989 + index * 24, 107)
               for index in range(5)},
            "player_count": (1670, 187, 1805, 218),
            "east_round": (1680, 225, 1800, 257),
            "clock": (1670, 260, 1810, 290),
            "start_score": (1704, 354, 1779, 380),
            "required_score": (1704, 429, 1779, 455),
            "required_score_label_glyph_tail": (1802, 420, 1817, 428),
            "tobi": (1710, 503, 1768, 530),
            "red_dora": (1691, 578, 1788, 605),
            "tsumo_loss": (1710, 652, 1768, 679),
            "kuitan": (1710, 727, 1768, 754),
            "shibari": (1684, 800, 1796, 827),
            "display": (1710, 876, 1768, 894),
        }
        for name, reviewed, current in self.pairs:
            for field, box in changes.items():
                with self.subTest(evidence=name, field=field):
                    self.assertFalse(verified_friend_room(erased(current, box), reviewed,
                                                         sanma=True))

    def test_each_ready_identity_cpu_and_occupied_slot_remains_bound(self):
        for name, reviewed, current in self.pairs:
            for slot, offset in enumerate((0, 390, 770), start=1):
                for field, box in {
                    "ready": (265 + offset, 700, 380 + offset, 760),
                    "identity_or_cpu": (166 + offset, 846, 312 + offset, 882),
                    "occupied_slot": (85 + offset, 650, 430 + offset, 900),
                }.items():
                    with self.subTest(evidence=name, slot=slot, field=field):
                        self.assertFalse(verified_friend_room(erased(current, box), reviewed,
                                                             sanma=True))

    def test_controls_remain_calibrated_even_when_both_images_change(self):
        for name, reviewed, current in self.pairs:
            for box in ((190, 45, 360, 115), (1000, 955, 1280, 1040)):
                changed = erased(current, box)
                with self.subTest(evidence=name, box=box):
                    self.assertFalse(verified_friend_room(changed, reviewed, sanma=True))
                    self.assertFalse(verified_friend_room(changed, changed, sanma=True))

    def test_count_and_clock_are_calibrated_not_merely_equal(self):
        for name, _, current in self.pairs:
            for box in ((1670, 187, 1805, 218), (1670, 260, 1810, 290)):
                changed = erased(current, box)
                with self.subTest(evidence=name, box=box):
                    self.assertFalse(verified_friend_room(changed, changed, sanma=True))

    def test_other_room_and_default_yonma_path_reject(self):
        room184 = self.room184[0]
        for name, reviewed, current in self.pairs:
            with self.subTest(evidence=name):
                self.assertFalse(verified_friend_room(current, reviewed))
                self.assertFalse(verified_friend_room(current, reviewed, sanma=False))
                if name.startswith("187"):
                    self.assertFalse(verified_friend_room(current, room184, sanma=True))
                    self.assertFalse(verified_friend_room(room184, current, sanma=True))

    def test_invalid_and_non_native_images_reject_in_either_position(self):
        reviewed = self.pairs[0][1]
        output = io.BytesIO()
        Image.new("RGB", (960, 540)).save(output, format="PNG")
        for invalid in (b"", b"not an image", output.getvalue(), reviewed[:128]):
            with self.subTest(length=len(invalid)):
                self.assertFalse(verified_friend_room(invalid, reviewed, sanma=True))
                self.assertFalse(verified_friend_room(reviewed, invalid, sanma=True))

    def test_two_fresh_captures_and_mismatch_resets_streak_without_click(self):
        for name, reviewed, current in self.pairs:
            with self.subTest(evidence=name):
                next_frame = self.next_frames[name]
                self.assertNotEqual(current, next_frame)
                page = Mock()
                page.screenshot.side_effect = [current, next_frame]
                on_capture = Mock()
                self.assertEqual(await_reviewed_friend_room(
                    page, reviewed, attempts=2, sanma=True, on_capture=on_capture), 2)
                self.assertEqual(page.screenshot.call_args_list,
                                 [call(animations="disabled")] * 2)
                self.assertEqual(on_capture.call_args_list,
                                 [call(1, current, True), call(2, next_frame, True)])
                page.mouse.click.assert_not_called()

                changed = erased(current, (1704, 354, 1779, 380))
                page.reset_mock()
                page.screenshot.side_effect = [current, changed, current, next_frame]
                self.assertEqual(await_reviewed_friend_room(
                    page, reviewed, attempts=4, sanma=True), 4)
                self.assertEqual(page.screenshot.call_count, 4)
                self.assertEqual(page.wait_for_timeout.call_args_list, [call(100)] * 3)
                page.mouse.click.assert_not_called()

                page.reset_mock()
                page.screenshot.side_effect = [current, changed, current]
                with self.assertRaisesRegex(RuntimeError, "consecutive captures"):
                    await_reviewed_friend_room(page, reviewed, attempts=3, sanma=True)
                page.mouse.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
