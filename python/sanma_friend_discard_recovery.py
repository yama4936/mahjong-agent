"""Bounded evidence for continuing a reviewed CPU friend match after a discard."""
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

from sanma_discard_evidence_chain import evaluate
from sanma_concealed_conservation import consistent


class MatchContinuity:
    EVENTS = ('Network.webSocketCreated', 'Network.webSocketClosed', 'Network.webSocketFrameError',
              'Page.frameStartedLoading', 'Page.frameNavigated', 'Page.frameDetached',
              'Page.navigatedWithinDocument', 'Inspector.detached', 'Inspector.targetCrashed')

    def __init__(self, page):
        self.page = page
        self.invalid = False
        self.url = page.url
        self.session = None
        try:
            self.session = page.context.new_cdp_session(page)
            for name in self.EVENTS:
                self.session.on(name, lambda _event: self.invalidate())
            self.session.send('Network.enable')
            self.session.send('Page.enable')
            if not self.alive():
                raise RuntimeError('match continuity unavailable')
        except Exception:
            self.close()
            raise

    def invalidate(self):
        self.invalid = True

    def alive(self):
        try:
            self.page.wait_for_timeout(1)
            self.session.send('Runtime.evaluate', {'expression': '1', 'returnByValue': True})
            return not self.invalid and not self.page.is_closed() and self.page.url == self.url
        except Exception:
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
        receipts = [before, *posts]
        # Each five-sou has its ordinary/red glyph independently checked in
        # every frame; other fives remain excluded because conservation alone
        # cannot establish red identity.
        for receipt in receipts:
            data = Path(receipt['screenshot']).read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest != receipt['digest'] or digest != receipt['sourceObservation']['digest']:
                return False
            hand = receipt['sourceObservation']['report']['hand']['value']
            tiles = hand.get('tiles', [])
            if (hand.get('candidateMelds') != 0 or any(t in {'0p','5p'} for t in tiles)):
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
    result = evaluate(paths[0], paths[1:], journal, recheck_round=True)
    ok = (result.get('state') == 'later_turn_evidence_candidate'
          and all(consistent(receipts[0], post, journal[0]['clickIndex']) for post in receipts[1:]))
    print(json.dumps({'candidate': ok}))
