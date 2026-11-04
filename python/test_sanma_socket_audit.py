import hashlib
import unittest
from unittest.mock import Mock
from sanma_socket_audit import SocketAudit

class SocketAuditTest(unittest.TestCase):
    def setUp(self):
        self.page=Mock();self.session=Mock();self.page.context.new_cdp_session.return_value=self.session
        self.log=Mock();self.audit=SocketAudit(self.page,self.log)
        self.callbacks={x.args[0]:x.args[1] for x in self.session.on.call_args_list}
    def test_created_and_closed_match_without_payload_or_url(self):
        event={'requestId':'private-rid','url':'wss://user:secret@game.invalid/path?key=token','payload':'secret'}
        self.callbacks['Network.webSocketCreated'](event)
        self.callbacks['Network.webSocketClosed']({'requestId':'private-rid','payload':'secret'})
        c=self.log.call_args
        self.assertEqual(c.args[0],'sanma_socket_audit_closed')
        self.assertEqual(c.kwargs['requestIdSha256'],hashlib.sha256(b'private-rid').hexdigest())
        self.assertEqual(c.kwargs['hostnameSha256'],hashlib.sha256(b'game.invalid').hexdigest());self.assertTrue(c.kwargs['creationObserved'])
        log=str(self.log.call_args_list)
        for secret in ('private-rid','user','secret','/path','token'):self.assertNotIn(secret,log)
        self.assertEqual([x.args[0] for x in self.session.send.call_args_list],['Network.enable'])
    def test_preexisting_or_unrecognized_connection_remains_unknown(self):
        self.callbacks['Network.webSocketClosed']({'requestId':'unknown'})
        self.assertIsNone(self.log.call_args.kwargs['hostnameSha256'])
        self.assertFalse(self.log.call_args.kwargs['creationObserved'])
        self.assertFalse(self.log.call_args.kwargs['operationAuthorized'])
    def test_independent_of_action_and_callback_errors_are_silent(self):
        self.log.side_effect=RuntimeError('sensitive')
        self.callbacks['Network.webSocketCreated']({'requestId':'1','url':'wss://bad.invalid:broken'})
        self.callbacks['Network.webSocketClosed']({'requestId':'1'})
        self.audit.close();self.audit.close();self.session.detach.assert_called_once()
        self.page.mouse.click.assert_not_called()
    def test_bounded_memory(self):
        for i in range(140): self.callbacks['Network.webSocketCreated']({'requestId':str(i),'url':'wss://game.invalid'})
        self.assertEqual(len(self.audit.hosts),128)
        self.callbacks['Network.webSocketClosed']({'requestId':'0'})
        self.assertFalse(self.log.call_args.kwargs['creationObserved'])
