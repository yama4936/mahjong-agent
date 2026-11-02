"""The sanma OCR scheduling must not change the regular OCR engine."""
import sys
import types
import unittest
from unittest.mock import Mock, patch

import board_metadata


class SanmaOcrThreadsTest(unittest.TestCase):
    def tearDown(self):
        board_metadata.ocr_engine.cache_clear()

    def test_separate_cached_engines_and_thread_options(self):
        factory = Mock(side_effect=[object(), object()])
        with patch.dict(sys.modules, {'rapidocr': types.SimpleNamespace(RapidOCR=factory)}), \
                patch('board_metadata.os.cpu_count', return_value=8):
            board_metadata.ocr_engine.cache_clear()
            default = board_metadata.ocr_engine()
            sanma = board_metadata.ocr_engine(sanma_threads=True)
            self.assertIs(board_metadata.ocr_engine(), default)
            self.assertIs(board_metadata.ocr_engine(sanma_threads=True), sanma)
        self.assertEqual(factory.call_count, 2)
        factory.assert_any_call()
        factory.assert_any_call(params={
            'EngineConfig.onnxruntime.intra_op_num_threads': 4,
            'EngineConfig.onnxruntime.inter_op_num_threads': 4,
        })

    def test_threads_do_not_exceed_available_cpu_count(self):
        for available, expected in ((2, 2), (1, 1), (None, 1)):
            with self.subTest(available=available):
                factory = Mock(return_value=object())
                with patch.dict(sys.modules, {'rapidocr': types.SimpleNamespace(RapidOCR=factory)}), \
                        patch('board_metadata.os.cpu_count', return_value=available):
                    board_metadata.ocr_engine.cache_clear()
                    board_metadata.ocr_engine(sanma_threads=True)
                factory.assert_called_once_with(params={
                    'EngineConfig.onnxruntime.intra_op_num_threads': expected,
                    'EngineConfig.onnxruntime.inter_op_num_threads': expected,
                })


if __name__ == '__main__':
    unittest.main()
