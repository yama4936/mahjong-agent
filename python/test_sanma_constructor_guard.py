import argparse
import unittest
from unittest.mock import patch
from auto_operator import PythonAutoOperator

class SanmaConstructorGuardTests(unittest.TestCase):
    def test_direct_sanma_construction_rejects_before_files_or_children(self):
        args = argparse.Namespace(rules="sanma")
        with patch("auto_operator.load_references") as refs, \
             patch("auto_operator.load_json") as load, \
             patch("auto_operator.subprocess.Popen") as spawn:
            with self.assertRaisesRegex(RuntimeError, "sanma automatic decisions"):
                PythonAutoOperator(args)
        refs.assert_not_called(); load.assert_not_called(); spawn.assert_not_called()
