"""Exercise win-input deadline/session changes using a saved match frame.

The image is a real ron frame; action detection is supplied by the receipt, so
this exercises click timing, not tsumo visual recognition.
"""
import time
import unittest
from unittest.mock import patch

import test_sanma_friend_ron_click as fixture


@unittest.skipUnless(fixture.BEFORE.exists() and fixture.AFTER.exists() and fixture.REFS.exists(),
                     'saved image or screen references unavailable')
class SanmaWinDeadlineTest(unittest.TestCase):
    def make_case(self, action):
        case = fixture.SanmaFriendRonTest()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.receipt['sourceObservation']['report']['buttonRow']['value']['slots'][1]['action'] = action
        return case

    def test_normal_win_and_delayed_revocations(self):
        for action in ('ron', 'tsumo'):
            for stage in ('normal', 'log_deadline', 'log_session', 'latch_deadline', 'latch_session'):
                with self.subTest(action=action, stage=stage):
                    case = self.make_case(action)
                    clock = {'offset': 0}
                    monotonic = time.monotonic
                    def expire():
                        if stage.endswith('deadline'):
                            clock['offset'] = 301
                        else:
                            case.operator.verified_friend_300_active = False
                    def log(event, **kwargs):
                        if event == 'sanma_friend_candidate_click' and stage.startswith('log_'):
                            expire()
                    def latch(*args):
                        if stage.startswith('latch_'):
                            expire()
                    case.operator.log.side_effect = log
                    operation = getattr(case.operator, f'execute_sanma_friend_{action}_candidate')
                    with patch('auto_operator.time.monotonic', side_effect=lambda: monotonic() + clock['offset']), \
                         patch('auto_operator.latch_friend_action_target', side_effect=latch):
                        if stage == 'normal':
                            operation(case.page, case.receipt)
                            case.page.mouse.click.assert_called_once()
                        else:
                            with self.assertRaisesRegex(RuntimeError, 'session or timing expired'):
                                operation(case.page, case.receipt)
                            case.page.mouse.click.assert_not_called()
