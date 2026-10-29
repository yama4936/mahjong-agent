import asyncio
import io
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from aiohttp import WSMsgType, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image, UnidentifiedImageError
from server import Relay, create_app, is_game_url, public_frame


def png(size=(1920,1080)):
    out=io.BytesIO();Image.new('RGB',size,'green').save(out,'PNG');return out.getvalue()


class FrameTests(unittest.TestCase):
    def test_only_exact_game_origin(self):
        self.assertTrue(is_game_url('https://game.mahjongsoul.com/index.html'))
        for url in ['https://game.mahjongsoul.com.evil.test/index.html','https://evil.test/','http://game.mahjongsoul.com/index.html']:
            self.assertFalse(is_game_url(url))

    def test_all_content_is_published_without_classification(self):
        state, frame = public_frame(png())
        self.assertEqual(state, 'live')
        image = Image.open(io.BytesIO(frame))
        self.assertEqual(image.format, 'JPEG')
        self.assertEqual(image.size, (1280, 720))

    def test_other_viewports_preserve_aspect_ratio(self):
        for size, expected in [((100,100),(100,100)), ((800,1200),(480,720))]:
            state, frame = public_frame(png(size))
            self.assertEqual(state, 'live')
            self.assertEqual(Image.open(io.BytesIO(frame)).size, expected)

    def test_invalid_capture_is_not_published(self):
        with self.assertRaises(UnidentifiedImageError):
            public_frame(b'not an image')

    def test_latest_packet_replaces_backlog_and_clears_frame(self):
        relay=Relay();queue=asyncio.Queue(maxsize=1);relay.clients.add(queue)
        relay.broadcast('live',b'old',1);relay.broadcast('live',b'new',2)
        self.assertEqual(queue.qsize(),1);self.assertEqual(queue.get_nowait()[1],b'new')
        relay.broadcast('waiting');self.assertIsNone(relay.last_capture)
        self.assertIsNone(queue.get_nowait()[1])


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.results = tempfile.TemporaryDirectory()
        self.relay=Relay();self.client=TestClient(TestServer(create_app(self.relay,capture=False,results_dir=self.results.name)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.results.cleanup()

    async def test_only_exported_results_and_images_are_public(self):
        root = Path(self.results.name)
        (root / 'data.json').write_text('{"records":[]}')
        (root / 'data.json.tmp').write_text('incomplete')
        (root / 'images').mkdir()
        name = 'images/' + 'a'*24 + '.webp'
        (root / name).write_bytes(b'image')
        response = await self.client.get('/results/data.json', headers={'Origin':'https://jantama.yama.asia'})
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {'records':[]})
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], 'https://jantama.yama.asia')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        image = await self.client.get('/results/' + name)
        self.assertEqual(image.status, 200)
        self.assertEqual(image.headers['Content-Type'], 'image/webp')
        for name in ['data.json.tmp', 'server.py', '.env', 'images/other.webp']:
            self.assertEqual((await self.client.get('/results/' + name)).status, 404)
        self.assertEqual((await self.client.post('/results/data.json')).status, 405)

    async def test_stream_and_hide_and_no_control(self):
        ws=await self.client.ws_connect('/ws',origin='https://jantama.yama.asia')
        self.assertEqual((await ws.receive_json())['state'],'waiting')
        self.relay.telemetry = {'updatedAt': '2026-10-29T06:00:00+00:00',
                                'decision': None, 'logs': [{'id': '1', 'event': 'click_sent'}]}
        self.relay.broadcast('live',b'jpeg-test',123)
        packet = await ws.receive_json()
        self.assertEqual(packet['capturedAt'],123)
        self.assertEqual(packet['telemetry'], self.relay.telemetry)
        self.assertEqual((await ws.receive()).data,b'jpeg-test')
        self.relay.broadcast('waiting')
        self.assertIsNone((await ws.receive_json())['capturedAt'])
        await ws.send_json({'method':'Input.dispatchMouseEvent'})
        self.assertEqual((await ws.receive()).type,WSMsgType.CLOSE)
        await ws.close()

    async def test_no_debug_proxy_files_or_mutation(self):
        for route in ['/json/list','/server.py','/.env','/artifacts/file','/devtools/page/123']:
            self.assertEqual((await self.client.get(route)).status,404)
        self.assertEqual((await self.client.post('/health')).status,405)
        with self.assertRaises(WSServerHandshakeError):
            await self.client.ws_connect('/ws',origin='https://evil.test')
        response=await self.client.get('/health')
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertNotIn('CDP',await response.text())

    async def test_tile_images_are_available_from_fixed_allowlist(self):
        response = await self.client.get('/tiles/E.png')
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers['Content-Type'], 'image/png')
        self.assertTrue((await response.read()).startswith(b'\x89PNG'))
        self.assertEqual(response.headers['Cache-Control'], 'public, max-age=86400')
        versioned = await self.client.get('/tiles/E.png?v=8c0f22e7')
        self.assertEqual(versioned.headers['Cache-Control'], 'public, max-age=31536000, immutable')
        self.assertEqual((await self.client.get('/tiles/LICENSE')).status, 200)
        for name in ['server.py', '.env', '0m.png', 'invalid.png']:
            self.assertEqual((await self.client.get('/tiles/' + name)).status, 404)

    async def test_capacity_and_new_viewer_has_no_old_frame(self):
        self.relay.broadcast('live',b'old',1)
        clients=[await self.client.ws_connect('/ws') for _ in range(16)]
        for ws in clients:self.assertEqual((await ws.receive_json())['state'],'waiting')
        with self.assertRaises(WSServerHandshakeError) as error:await self.client.ws_connect('/ws')
        self.assertEqual(error.exception.status,503)
        for ws in clients:await ws.close()

    async def test_events_arrive_without_video_and_reject_control(self):
        ws = await self.client.ws_connect('/events', origin='https://jantama.yama.asia')
        initial = await ws.receive_json()
        self.assertEqual(initial['type'], 'telemetry')
        snapshot = {'updatedAt': '2026-10-29T06:00:00+00:00', 'decision': None,
                    'logs': [{'id': 'one', 'event': 'action_aborted'}]}
        self.relay.publish_telemetry(snapshot)
        async with asyncio.timeout(.5):
            self.assertEqual((await ws.receive_json())['telemetry'], snapshot)
        self.assertIsNone(self.relay.last_capture)
        self.assertEqual(len(self.relay.clients), 0)
        self.relay.publish_telemetry(snapshot)
        self.assertTrue(next(iter(self.relay.event_clients)).empty())
        await ws.send_json({'method': 'Input.dispatchMouseEvent'})
        self.assertEqual((await ws.receive()).type, WSMsgType.CLOSE)
        await ws.close()

    async def test_jsonl_append_pushes_to_events_within_subsecond(self):
        root = Path(self.results.name)
        log = root / 'operator' / 'python-operator.jsonl'
        log.parent.mkdir()
        log.write_text('')
        ws = await self.client.ws_connect('/events')
        await ws.receive_json()
        with patch.dict('os.environ', {'OPERATOR_ARTIFACTS_DIR': str(root)}):
            follower = asyncio.create_task(self.relay.follow_telemetry())
            try:
                log.write_text('{"event":"action_aborted","timestamp":"2026-10-29T06:00:00+00:00"}\n')
                async with asyncio.timeout(.75):
                    packet = await ws.receive_json()
                self.assertEqual(packet['telemetry']['logs'][-1]['event'], 'action_aborted')
            finally:
                follower.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await follower
        await ws.close()

if __name__=='__main__':unittest.main()
