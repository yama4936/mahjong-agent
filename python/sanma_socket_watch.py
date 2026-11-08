"""Read-only socket metadata watch; start before a user-initiated reconnect.

Never navigates, clicks, reads WebSocket payloads, or authorizes game actions.
The watch observes one already open game page and writes only hashed IDs,
hashed hostnames, and frame counts. An existing socket's origin remains unknown.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from sanma_socket_audit import SocketAudit

LOCK = Path('/home/yama1/server/data/dev-work/jantama/socket-watch.lock')

def is_game_page(page):
    try:
        url = urlsplit(page.url)
        return not page.is_closed() and url.scheme == 'https' and url.hostname == 'game.mahjongsoul.com'
    except Exception:
        return False


def game_page(browser):
    pages = []
    for context in browser.contexts:
        for page in context.pages:
            if is_game_page(page):
                pages.append(page)
    if len(pages) != 1:
        raise RuntimeError('exactly one live Mahjong Soul page is required')
    return pages[0]


def watch(page, log, *, interval=30, stop=lambda: False, max_seconds=None):
    audit = SocketAudit(page, log)
    started = last = time.monotonic()
    try:
        while not stop():
            if audit.logging_failed:
                raise RuntimeError('socket audit logging failed')
            if not is_game_page(page):
                raise RuntimeError('game page closed or navigated away')
            now=time.monotonic()
            if max_seconds is not None and now-started >= max_seconds: break
            if now-last >= interval:
                audit.snapshot('periodic');last=now
            page.wait_for_timeout(250)
    finally:
        audit.snapshot('watch_stopping')
        audit.close()
        if audit.logging_failed:
            raise RuntimeError('socket audit logging failed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cdp',default='http://127.0.0.1:9222')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    base=Path('/home/yama1/server/data/dev-work/jantama').resolve()
    output=args.output.resolve()
    if not output.is_relative_to(base): parser.error('output must be under the Jantama development SSD directory')
    LOCK.parent.mkdir(parents=True,exist_ok=True)
    with LOCK.open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit('socket watch already running')
        output.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        with os.fdopen(fd,'a',encoding='utf8',buffering=1) as out:
            def log(event, **fields):
                out.write(json.dumps({'timestamp':datetime.now(timezone.utc).isoformat(),'event':event,**fields},ensure_ascii=False)+'\n')
            stopped=[False]
            def handle(_signum,_frame):stopped[0]=True
            signal.signal(signal.SIGTERM,handle);signal.signal(signal.SIGINT,handle)
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                browser=playwright.chromium.connect_over_cdp(args.cdp)
                page=game_page(browser)
                log('socket_watch_attached',operationAuthorized=False)
                watch(page,log,stop=lambda:stopped[0])
                log('socket_watch_stopped',operationAuthorized=False)

if __name__=='__main__':main()
