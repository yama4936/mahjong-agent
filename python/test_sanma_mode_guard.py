"""Sanma selection stops before an operator, browser or dashboard can start."""
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import auto_operator

ROOT = Path(__file__).resolve().parents[1]
BASE = ['auto_operator.py', '--layout', 'layout.json', '--templates', 'tiles', '--state', 'state.json']


class SanmaModeGuardTests(unittest.TestCase):
    def test_default_and_explicit_yonma_parse_unchanged(self):
        for extra in ([], ['--rules', 'yonma'], ['--rules=yonma', '--ranked-loop']):
            with self.subTest(extra=extra), patch('sys.argv', BASE + extra):
                self.assertEqual(auto_operator.parse_args().rules, 'yonma')

    def test_sanma_stops_before_lease_and_browser_for_all_modes(self):
        for mode in ('observer', 'advisor', 'auto', 'force-auto'):
            for extra in ([], ['--ranked-loop'], ['--rules=yonma']):
                stderr = io.StringIO()
                with self.subTest(mode=mode, extra=extra), \
                        patch('sys.argv', BASE + ['--rules', 'sanma', '--mode', mode] + extra), \
                        patch('sys.stderr', stderr), patch('auto_operator.operator_lease') as lease, \
                        patch('auto_operator.PythonAutoOperator') as operator, \
                        patch('auto_operator.sync_playwright') as browser, \
                        self.assertRaises(SystemExit) as raised:
                    auto_operator.main()
                self.assertEqual(raised.exception.code, 2)
                self.assertIn('sanma automatic decisions and screen operation are not implemented', stderr.getvalue())
                lease.assert_not_called()
                operator.assert_not_called()
                browser.assert_not_called()

    def test_node_launcher_rejects_before_environment_or_children(self):
        for args in (['--rules', 'sanma'], ['--rules=sanma', '--ranked-loop'],
                     ['--rules=sanma', '--rules=yonma']):
            with self.subTest(args=args):
                result = subprocess.run(['node', str(ROOT / 'scripts/run-operator.mjs'), 'force-auto', *args],
                                        cwd=ROOT, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertIn('sanma automatic decisions and screen operation are not implemented', result.stderr)
                self.assertNotIn('environment is missing', result.stderr)
