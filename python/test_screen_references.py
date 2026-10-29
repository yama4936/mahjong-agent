import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from auto_operator import PythonAutoOperator, parse_args
from screen_state import load_references


class ScreenReferenceTest(unittest.TestCase):
    def test_missing_empty_and_unrecognized_directories_fail_with_remedy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for directory in (root / 'missing', root):
                with self.subTest(directory=directory):
                    with self.assertRaisesRegex(RuntimeError, '--screen-references') as error:
                        load_references(directory)
                    self.assertIn(str(directory), str(error.exception))
            Image.new('RGB', (32, 18)).save(root / 'unrelated.png')
            with self.assertRaisesRegex(RuntimeError, 'No screen-state reference'):
                load_references(root)

    def test_valid_reference_preserves_state_mapping(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            Image.new('RGB', (32, 18), 'red').save(root / 'lobby-ready.png')
            references = load_references(root)
            self.assertEqual(len(references), 1)
            state, image = next(iter(references.values()))
            self.assertEqual(state, 'lobby')
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))

    def test_corrupt_reference_identifies_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'lobby-ready.png'
            path.write_bytes(b'not a PNG')
            with self.assertRaisesRegex(RuntimeError, 'Invalid screen-state reference') as error:
                load_references(path.parent)
            self.assertIn(str(path), str(error.exception))

    def test_operator_rejects_empty_references_before_config_or_subprocess(self):
        with tempfile.TemporaryDirectory() as temporary:
            for custom in (None, Path(temporary) / 'custom'):
                args = argparse.Namespace(project=temporary, screen_references=custom)
                with patch('auto_operator.subprocess.Popen') as process:
                    with self.assertRaisesRegex(RuntimeError, 'No screen-state reference') as error:
                        PythonAutoOperator(args)
                    process.assert_not_called()
                self.assertIn(str(custom or Path(temporary) / 'artifacts/live'), str(error.exception))

    def test_cli_accepts_custom_directory(self):
        with patch('sys.argv', ['operator', '--layout', 'layout.json', '--templates', 'templates',
                                '--state', 'state.json', '--screen-references', 'reference images']):
            self.assertEqual(parse_args().screen_references, Path('reference images'))
