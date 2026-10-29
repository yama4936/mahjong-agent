"""Full-viewport, lossless captures without Playwright's page preparation.

This changes PNG compression only.  It does not reuse a screencast frame or
claim that the compositor rendered a new frame after a click.  Callers must
retain their selection/state checks and use ``attempt_started_at`` when
charging a capture (including fallback) against an action budget.
"""

import base64
from dataclasses import dataclass
import io
import time
from typing import Any

from PIL import Image


@dataclass(frozen=True)
class CaptureReceipt:
    png: bytes
    attempt_started_at: float
    started_at: float
    completed_at: float
    width: int
    height: int
    method: str
    fallback_reason: str | None = None


def _png_size(png: bytes, expected_size: tuple[int, int] | None) -> tuple[int, int]:
    with Image.open(io.BytesIO(png)) as image:
        if image.format != "PNG":
            raise ValueError("full capture must be lossless PNG")
        image.load()
        size = image.size
    if expected_size is not None and size != expected_size:
        raise ValueError(f"full capture size {size} does not match expected {expected_size}")
    return size


def capture_full_png(
    page: Any, *, session: Any = None, expected_size: tuple[int, int] | None = None,
) -> CaptureReceipt:
    """Capture the current full viewport, falling back to the established API.

    ``expected_size`` is in image pixels (CSS viewport size times DPR), not
    CSS pixels.  A mismatching or undecodable CDP result triggers fallback;
    an invalid fallback raises instead of admitting a partial image.

    A supplied CDP session is borrowed and never detached.  A session created
    here is always detached, even when capture/decoding fails.  No browser,
    page, viewport, DOM, or external session is closed or changed by this
    helper.  The fallback retains the caller's existing screenshot behavior.

    ``started_at`` belongs to the successful request.  ``attempt_started_at``
    precedes attachment and any failed request, so using it for the budget
    cannot forgive time consumed by fallback.  Neither timestamp proves the
    pixel contents' compositor age.
    """
    attempt_started_at = time.monotonic()
    active_session = session
    owns_session = session is None
    fallback_reason = None
    try:
        if owns_session:
            active_session = page.context.new_cdp_session(page)
        started_at = time.monotonic()
        result = active_session.send("Page.captureScreenshot", {
            "format": "png",
            "fromSurface": True,
            "captureBeyondViewport": False,
            "optimizeForSpeed": True,
        })
        png = base64.b64decode(result["data"], validate=True)
        width, height = _png_size(png, expected_size)
        completed_at = time.monotonic()
    except Exception as error:
        fallback_reason = f"{type(error).__name__}: {error}"
    finally:
        if owns_session and active_session is not None:
            try:
                active_session.detach()
            except Exception:
                # A completed capture remains usable if the target already
                # disappeared.  Never close the page/browser to clean up.
                pass
    if fallback_reason is None:
        return CaptureReceipt(png, attempt_started_at, started_at, completed_at,
                              width, height, "cdp_png_fast")

    started_at = time.monotonic()
    png = page.screenshot(animations="disabled")
    width, height = _png_size(png, expected_size)
    return CaptureReceipt(png, attempt_started_at, started_at, time.monotonic(),
                          width, height, "playwright_png", fallback_reason)
