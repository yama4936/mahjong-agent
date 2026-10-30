"""Unverified three-player reactions must never reach physical input."""
import argparse
import unittest
from unittest.mock import Mock

from auto_operator import PythonAutoOperator


class SanmaReactionExecutionGuardTest(unittest.TestCase):
    def setUp(self):
        self.operator = PythonAutoOperator.__new__(PythonAutoOperator)
        self.operator.args = argparse.Namespace(rules="sanma", mode="force-auto", accept_single_call=True)
        self.page = Mock()

    def test_direct_reaction_entrypoints_reject_sanma_before_reading_page(self):
        calls = [
            lambda: self.operator.execute_reaction_pass(self.page, {}),
            lambda: self.operator.execute_force_auto_call(self.page, b"untrusted", {}),
            lambda: self.operator.execute_force_auto_reaction_win(self.page, b"untrusted", {}),
        ]
        for call in calls:
            with self.subTest(call=call), self.assertRaisesRegex(RuntimeError, "sanma execution"):
                call()
        self.page.mouse.click.assert_not_called()
        self.page.screenshot.assert_not_called()

    def test_pass_refuses_sanma_evaluation_even_when_configured_for_yonma(self):
        self.operator.args.rules = "yonma"
        for evidence in ({"state": {"rules": "sanma"}},
                         {"scope": "offline_untrusted_sanma_auto_observation"},
                         {"scope": "sanma_kita_confirmation_observation"}):
            with self.subTest(evidence=evidence), self.assertRaisesRegex(RuntimeError, "sanma execution"):
                self.operator.execute_reaction_pass(self.page, evidence)
        self.page.mouse.click.assert_not_called()

    def test_kita_cannot_be_confirmed_by_button_disappearance(self):
        with self.assertRaisesRegex(RuntimeError, "north removal and replacement draw"):
            self.operator.confirm_action_button(self.page, "kita", b"button")
        self.page.screenshot.assert_not_called()


if __name__ == "__main__":
    unittest.main()
