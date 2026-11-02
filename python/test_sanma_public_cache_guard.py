import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from auto_operator import PythonAutoOperator


class SanmaPublicCacheGuardTest(unittest.TestCase):
    def test_sanma_never_promotes_even_a_mislabeled_four_player_result(self):
        op = PythonAutoOperator.__new__(PythonAutoOperator)
        op.args = SimpleNamespace(rules='sanma')
        op.cached_public_observation = {'ownDiscards': ['F']}
        op.observe_post_call_timeout_river = Mock()
        result = op.accept_public_observation({'ownDiscards': ['F', '9p'],
                                                'ownDiscardsObserved': True})
        self.assertFalse(result)
        self.assertEqual(op.cached_public_observation, {'ownDiscards': ['F']})
        op.observe_post_call_timeout_river.assert_not_called()

    def test_sanma_labeled_candidate_is_never_promoted_under_yonma_operator(self):
        op = PythonAutoOperator.__new__(PythonAutoOperator)
        op.args = SimpleNamespace(rules='yonma')
        self.assertFalse(op.accept_public_observation({'rules': 'sanma'}))

    def test_fallback_passes_sanma_rules_to_cli(self):
        from pathlib import Path
        from unittest.mock import patch
        op = PythonAutoOperator.__new__(PythonAutoOperator)
        op.args = SimpleNamespace(mode='force-auto', rules='sanma', evaluation_timeout=5)
        op.public_recognition_server = None
        op.public_state = {'seat': 'east'}
        op.layout_path = Path('layout.json')
        op.templates = Path('templates')
        op.root = Path('.')
        op.evaluator_env = {}
        op.log = Mock()
        completed = SimpleNamespace(returncode=0, stdout='{"rules":"sanma"}', stderr='')
        with patch('auto_operator.subprocess.run', return_value=completed) as run:
            self.assertEqual(op.observe_public_board(Path('frame.png')), {'rules': 'sanma'})
        self.assertIn('--rules=sanma', run.call_args.args[0])
        self.assertIn('--backend=hybrid', run.call_args.args[0])
