"""The OCR gate sees exactly the decoded pixels already used by OCR."""
import io
import unittest
from unittest.mock import patch
from PIL import Image
from screen_state import classify_screen, classify_screen_image


class SharedFrameTests(unittest.TestCase):
    def test_decoded_frame_matches_png_and_jpeg_sources_without_mutation(self):
        image = Image.new('RGB', (1920, 1080), (30, 42, 54))
        for fmt in ('PNG', 'JPEG'):
            output = io.BytesIO()
            image.save(output, format=fmt)
            data = output.getvalue()
            decoded = Image.open(io.BytesIO(data)).convert('RGB')
            pixels = decoded.tobytes()
            self.assertEqual(classify_screen(data, {}), classify_screen_image(decoded, {}))
            self.assertEqual(decoded.tobytes(), pixels)

    def test_board_screen_gate_uses_already_decoded_frame(self):
        import board_metadata
        frame = Image.new('RGB', (1920, 1080), (30, 42, 54))
        with patch('PIL.Image.open', return_value=frame) as opened, \
             patch('screen_state.classify_screen_image', return_value=('unknown', 0.0)) as gate:
            result = board_metadata.recognize_board('unused.png', sanma_compact_candidate=False)
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(gate.call_args.args[0].tobytes(), frame.tobytes())
        self.assertEqual(result['reason'], 'not_gameplay_screen')


if __name__ == '__main__':
    unittest.main()
