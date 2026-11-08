import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from sanma_prestart_socket_audit import run, choose_blank_page

class PrestartAuditTest(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        self.output=Path(self.dir.name)/'audit.jsonl'
        self.page=Mock(); self.page.url='about:blank'; self.page.is_closed.return_value=False
        self.session=Mock(); self.page.context.new_cdp_session.return_value=self.session
        context=Mock();context.pages=[self.page];self.browser=Mock();self.browser.contexts=[context]
        self.clock=0
    def now(self):
        self.clock+=.2;return self.clock
    def test_capture_start_and_stop_without_navigation(self):
        events={}
        self.session.on.side_effect=lambda name,callback: events.update({name:callback})
        def wait(_):
            if events:
                events['Network.webSocketCreated']({'requestId':'rid','url':'wss://user:pass@game.invalid/path?key=secret'})
                events['Network.webSocketClosed']({'requestId':'rid','payload':'private'})
                events.clear()
        self.page.wait_for_timeout.side_effect=wait
        run(self.browser,self.output,1.0,now=self.now)
        records=[json.loads(s) for s in self.output.read_text().splitlines()]
        self.assertTrue(any(r['event']=='sanma_prestart_audit_ready' for r in records))
        close=next(r for r in records if r['event']=='sanma_socket_audit_closed')
        self.assertTrue(close['creationObserved']);self.assertIsNotNone(close['hostnameSha256'])
        self.assertTrue(all(r['operationAuthorized'] is False for r in records))
        for secret in ('user','pass','secret','private','/path','rid'):
            self.assertNotIn(secret,self.output.read_text())
        self.page.goto.assert_not_called();self.page.reload.assert_not_called();self.page.mouse.click.assert_not_called()
        self.assertEqual(self.output.stat().st_mode & 0o777,0o600)
    def test_reject_live_and_ambiguous_pages_without_artifact(self):
        self.page.url='https://game.mahjongsoul.com/'
        with self.assertRaises(RuntimeError):run(self.browser,self.output,1,now=self.now)
        self.assertFalse(self.output.exists())
        other=Mock();other.url='https://game.mahjongsoul.com/';other.is_closed.return_value=False
        self.page.url='about:blank';self.browser.contexts[0].pages=[self.page,other]
        with self.assertRaises(RuntimeError):run(self.browser,self.output,1,now=self.now)
        self.assertFalse(self.output.exists())
        self.browser.contexts[0].pages=[self.page,self.page]
        with self.assertRaises(RuntimeError):choose_blank_page(self.browser)
    def test_reject_invalid_duration_and_existing_file(self):
        for duration in (0,-1,float('nan'),86401):
            with self.assertRaises(ValueError):run(self.browser,self.output,duration,now=self.now)
        self.output.write_text('preserve')
        with self.assertRaises(FileExistsError):run(self.browser,self.output,1,now=self.now)
        self.assertEqual(self.output.read_text(),'preserve')
