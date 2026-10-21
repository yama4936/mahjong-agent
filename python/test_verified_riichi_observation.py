import argparse
import copy
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from auto_operator import PythonAutoOperator

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'test/fixtures'
FRAME = FIXTURES / 'black-client-20261021.png'


class VerifiedRiichiObservationTest(unittest.TestCase):
    def setUp(self):
        self.cases = json.loads((FIXTURES / 'false-river-riichi-20261021.json').read_text())['cases']
        self.op = PythonAutoOperator.__new__(PythonAutoOperator)
        self.op.public_state = json.loads((ROOT / 'examples/public-unknown.json').read_text())
        self.op.log = Mock()

    def apply(self, case, *, metadata=None, observation=None):
        with patch('board_metadata.recognize_riichi_sticks', return_value=[]):
            return self.op.frame_metadata_state(
                FRAME, copy.deepcopy(observation if observation is not None else case['reconstructedObservation']),
                prepared_metadata=copy.deepcopy(metadata if metadata is not None else case['metadata']))

    def test_actual_phantom_river_flag_does_not_reach_verified_decisions(self):
        for case in self.cases:
            with self.subTest(source=case['sourceTimestamp']):
                self.setUp()
                raw = copy.deepcopy(case['reconstructedObservation'])
                original = copy.deepcopy(raw)
                public_before = copy.deepcopy(self.op.public_state)
                with patch('board_metadata.recognize_riichi_sticks', return_value=[]):
                    state, observed, _ = self.op.frame_metadata_state(FRAME, raw, prepared_metadata=case['metadata'])
                declarations = {o['seat'] for o in observed['opponentDiscards'] if o.get('riichiDeclared')}
                self.assertEqual(declarations, set(case['metadata']['riichiSeats']))
                self.assertEqual(raw, original)
                self.assertEqual(self.op.public_state, public_before)
                for before, after in zip(raw['opponentDiscards'], observed['opponentDiscards']):
                    self.assertEqual({k:v for k,v in before.items() if k != 'riichiDeclared'},
                                     {k:v for k,v in after.items() if k != 'riichiDeclared'})
                self.assertEqual(state['scores'], case['state']['scores'])

    def test_conserved_payment_and_occluded_stick_preserve_real_riichi(self):
        before, after = self.cases
        self.apply(before)
        hidden = copy.deepcopy(after['metadata']); hidden['riichiSeats'] = []
        raw = copy.deepcopy(after['reconstructedObservation'])
        raw['opponentDiscards'][1]['riichiDeclared'] = False
        for _ in range(2):
            state, observed, _ = self.apply(after, metadata=hidden, observation=raw)
            self.assertTrue(next(o for o in state['opponents'] if o['seat'] == 'west')['riichi'])
            self.assertEqual({o['seat'] for o in observed['opponentDiscards'] if o.get('riichiDeclared')}, {'west'})
        self.assertEqual(self.op.riichi_metadata_history['riichiSeats'], ['west'])

    def test_own_river_flag_requires_evidence_but_real_own_payment_survives(self):
        before = self.cases[0]
        raw = copy.deepcopy(before['reconstructedObservation']); raw['ownRiichiDeclared'] = True
        _, observed, _ = self.apply(before, observation=raw)
        self.assertFalse(observed['ownRiichiDeclared'])
        meta = copy.deepcopy(before['metadata']); meta['scores']['east'] -= 1000; meta['riichiSticks'] = 1
        raw['ownRiichiDeclared'] = False
        for _ in range(2):
            state, observed, _ = self.apply(before, metadata=meta, observation=raw)
            self.assertTrue(state['riichiDeclared'])
            self.assertTrue(observed['ownRiichiDeclared'])

    def test_flags_are_filtered_after_actual_seat_remapping(self):
        case = self.cases[1]
        meta = {**copy.deepcopy(case['metadata']), 'seat':'west',
                'scores':{'west':25000, 'north':25000, 'east':24000, 'south':25000},
                'riichiSeats':['east']}
        state, observed, _ = self.apply(case, metadata=meta)
        self.assertEqual(state['seat'], 'west')
        self.assertEqual({o['seat'] for o in observed['opponentDiscards'] if o.get('riichiDeclared')}, {'east'})
        self.assertFalse(next(o for o in observed['opponentDiscards'] if o['seat'] == 'north')['riichiDeclared'])

    def test_real_resident_request_cannot_restore_cached_phantom_flag(self):
        case = self.cases[1]
        original = copy.deepcopy(case['reconstructedObservation'])
        self.op.args = argparse.Namespace(board_metadata=True)
        self.op.current_board_metadata = Mock(return_value=case['metadata'])
        self.op.poll_public_recognition = Mock()
        self.op.cached_public_observation = original
        self.op.action_deadline_remaining_ms = lambda: 300000
        self.op.recognition_request_id = 0
        self.op.recognition_server = Mock()
        self.op.recognition_server.poll.return_value = None
        self.op.recognition_server.stdin = io.StringIO()
        self.op.recognition_server.stdout = io.StringIO('{"id":1,"result":{}}\n')
        with patch('board_metadata.recognize_riichi_sticks', return_value=[]):
            self.op.recognize_resident(FRAME, evaluate_force_auto=True)
        request = json.loads(self.op.recognition_server.stdin.getvalue())
        self.assertEqual({o['seat'] for o in request['publicObservation']['opponentDiscards'] if o.get('riichiDeclared')}, {'west'})
        self.assertEqual(self.op.cached_public_observation, case['reconstructedObservation'])

    def test_reaction_subprocess_receives_the_same_verified_flags(self):
        case = self.cases[1]
        with tempfile.TemporaryDirectory() as directory:
            self.op.frames = Path(directory)
            self.op.root = ROOT
            self.op.state_path = ROOT / 'examples/public-unknown.json'
            self.op.layout_path = ROOT / 'config/layout-300-regression.json'
            self.op.templates = ROOT / 'templates/bootstrap'
            self.op.args = argparse.Namespace(board_metadata=True, mode='force-auto', action_templates='', evaluation_timeout=30)
            self.op.evaluator_env = {}
            def run(command, **kwargs):
                observation = json.loads(Path(command[3]).read_text())
                self.assertEqual({o['seat'] for o in observation['opponentDiscards'] if o.get('riichiDeclared')}, {'west'})
                return subprocess.CompletedProcess(command, 0, stdout='{"status":"not_ready"}', stderr='')
            with patch('board_metadata.recognize_riichi_sticks', return_value=[]), patch('auto_operator.subprocess.run', side_effect=run):
                self.op.evaluate(FRAME, {'tile':'6p','fromSeat':'south'}, case['reconstructedObservation'],
                                 {'tiles':case['state']['hand']}, ['pon','pass'], prepared_metadata=case['metadata'])


if __name__ == '__main__':
    unittest.main()
