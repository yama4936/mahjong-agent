"""Bounded evidence for continuing a reviewed CPU friend match after a discard."""
import hashlib
import json
import math
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from sanma_discard_evidence_chain import evaluate
from sanma_concealed_conservation import consistent


class MatchContinuity:
    EVENTS = ('Network.webSocketCreated', 'Network.webSocketClosed', 'Network.webSocketFrameError',
              'Page.frameStartedLoading', 'Page.frameNavigated', 'Page.frameDetached',
              'Page.navigatedWithinDocument', 'Inspector.detached', 'Inspector.targetCrashed')

    def __init__(self, page):
        self.page = page
        self.invalid = False
        self.monitor_id = uuid.uuid4().hex
        self.started_at = time.monotonic()
        self.invalid_reason = None
        self.invalid_at = None
        self.invalid_network = None
        self.url = page.url
        self.session = None
        try:
            self.session = page.context.new_cdp_session(page)
            for name in self.EVENTS:
                self.session.on(name, lambda event, event_name=name: self.invalidate(event_name, event))
            self.session.send('Network.enable')
            self.session.send('Page.enable')
            if not self.alive():
                raise RuntimeError('match continuity unavailable')
        except Exception:
            self.close()
            raise

    def invalidate(self, reason='unknown', event=None):
        if not self.invalid:
            self.invalid_reason = reason
            self.invalid_at = time.monotonic()
            if reason.startswith('Network.webSocket') and isinstance(event, dict):
                metadata = {}
                request = event.get('requestId')
                if isinstance(request, str) and request:
                    metadata['requestIdSha256'] = hashlib.sha256(request.encode()).hexdigest()
                url = event.get('url')
                if isinstance(url, str):
                    try:
                        parsed = urlsplit(url)
                        if parsed.scheme in ('ws', 'wss') and parsed.hostname:
                            metadata['hostname'] = parsed.hostname
                    except ValueError:
                        pass
                self.invalid_network = metadata
        self.invalid = True

    def diagnostic(self):
        result = {'monitorId': self.monitor_id, 'invalid': self.invalid,
                  'reason': self.invalid_reason,
                  'elapsedMs': round((self.invalid_at-self.started_at)*1000) if self.invalid_at is not None else None}
        if self.invalid_network is not None:
            result['network'] = self.invalid_network.copy()
        return result

    def alive(self):
        try:
            self.page.wait_for_timeout(1)
            self.session.send('Runtime.evaluate', {'expression': '1', 'returnByValue': True})
            if self.page.is_closed(): self.invalidate('page_closed')
            elif self.page.url != self.url: self.invalidate('page_url_changed')
            return not self.invalid
        except Exception as error:
            self.invalidate('observation_exception:' + type(error).__name__)
            return False

    def close(self):
        try:
            if self.session is not None:
                self.session.detach()
        except Exception:
            pass


def candidate(before, posts, journal, *, continuity, active, started, deadline_ms, now=time.monotonic):
    """Only an evidence-backed candidate, never a guarantee of input outcome."""
    def valid():
        value = now()
        return (active() is True and continuity.alive() is True
                and type(started) in (int, float) and math.isfinite(started)
                and type(deadline_ms) is int and deadline_ms == 300000
                and 0 <= (value-started)*1000 < deadline_ms)
    try:
        if len(posts) != 2 or not valid():
            return False
        if (len(journal) != 2 or any(event.get('blankDrawIdentityUnknown') is True for event in journal)
                and not all(event.get('blankDrawIdentityUnknown') is True for event in journal)):
            return False
        receipts = [before, *posts]
        # Each five-sou has its ordinary/red glyph independently checked in
        # every frame; other fives remain excluded because conservation alone
        # cannot establish red identity.
        for receipt in receipts:
            from sanma_friend_geometry_alignment import aligned_post_slots
            aligned = aligned_post_slots(before, receipt) if receipt is not before else None
            data = Path(receipt['screenshot']).read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest != receipt['digest'] or digest != receipt['sourceObservation']['digest']:
                return False
            hand = receipt['sourceObservation']['report']['hand']['value']
            tiles = hand.get('tiles', [])
            if hand.get('candidateMelds') != 0:
                return False
            if '0p' in tiles:
                from sanma_five_pin_candidate import red_five_pin_face_candidate
                geometry = receipt['sourceObservation']['report']['handGeometry']['value']
                slots = aligned or [*geometry['handSlots'], geometry['drawSlot']]
                if len(tiles) != 14 or len(slots) != 14 or any(
                    not red_five_pin_face_candidate(data,slots[i]) for i,tile in enumerate(tiles) if tile == '0p'
                ):
                    return False
            if '5p' in tiles:
                from sanma_five_pin_candidate import ordinary_five_pin_face_candidate
                geometry = receipt['sourceObservation']['report']['handGeometry']['value']
                slots = [*geometry['handSlots'], geometry['drawSlot']]
                if len(tiles) != 14 or len(slots) != 14 or any(
                    not ordinary_five_pin_face_candidate(data, slots[i]) for i,tile in enumerate(tiles) if tile == '5p'
                ):
                    return False
            if any(t in {'0s','5s'} for t in tiles):
                from sanma_five_sou_candidate import ordinary_five_sou_face_candidate, red_five_sou_face_candidate
                geometry = receipt['sourceObservation']['report']['handGeometry']['value']
                slots = [*geometry['handSlots'], geometry['drawSlot']]
                if len(tiles) != 14 or len(slots) != 14 or any(
                    not (red_five_sou_face_candidate if tile == '0s' else ordinary_five_sou_face_candidate)(data, slots[i])
                    for i,tile in enumerate(tiles) if tile in {'0s','5s'}
                ):
                    return False
        paths = [str(Path(r['screenshot']).with_suffix('.receipt.json')) for r in receipts]
        if any(json.loads(Path(path).read_text()) != receipt for path, receipt in zip(paths, receipts)):
            return False
        remaining = deadline_ms / 1000 - (now() - started)
        if remaining <= 0:
            return False
        # OCR may hang inside a native runtime. Isolate it in a reaped child,
        # bound by both the old turn deadline and an operational limit.
        request = json.dumps({'paths': paths, 'journal': journal})
        child = subprocess.run([sys.executable, __file__], input=request, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=min(20.0, remaining), check=True)
        response = json.loads(child.stdout.strip().splitlines()[-1])
        return response.get('candidate') is True and valid()
    except Exception:
        return False


if __name__ == '__main__':
    request = json.load(sys.stdin)
    paths, journal = request['paths'], request['journal']
    receipts = [json.loads(Path(path).read_text()) for path in paths]
    unknown_draw = all(event.get('blankDrawIdentityUnknown') is True for event in journal)
    result = evaluate(paths[0], paths[1:], journal, recheck_round=True, unknown_draw=unknown_draw,
                      friend_second_row_overlap=True)
    ok = (result.get('state') == 'later_turn_evidence_candidate'
          and all(consistent(receipts[0], post, journal[0]['clickIndex']) for post in receipts[1:]))
    print(json.dumps({'candidate': ok}))
