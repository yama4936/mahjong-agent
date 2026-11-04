"""Read-only, metadata-only WebSocket audit for reviewed sanma friend sessions."""
from collections import OrderedDict
import hashlib
from urllib.parse import urlsplit


class SocketAudit:
    def __init__(self, page, log):
        self.session = None
        self.log = log
        self.hosts = OrderedDict()
        try:
            self.session = page.context.new_cdp_session(page)
            self.session.on('Network.webSocketCreated', self.created)
            self.session.on('Network.webSocketClosed', self.closed)
            self.session.send('Network.enable')
            self._log('sanma_socket_audit_started', preexistingSocketsKnown=False, operationAuthorized=False)
        except Exception:
            self.close()
            raise

    def _log(self, event, **fields):
        try:
            self.log(event, **fields)
        except Exception:
            pass

    @staticmethod
    def _key(event):
        request = event.get('requestId') if isinstance(event, dict) else None
        return hashlib.sha256(request.encode()).hexdigest() if isinstance(request, str) and request else None

    def created(self, event):
        try:
            key = self._key(event)
            if key is None:
                return
            url = event.get('url')
            host = None
            if isinstance(url, str):
                parsed = urlsplit(url)
                if parsed.scheme in ('ws', 'wss'):
                    host = hashlib.sha256(parsed.hostname.encode()).hexdigest() if parsed.hostname else None
            self.hosts[key] = host
            if len(self.hosts) > 128:
                self.hosts.popitem(last=False)
            self._log('sanma_socket_audit_created', requestIdSha256=key,
                      hostnameSha256=host, operationAuthorized=False)
        except Exception:
            pass

    def closed(self, event):
        try:
            key = self._key(event)
            if key is None:
                return
            known = key in self.hosts
            host = self.hosts.pop(key, None)
            self._log('sanma_socket_audit_closed', requestIdSha256=key,
                      hostnameSha256=host, creationObserved=known, operationAuthorized=False)
        except Exception:
            pass

    def close(self):
        if self.session is not None:
            try:
                self.session.detach()
            except Exception:
                pass
            self.session = None
        self.hosts.clear()
