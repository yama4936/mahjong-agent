"""Observe WebSocket metadata on an existing blank page before game navigation.

This helper never navigates, clicks, refreshes, or opens a page. Start it only
when no match is running, before a separate controller navigates the page.
"""
import argparse
import json
import math
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright
from sanma_socket_audit import SocketAudit

SSD_ROOT = Path('/home/yama1/server/data/dev-work/jantama').resolve()


def choose_blank_page(browser):
    existing = [page for context in browser.contexts for page in context.pages if not page.is_closed()]
    if any((urlsplit(page.url).hostname or '').endswith('mahjongsoul.com') for page in existing):
        raise RuntimeError('existing Mahjong Soul page prevents prestart audit')
    pages = [page for page in existing if page.url == 'about:blank']
    if len(pages) != 1:
        raise RuntimeError('exactly one existing blank page is required')
    return pages[0]


def run(browser, output, duration, *, now=time.monotonic):
    path = Path(output).resolve()
    if (not path.is_relative_to(SSD_ROOT) or path == SSD_ROOT
            or type(duration) not in (int, float) or not math.isfinite(duration)
            or not 0 < duration <= 86400):
        raise ValueError('invalid audit output or duration')
    page = choose_blank_page(browser)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    audit = None
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        def log(event, **kwargs):
            stream.write(json.dumps({'event': event, 'monotonic': now(), **kwargs},
                                    ensure_ascii=False, allow_nan=False) + '\n')
            stream.flush()
        try:
            audit = SocketAudit(page, log)
            if page.url != 'about:blank' or page.is_closed():
                raise RuntimeError('page changed during audit setup')
            log('sanma_prestart_audit_ready', beforeNavigation=True, operationAuthorized=False)
            end = now() + duration
            while now() < end and not page.is_closed():
                page.wait_for_timeout(min(250, max(1, int((end-now())*1000))))
            log('sanma_prestart_audit_stopped', operationAuthorized=False)
        finally:
            if audit is not None:
                audit.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cdp',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--duration-seconds',type=float,default=7200)
    args=parser.parse_args()
    with sync_playwright() as playwright:
        browser=playwright.chromium.connect_over_cdp(args.cdp)
        run(browser,args.output,args.duration_seconds)


if __name__ == '__main__':
    main()
