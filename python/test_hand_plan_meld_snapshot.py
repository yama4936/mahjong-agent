"""The delayed public worker must receive one immutable hand/meld context."""
import copy
import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image
from auto_operator import PythonAutoOperator


class HandPlanMeldSnapshotTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        op = self.operator = PythonAutoOperator.__new__(PythonAutoOperator)
        op.frames = Path(temporary.name)
        op.public_recognition_server = Mock()
        op.public_recognition_server.poll.return_value = None
        op.public_recognition_thread = None
        op.public_recognition_lock = threading.Lock()
        op.public_cache_last_frame_hash = None
        op.public_recognition_request_id = 0
        op.public_cache_generation = 7
        op.cached_open_melds = 1
        op.cached_concealed_tiles = ["2s", "3s", "4s", "4s", "5s", "5s", "6s", "6s", "9s", "9s"]
        op.public_state = {"seat": "east", "round": "east_1"}
        op.cached_public_observation = {"ownMeldsObserved": True,
            "ownMelds": [{"type": "chi", "tiles": ["7m", "6m", "8m"]}]}
        op.request_public_recognition = Mock(return_value={})
        image = io.BytesIO()
        Image.new("RGB", (1920, 1080)).save(image, "PNG")
        self.frame = image.getvalue()

    def queue(self, include=True):
        with patch("auto_operator.threading.Thread") as thread:
            thread.return_value.is_alive.return_value = False
            self.operator.schedule_public_recognition(self.frame, force=True,
                verified_match=True, include_hand_plan=include)
            callback = thread.call_args.kwargs["target"]
        return callback

    def test_delayed_worker_uses_original_hand_meld_seat_round_and_generation(self):
        op = self.operator
        original = copy.deepcopy(op.cached_public_observation["ownMelds"])
        hand = list(op.cached_concealed_tiles)
        callback = self.queue()
        op.cached_concealed_tiles[0] = "P"
        op.cached_public_observation["ownMelds"][0]["tiles"][0] = "P"
        op.cached_open_melds = 2
        op.public_state.update(seat="south", round="east_2")
        op.public_cache_generation = 8
        callback()
        request = op.request_public_recognition.call_args.args[0]
        self.assertEqual(request["concealedTiles"], hand)
        self.assertEqual(request["melds"], original)
        self.assertEqual(request["openMelds"], 1)
        self.assertEqual(request["seat"], "east")
        self.assertEqual(request["round"], "east_1")
        self.assertEqual(op.public_recognition_result["generation"], 7)

    def test_unknown_partial_or_count_mismatch_does_not_claim_typed_melds(self):
        for observation in (None, {}, {"ownMeldsObserved": False, "ownMelds": []},
                            {"ownMeldsObserved": True, "ownMelds": []},
                            {"ownMeldsObserved": True, "ownMelds": None}):
            with self.subTest(observation=observation):
                self.operator.cached_public_observation = observation
                callback = self.queue()
                callback()
                request = self.operator.request_public_recognition.call_args.args[0]
                self.assertNotIn("melds", request)
                self.assertEqual(request["openMelds"], 1)

    def test_startup_without_hand_plan_does_not_send_partial_plan_fields(self):
        self.queue(include=False)()
        request = self.operator.request_public_recognition.call_args.args[0]
        for name in ("melds", "concealedTiles", "openMelds", "seat", "round"):
            self.assertNotIn(name, request)


if __name__ == "__main__":
    unittest.main()
