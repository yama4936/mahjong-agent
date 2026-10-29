import base64
import io
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from synchronous_capture import capture_full_png


def image_bytes(size=(23, 17), format="PNG"):
    image = Image.new("RGB", size)
    image.putdata([(index % 256, index * 17 % 256, index * 71 % 256)
                   for index in range(size[0] * size[1])])
    stream = io.BytesIO()
    image.save(stream, format=format)
    return stream.getvalue()


class SynchronousCaptureTest(unittest.TestCase):
    def setUp(self):
        self.png = image_bytes()
        self.page = Mock()
        self.session = Mock()
        self.page.context.new_cdp_session.return_value = self.session
        self.session.send.return_value = {"data": base64.b64encode(self.png).decode()}
        self.page.screenshot.return_value = self.png

    def test_owned_session_returns_full_lossless_pixels_and_detaches(self):
        with patch("synchronous_capture.time.monotonic", side_effect=[10, 11, 12]):
            result = capture_full_png(self.page, expected_size=(23, 17))
        self.assertEqual(result.png, self.png)
        self.assertEqual((result.width, result.height), (23, 17))
        self.assertEqual((result.attempt_started_at, result.started_at, result.completed_at),
                         (10, 11, 12))
        self.assertEqual(result.method, "cdp_png_fast")
        self.assertIsNone(result.fallback_reason)
        self.page.context.new_cdp_session.assert_called_once_with(self.page)
        self.session.send.assert_called_once_with("Page.captureScreenshot", {
            "format": "png", "fromSurface": True,
            "captureBeyondViewport": False, "optimizeForSpeed": True,
        })
        self.session.detach.assert_called_once()
        self.page.screenshot.assert_not_called()
        self.page.close.assert_not_called()

    def test_borrowed_session_is_never_detached_on_success_or_failure(self):
        for fails in (False, True):
            with self.subTest(fails=fails):
                self.session.send.side_effect = RuntimeError("closed") if fails else None
                result = capture_full_png(self.page, session=self.session)
                self.assertEqual(result.method, "playwright_png" if fails else "cdp_png_fast")
        self.session.detach.assert_not_called()
        self.page.context.new_cdp_session.assert_not_called()

    def test_protocol_failure_falls_back_without_resetting_attempt_budget(self):
        self.session.send.side_effect = RuntimeError("unknown optimizeForSpeed parameter")
        with patch("synchronous_capture.time.monotonic", side_effect=[10, 11, 15, 17]):
            result = capture_full_png(self.page, expected_size=(23, 17))
        self.assertEqual(result.attempt_started_at, 10)
        self.assertEqual(result.started_at, 15)
        self.assertEqual(result.completed_at - result.attempt_started_at, 7)
        self.assertEqual(result.method, "playwright_png")
        self.assertIn("unknown optimizeForSpeed", result.fallback_reason)
        self.session.detach.assert_called_once()
        self.page.screenshot.assert_called_once_with(animations="disabled")

    def test_attach_failure_uses_fallback_without_detaching_unknown_session(self):
        self.page.context.new_cdp_session.side_effect = RuntimeError("not Chromium")
        result = capture_full_png(self.page)
        self.assertEqual(result.png, self.png)
        self.assertIn("not Chromium", result.fallback_reason)
        self.session.detach.assert_not_called()

    def test_partial_lossy_corrupt_or_invalid_base64_results_are_not_admitted(self):
        for encoded in (base64.b64encode(image_bytes((22, 17))).decode(),
                        base64.b64encode(image_bytes(format="JPEG")).decode(),
                        base64.b64encode(self.png[:40]).decode(), "not base64!!"):
            with self.subTest(encoded=encoded[:30]):
                self.session.reset_mock()
                self.page.screenshot.reset_mock()
                self.session.send.return_value = {"data": encoded}
                result = capture_full_png(self.page, expected_size=(23, 17))
                self.assertEqual(result.png, self.png)
                self.assertEqual(result.method, "playwright_png")
                self.assertTrue(result.fallback_reason)
                self.session.detach.assert_called_once()
                self.page.screenshot.assert_called_once()

    def test_invalid_fallback_raises_and_never_returns_unvalidated_receipt(self):
        self.session.send.side_effect = RuntimeError("unsupported")
        self.page.screenshot.return_value = image_bytes((22, 17))
        with self.assertRaisesRegex(ValueError, "does not match expected"):
            capture_full_png(self.page, expected_size=(23, 17))
        self.session.detach.assert_called_once()

    def test_detach_failure_preserves_valid_capture_without_closing_page(self):
        self.session.detach.side_effect = RuntimeError("target already detached")
        result = capture_full_png(self.page)
        self.assertEqual(result.png, self.png)
        self.page.screenshot.assert_not_called()
        self.page.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
