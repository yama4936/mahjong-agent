"""Bounded upright OCR recovery for the 2026-10-29 left-score highlight."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from board_metadata import recognize_score


def reading(text="22600", confidence=0.99999):
    return SimpleNamespace(txts=[text], scores=[confidence])


class LeftScoreConsensusTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.frame = Path(self.directory.name) / "frame.png"
        Image.new("RGB", (1920, 1080)).save(self.frame)

    def test_low_primary_requires_two_high_confidence_matching_retries(self):
        engine = Mock(side_effect=[reading(confidence=0.97512),
                                   reading(confidence=0.99976), reading(confidence=0.99999)])
        with patch("board_metadata.ocr_engine", return_value=engine):
            self.assertEqual(recognize_score(self.frame, "left"), 22600)
        self.assertEqual([call.args[0].shape[1] for call in engine.call_args_list], [412, 360, 480])

    def test_disagreement_low_confidence_and_missing_readings_are_rejected(self):
        for first, second in (
            (reading("22600"), reading("22500")),
            (reading(confidence=0.97999), reading()),
            (reading(), reading(confidence=0.97999)),
            (SimpleNamespace(txts=None, scores=None), reading()),
            (reading(), SimpleNamespace(txts=[], scores=[])),
            (reading(), SimpleNamespace(txts=["22600"], scores=[])),
            (reading(), reading("garbage")),
            (reading(), reading(confidence=float("nan"))),
            (reading(), reading(confidence=float("inf"))),
            (reading(), reading(confidence=1.1)),
            (reading(), reading(confidence=None)),
            (reading(), reading(confidence="invalid")),
            (reading(), reading(text=22600)),
        ):
            with self.subTest(first=first, second=second):
                engine = Mock(side_effect=[reading(confidence=0.97512), first, second])
                with patch("board_metadata.ocr_engine", return_value=engine):
                    self.assertIsNone(recognize_score(self.frame, "left"))
                self.assertEqual(engine.call_count, 3)

    def test_high_confidence_primary_has_no_additional_ocr(self):
        engine = Mock(return_value=reading(confidence=0.99047))
        with patch("board_metadata.ocr_engine", return_value=engine):
            self.assertEqual(recognize_score(self.frame, "left"), 22600)
        self.assertEqual(engine.call_count, 1)

    def test_other_positions_do_not_retry(self):
        for position in ("own", "right", "opposite"):
            with self.subTest(position=position):
                engine = Mock(return_value=reading(confidence=0.97512))
                with patch("board_metadata.ocr_engine", return_value=engine):
                    self.assertIsNone(recognize_score(self.frame, position))
                self.assertEqual(engine.call_count, 1)


if __name__ == "__main__":
    unittest.main()
