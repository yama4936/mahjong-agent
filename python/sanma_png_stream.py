"""Experimental, bounded PNG stream for one friend-match freshness capture."""
import base64
import io
import math
import time
from PIL import Image

class SanmaPngStream:
    def __init__(self, page, *, max_age=0.8, timeout=2.0):
        self.page = page
        self.max_age = max_age
        self.timeout = timeout
        self.session = None
        self.last_timestamp = None
        self.latest = None
        self.error = None
        self.last_wall = time.time()
        self.last_mono = time.monotonic()

    def start(self):
        self.session = self.page.context.new_cdp_session(self.page)
        self.session.on('Page.screencastFrame', self._receive)
        try:
            self.session.send('Page.startScreencast', {'format':'png','everyNthFrame':1})
        except Exception:
            self.close()
            raise

    def _receive(self, event):
        try:
            wall, mono = time.time(), time.monotonic()
            if abs((wall-self.last_wall)-(mono-self.last_mono)) > .1:
                raise ValueError('wall clock changed')
            self.last_wall, self.last_mono = wall, mono
            stamp = event['metadata']['timestamp']
            if isinstance(stamp, bool) or not isinstance(stamp, (int,float)) or not math.isfinite(stamp):
                raise ValueError('invalid timestamp')
            if self.last_timestamp is not None and stamp <= self.last_timestamp:
                raise ValueError('timestamp not increasing')
            age = wall-stamp
            if age < 0 or age > self.max_age:
                raise ValueError('frame age outside limit')
            frame = base64.b64decode(event['data'], validate=True)
            with Image.open(io.BytesIO(frame)) as im:
                if im.format != 'PNG' or im.size != (1920,1080):
                    raise ValueError('invalid frame geometry or encoding')
                im.verify()
            self.last_timestamp = stamp
            self.latest = (stamp, frame)
        except Exception as exc:
            self.error = str(exc)
        finally:
            try:
                self.session.send('Page.screencastFrameAck', {'sessionId':event['sessionId']})
            except Exception as exc:
                self.error = str(exc)

    def capture_after(self, wall_threshold):
        deadline = time.monotonic()+self.timeout
        while time.monotonic() < deadline:
            if self.error:
                raise RuntimeError('PNG stream invalid: '+self.error)
            wall, mono = time.time(), time.monotonic()
            if abs((wall-self.last_wall)-(mono-self.last_mono)) > .1:
                raise RuntimeError('wall clock changed')
            if self.latest and self.latest[0] > wall_threshold:
                now = time.time()
                if now-self.latest[0] < 0 or now-self.latest[0] > self.max_age:
                    raise RuntimeError('PNG stream stale')
                return self.latest[1]
            self.page.wait_for_timeout(25)
        raise RuntimeError('PNG stream timed out')

    def close(self):
        if self.session is not None:
            session, self.session = self.session, None
            try:
                session.send('Page.stopScreencast')
            finally:
                session.detach()
