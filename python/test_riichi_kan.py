import argparse
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import Mock
from auto_operator import (PythonAutoOperator, RetryableSafetyAbort, force_auto_riichi_kan_prompt,
                           force_auto_self_action_buttons, force_auto_reaction_win_button)

FIXTURES = Path(__file__).resolve().parents[1] / 'test/fixtures'
ROOT = Path(__file__).resolve().parents[1]


class RiichiKanPassTest(unittest.TestCase):
    def setUp(self):
        self.op = PythonAutoOperator.__new__(PythonAutoOperator)
        self.op.args = argparse.Namespace(mode='force-auto', action_templates='', stability_pixel_delta=1.5)
        self.op.layout = json.loads((ROOT / 'config/layout-300-regression.json').read_text())
        self.op.layout['actionButtonRegions'] = json.loads((ROOT / 'config/layout.json').read_text())['actionButtonRegions']
        self.source = FIXTURES / 'riichi-kan-prompt-20261022.jpg'
        self.evaluation = json.loads((FIXTURES / 'riichi-kan-prompt-20261022.json').read_text())['evaluation']

    def test_original_jpeg_prompt_routes_discard_to_pass_without_new_recognition(self):
        for source in [self.source, FIXTURES / 'riichi-kan-prompt-later-20261022.jpg']:
            frame = source.read_bytes()
            self.assertEqual(force_auto_self_action_buttons(frame, self.op.layout['viewport']), [])
            self.assertIsNone(force_auto_reaction_win_button(frame, self.op.layout['viewport'], self.op.layout['actionButtonRegions']['pass']))
            result = self.op.force_auto_riichi_kan_fallback(source, self.evaluation)
            self.assertEqual(result['status'], 'reaction_prompt')
            self.assertEqual(result['availableUiActions'], ['kan', 'pass'])
            self.assertEqual(result['decision']['selectedAction']['action'], 'pass')
            self.assertEqual(result['actionButton']['center'], {'x': 1307.5, 'y': 827.5})
            self.assertEqual(len(result['recognition']['tiles']), 14)

    def test_no_pass_override_without_matching_riichi_quad_hand_evidence(self):
        for case in ['not_riichi', 'open', 'tsumo', 'ankan', 'thirteen', 'different_hand', 'draw_not_fourth', 'advisor']:
            with self.subTest(case=case):
                self.setUp()
                e = copy.deepcopy(self.evaluation)
                if case == 'not_riichi': e['state']['riichiDeclared'] = False
                if case == 'open': e['state']['openMelds'] = 1
                if case in ['tsumo', 'ankan']: e['decision']['selectedAction']['action'] = case
                if case == 'thirteen': e['recognition']['tiles'].pop()
                if case == 'different_hand': e['recognition']['tiles'][0] = 'P'
                if case == 'draw_not_fourth':
                    e['state']['draw'] = 'F'
                    e['recognition']['tiles'][-1] = 'F'
                if case == 'advisor': self.op.args.mode = 'advisor'
                self.assertIsNone(self.op.force_auto_riichi_kan_fallback(self.source, e))

    def test_native_dismissed_and_orange_controls_are_not_kan_prompts(self):
        for name in ['riichi-kan-dismissed-20261022.png', 'riichi-kan-orange-control-20261022.jpg']:
            frame = (FIXTURES / name).read_bytes()
            self.assertIsNone(force_auto_riichi_kan_prompt(frame, self.op.layout['viewport'], self.op.layout['actionButtonRegions']['pass']))
            self.assertIsNone(self.op.force_auto_riichi_kan_fallback(FIXTURES / name, self.evaluation))

    def prepare_pass(self, frames):
        result = self.op.force_auto_riichi_kan_fallback(self.source, self.evaluation)
        self.op.screencast_session = None
        self.op.require_force_auto_click_budget = Mock()
        self.op.require_action_deadline = Mock()
        self.op.log = Mock()
        self.op.confirm_action_button = Mock(return_value={'confirmation': 'action_button_region_changed'})
        page = Mock()
        page.screenshot.side_effect = frames
        return result, page

    def test_pass_requires_fresh_complete_prompt_and_confirms_button_disappearance(self):
        result, page = self.prepare_pass([self.source.read_bytes()] * 2)
        receipt = self.op.execute_reaction_pass(page, result, evaluated_captured_at=1.0)
        self.assertEqual(receipt['action'], 'pass')
        self.assertNotIn('discardedTile', receipt)
        page.mouse.click.assert_called_once_with(1307.5, 827.5)
        self.op.confirm_action_button.assert_called_once()
        self.op.require_action_deadline.assert_called_once()

    def test_disappearing_prompt_or_new_orange_action_prevents_click(self):
        for name in ['riichi-kan-dismissed-20261022.png', 'riichi-kan-orange-control-20261022.jpg']:
            with self.subTest(name=name):
                self.setUp()
                result, page = self.prepare_pass([self.source.read_bytes(), (FIXTURES / name).read_bytes()])
                with self.assertRaises(RetryableSafetyAbort):
                    self.op.execute_reaction_pass(page, result, evaluated_captured_at=1.0)
                page.mouse.click.assert_not_called()
                self.op.confirm_action_button.assert_not_called()
