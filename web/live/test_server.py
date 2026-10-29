import asyncio
import io
import unittest
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
        self.relay=Relay();self.client=TestClient(TestServer(create_app(self.relay,capture=False)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_stream_and_hide_and_no_control(self):
        ws=await self.client.ws_connect('/ws',origin='https://jantama.yama.asia')
        self.assertEqual((await ws.receive_json())['state'],'waiting')
        self.relay.broadcast('live',b'jpeg-test',123)
        self.assertEqual((await ws.receive_json())['capturedAt'],123)
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

    async def test_capacity_and_new_viewer_has_no_old_frame(self):
        self.relay.broadcast('live',b'old',1)
        clients=[await self.client.ws_connect('/ws') for _ in range(16)]
        for ws in clients:self.assertEqual((await ws.receive_json())['state'],'waiting')
        with self.assertRaises(WSServerHandshakeError) as error:await self.client.ws_connect('/ws')
        self.assertEqual(error.exception.status,503)
        for ws in clients:await ws.close()

if __name__=='__main__':unittest.main()
