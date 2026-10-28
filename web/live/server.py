"""Read-only, bounded JPEG/WebSocket relay for the Mahjong Soul tab."""
import asyncio
import base64
import contextlib
import io
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web
from PIL import Image
from screen_state import classify_screen

ALLOWED_STATES = {'match', 'round_result', 'match_result'}
ALLOWED_ORIGINS = {
    'https://jantama.yama.asia', 'https://jantama-live.yama.asia',
    'https://jantama-results-yama-20261027.arcane-krill-4260.chatgpt.site',
}
CDP = os.environ.get('CDP_URL', 'http://127.0.0.1:9222')
FPS = min(5, max(1, int(os.environ.get('LIVE_FPS', '3'))))
MAX_VIEWERS = 16
ROOT = Path(__file__).parent


def is_game_url(url):
    parsed = urlsplit(url)
    return parsed.scheme == 'https' and parsed.hostname == 'game.mahjongsoul.com' and parsed.path == '/index.html'


def public_frame(raw):
    # No nearest-reference fallback: ambiguous/unsupported screens stay hidden.
    state, confidence = classify_screen(raw, {})
    if state not in ALLOWED_STATES or confidence < 1:
        return 'waiting', None
    image = Image.open(io.BytesIO(raw)).convert('RGB')
    if image.size != (1920, 1080):
        return 'waiting', None
    image.thumbnail((1280, 720))
    output = io.BytesIO()
    image.save(output, 'JPEG', quality=65)
    return state, output.getvalue()


class Relay:
    def __init__(self):
        self.clients = set()
        self.sequence = 0
        self.state = 'waiting'
        self.last_capture = None
        self.last_tick = time.monotonic()

    def broadcast(self, state, frame=None, captured_at=None):
        self.sequence += 1
        self.state = state
        self.last_tick = time.monotonic()
        self.last_capture = captured_at if frame else None
        packet = ({'state': state, 'sequence': self.sequence,
                   'capturedAt': self.last_capture, 'fpsLimit': FPS}, frame)
        for queue in tuple(self.clients):
            if queue.full():
                queue.get_nowait()  # Never accumulate an old video backlog.
            queue.put_nowait(packet)

    async def capture(self):
        async with ClientSession(timeout=ClientTimeout(total=3)) as session:
            while True:
                if not self.clients:
                    self.broadcast('waiting')
                    await asyncio.sleep(1)
                    continue
                try:
                    async with session.get(CDP + '/json/list') as response:
                        response.raise_for_status()
                        targets = await response.json()
                    target = next(t for t in targets if t.get('type') == 'page' and is_game_url(t.get('url', '')))
                    # Derive the websocket from the configured local CDP host, never from visitors.
                    endpoint = urlsplit(CDP)
                    ws_path = '/devtools/page/' + target['id']
                    async with session.ws_connect(f'ws://{endpoint.netloc}{ws_path}', max_msg_size=12*1024*1024) as ws:
                        seq = 0
                        async def call(method, params=None):
                            nonlocal seq
                            seq += 1
                            await ws.send_json({'id': seq, 'method': method, 'params': params or {}})
                            async with asyncio.timeout(3):
                                while True:
                                    msg = await ws.receive()
                                    if msg.type != WSMsgType.TEXT:
                                        raise ConnectionError('CDP disconnected')
                                    data = json.loads(msg.data)
                                    if data.get('id') == seq:
                                        if 'error' in data:
                                            raise RuntimeError('Capture unavailable')
                                        return data['result']
                        while self.clients:
                            start = time.monotonic()
                            tree = await call('Page.getFrameTree')
                            if not is_game_url(tree['frameTree']['frame']['url']):
                                break
                            captured_at = time.time()
                            shot = await call('Page.captureScreenshot', {'format': 'jpeg', 'quality': 80,
                                                                        'captureBeyondViewport': False})
                            state, frame = await asyncio.to_thread(public_frame, base64.b64decode(shot['data']))
                            # If capture stalls, do not label a delayed image as live.
                            if time.monotonic() - start > 2.5:
                                self.broadcast('offline')
                            else:
                                self.broadcast(state, frame, captured_at)
                            await asyncio.sleep(max(0.01, 1/FPS - (time.monotonic()-start)))
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    print(json.dumps({'event': 'capture_unavailable', 'type': type(error).__name__}), flush=True)
                    self.broadcast('offline')
                    await asyncio.sleep(2)
                finally:
                    self.broadcast('waiting')

    async def websocket(self, request):
        origin = request.headers.get('Origin')
        if origin and origin not in ALLOWED_ORIGINS:
            raise web.HTTPForbidden()
        if len(self.clients) >= MAX_VIEWERS:
            raise web.HTTPServiceUnavailable(text='Viewer limit reached')
        ws = web.WebSocketResponse(heartbeat=15, max_msg_size=1024, compress=False)
        await ws.prepare(request)
        queue = asyncio.Queue(maxsize=1)
        self.clients.add(queue)
        # New viewers never receive a cached image from a previous session.
        await ws.send_json({'state': 'waiting', 'capturedAt': None, 'fpsLimit': FPS})
        async def send():
            while True:
                metadata, frame = await queue.get()
                async with asyncio.timeout(3):
                    await ws.send_json(metadata)
                    if frame:
                        await ws.send_bytes(frame)
        sender = asyncio.create_task(send())
        # Closing the socket when its writer fails avoids retaining dead viewers.
        sender.add_done_callback(lambda _: asyncio.create_task(ws.close()))
        try:
            async for msg in ws:
                # This is a receive-only viewer, never a browser control endpoint.
                if msg.type in {WSMsgType.TEXT, WSMsgType.BINARY}:
                    await ws.close(code=1008, message=b'Read-only stream')
        finally:
            self.clients.discard(queue)
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError, ConnectionError):
                await sender
        return ws


def create_app(relay=None, capture=True):
    relay = relay or Relay()
    @web.middleware
    async def headers(request, handler):
        response = await handler(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob:; connect-src 'self' wss://jantama-live.yama.asia; style-src 'self'; script-src 'self'; frame-ancestors https://jantama.yama.asia https://jantama-results-yama-20261027.arcane-krill-4260.chatgpt.site"
        return response
    app = web.Application(middlewares=[headers], client_max_size=1024)
    async def health(request):
        return web.json_response({'service': 'jantama-live', 'state': relay.state,
                                  'viewers': len(relay.clients), 'fpsLimit': FPS,
                                  'capturedAt': relay.last_capture})
    async def static(request):
        name = request.match_info.get('name', 'live.html')
        if name not in {'live.html', 'live.js', 'live.css'}:
            raise web.HTTPNotFound()
        return web.FileResponse(ROOT / name)
    app.router.add_get('/health', health)
    app.router.add_get('/ws', relay.websocket)
    app.router.add_get('/', static)
    app.router.add_get('/{name}', static)
    if capture:
        async def lifecycle(app):
            task = asyncio.create_task(relay.capture())
            yield
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        app.cleanup_ctx.append(lifecycle)
    return app


if __name__ == '__main__':
    web.run_app(create_app(), host='127.0.0.1', port=4383, access_log=None)
