import argparse
import unittest
from unittest.mock import Mock
from auto_operator import PythonAutoOperator

class SanmaExecutionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.operator=object.__new__(PythonAutoOperator)
        self.operator.args=argparse.Namespace(mode='force-auto',rules='yonma')
        self.page=Mock()

    def test_missing_unknown_and_kita_never_click_even_without_sanma_state(self):
        for decision in ({}, {'selectedAction':{}}, {'selectedAction':{'action':'kita'}},
                         {'selectedAction':{'action':'unknown'}}, {'selectedAction':{'action':[]}},
                         {'recommendedAction':'kita'}):
            with self.subTest(decision=decision), self.assertRaisesRegex(RuntimeError,'supported action|unsupported action'):
                self.operator.execute(self.page,{'state':{},'decision':decision,'recognition':{}})
            self.page.mouse.click.assert_not_called()

    def test_untrusted_receipt_and_sanma_settings_never_click(self):
        for scope in ('offline_untrusted_sanma_auto_observation','sanma_self_turn_observation'):
            with self.subTest(scope=scope), self.assertRaisesRegex(RuntimeError,'sanma execution'):
                self.operator.execute(self.page,{'scope':scope,'decision':{'selectedAction':{'action':'tsumo'}},'recognition':{}})
        self.operator.args.rules='sanma'
        with self.assertRaisesRegex(RuntimeError,'sanma execution'):
            self.operator.execute(self.page,{'state':{},'decision':{'selectedAction':{'action':'discard'}},'recognition':{}})
        self.page.mouse.click.assert_not_called()

    def test_supported_yonma_advisor_remains_non_clicking(self):
        self.operator.args=argparse.Namespace(mode='advisor',rules='yonma',allow_local_discard=False,
            action_deadline_ms=300000,force_auto_click_budget_ms=None)
        self.operator.configured_action_deadline_ms=Mock(return_value=300000)
        self.operator.force_auto_click_budget_ms=Mock(return_value=None)
        result=self.operator.execute(self.page,{'state':{'rules':'yonma'},
            'decision':{'selectedAction':{'action':'discard','tile':'1m'}},'recognition':{}})
        self.assertEqual(result,{'clicked':False,'reason':'advisor_or_safety_stop'})
        self.page.mouse.click.assert_not_called()
