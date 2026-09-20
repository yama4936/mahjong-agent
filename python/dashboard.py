#!/usr/bin/env python3
"""Read-only local dashboard for the existing Mahjong Soul CDP page."""

from __future__ import annotations

import argparse
import base64
import json
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Browser, Page, sync_playwright

from screen_state import classify_screen, load_references


HTML = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Jantama Agent Monitor</title><style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#090d13;color:#f4edd9}
body{margin:0;padding:18px;display:grid;gap:14px}.bar{display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.pill{padding:6px 10px;border:1px solid #665a38;border-radius:999px;background:#171b22}
#screen{display:block;width:min(100%,1920px);height:auto;border:1px solid #5f5334;border-radius:10px;background:#101820}
small{color:#aca692}.ok{color:#82d9a0}.stop{color:#ff9c91}
.panel{padding:18px;background:#171d27;border:1px solid #424c5c;border-radius:10px}.metrics{display:flex;gap:24px;flex-wrap:wrap}.tiles{display:flex;gap:6px;flex-wrap:wrap;margin:14px 0}.tile{background:#eee9dd;color:#172132;padding:10px;border-radius:5px;font-weight:bold}.choices{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:10px 0 14px}.choice{display:flex;justify-content:space-between;gap:10px;padding:9px 11px;border:1px solid #424c5c;border-radius:7px;background:#111720}.choice.selected{border-color:#d9b85f;background:#242216}.probability{font-variant-numeric:tabular-nums;color:#82d9a0}.muted{color:#b7bbc4}pre{white-space:pre-wrap;overflow-wrap:anywhere}h2{font-size:18px;margin-top:0}h3{font-size:15px;margin:14px 0 0}#reason{color:#ffbc9b}
</style></head><body><div class="bar"><strong>Jantama Agent Monitor</strong>
<span class="pill" id="state">state: …</span><span class="pill" id="confidence">confidence: …</span>
<span class="pill" id="updated">updated: …</span><span class="pill stop">READ ONLY</span></div>
<section class="panel" aria-label="判定情報"><h2>判定モニター <small>保存ログ・現在の画面とは別時点</small></h2>
<p id="judgedAt" class="muted">判定待ち</p><div class="metrics"><span id="recommendation">推奨：未判定</span><span id="tileScore">認識スコア：—</span><span id="margin">候補差：—</span><span id="execution">クリック：—</span></div>
<div id="tiles" class="tiles" aria-label="認識手牌"></div><h3>選択肢 <small id="probabilityNote"></small></h3><div id="choices" class="choices" aria-label="選択肢と選択確率"></div><p id="reason" role="status"></p><p id="operator" class="muted"></p>
<details><summary>判定データ</summary><pre id="judgmentJson"></pre></details></section>
<strong>現在の画面（ライブ）</strong><img id="screen" alt="現在の雀魂画面"><small id="detail"></small><script>
const el=id=>document.getElementById(id);
const number=v=>typeof v==='number'?v.toFixed(3):'—';
const percent=v=>typeof v==='number'?(v*100).toFixed(1)+'%':'—';
const actionName=a=>({discard:'打牌',riichi:'リーチ',tsumo:'ツモ',ron:'ロン',chi:'チー',pon:'ポン',minkan:'明槓',ankan:'暗槓',kakan:'加槓',pass:'見送り'}[a]||a||'未判定');
function renderChoices(d){
 const probabilities=d?.jev?.probabilities||{};
 const candidates=(d?.candidates?.length?d.candidates:d?.legalActions)||[];
 const selected=d?.selectedActionId;
 el('probabilityNote').textContent=d?.jev?'（Jev選択確率）':'（Jev未使用のため確率なし）';
 el('choices').replaceChildren(...candidates.map(c=>{
  const id=c.actionId||c.id||'';const row=document.createElement('div');row.className='choice'+(id===selected?' selected':'');
  const label=document.createElement('span');label.textContent=c.tile?`${c.action||'discard'} ${c.tile}`:(c.action||id);
  const probability=document.createElement('span');probability.className='probability';probability.textContent=percent(probabilities[id]);probability.title='この選択肢が最善であるというJevの選択確率';
  row.append(label,probability);return row;
 }));
}
function renderJudgment(j){
 const e=j?.evaluation||{},r=e.recognition||{},d=e.decision||{},x=j?.execution||{};
 const selected=d.selectedAction||{};
 const action=selected.action||d.recommendedAction||(e.status==='reaction_prompt'?'pass':undefined);
 const tile=selected.tile||d.tile;
 el('judgedAt').textContent=j?.timestamp?'判定時刻：'+new Date(j.timestamp).toLocaleString()+' ／ 保存ログ（ライブ判定ではありません）':'判定ログなし';
 el('recommendation').textContent='推奨：'+actionName(action)+(tile?' '+tile:'')+(e.status==='reaction_prompt'?'（盤面を特定できないため安全側）':'');
 el('tileScore').textContent='認識スコア：'+number(r.confidence)+'（正解確率ではありません）';
 el('margin').textContent='候補差：'+number(r.ambiguityMargin);
 el('execution').textContent='クリック：'+(x.clicked===true?'送信済み'+(x.tileMultisetVerification?.verified?'・結果確認済み':''):x.clicked===false?'未実行':'実行記録なし');
 el('tiles').replaceChildren(...(r.tiles||[]).map((t,i)=>{const n=document.createElement('span');n.className='tile';n.textContent=t;n.title=(i===13?'ツモ牌':'手牌 '+(i+1));return n}));
 renderChoices(d);
 const reasons=[];if(r.turnReady===false)reasons.push('手番・手牌枚数を確認できません');if(r.safe===false)reasons.push('認識基準未達：クリック対象に採用しません');if(x.reason)reasons.push(x.reason);if(d.reason)reasons.push(typeof d.reason==='string'?d.reason:JSON.stringify(d.reason));
 el('reason').textContent=reasons.join(' ／ ')||'停止理由の記録なし';
 el('judgmentJson').textContent=JSON.stringify(j||{},null,2);
}
const image=document.querySelector('#screen'); async function refresh(){
 const now=Date.now(); image.src='/screen.png?t='+now;
 try{const s=await fetch('/api/status?t='+now,{cache:'no-store'}).then(r=>r.json());
 el('state').textContent='画面分類: '+s.screenState; el('confidence').textContent='画面分類スコア: '+number(s.screenConfidence);
 el('updated').textContent='画面更新: '+new Date(s.capturedAt).toLocaleTimeString();
 el('detail').textContent=s.pageUrl;renderJudgment(s.judgment);
 el('operator').textContent='操作者の最終記録：'+(s.lastEvent||'なし')+(s.lastEventAt?' ／ '+new Date(s.lastEventAt).toLocaleString():'')+(s.lastError?' ／ '+s.lastError:'');
 }catch(e){el('detail').textContent='更新失敗（表示内容は古い可能性があります）: '+e}finally{setTimeout(refresh,100)} }
refresh();</script></body></html>"""


class SharedFrame:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.image = b""
        self.status: dict[str, Any] = {
            "screenState": "unknown", "screenConfidence": 0, "capturedAt": None,
            "pageUrl": "", "lastEvent": None,
        }


def read_operator_status(path: Path | None) -> dict[str, Any]:
    empty = {"lastEvent": None, "lastEventAt": None, "lastError": None, "judgment": None}
    if not path or not path.exists():
        return empty
    try:
        # Bound IO for long sessions; skip partial first/last JSON records.
        with path.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - 2_000_000))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
        records = []
        for line in lines:
            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
            except ValueError:
                continue
        if not records:
            return empty
        latest = records[-1]
        # Never display an earlier run's recommendation as the new run's result.
        start = next((i for i in range(len(records)-1, -1, -1) if records[i].get("event") == "started"), 0)
        judgment = next((r for r in reversed(records[start:]) if isinstance(r.get("evaluation"), dict)), None)
        return {"lastEvent": latest.get("event"), "lastEventAt": latest.get("timestamp"),
                "lastError": latest.get("error"), "judgment": judgment}
    except (OSError, ValueError, TypeError):
        return empty


def handler_for(shared: SharedFrame) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            route = urlparse(self.path).path
            if route == "/":
                self.send_payload(HTML.encode(), "text/html; charset=utf-8")
                return
            with shared.lock:
                if route == "/screen.png" and shared.image:
                    self.send_payload(shared.image, "image/png")
                    return
                if route == "/api/status":
                    self.send_payload(json.dumps(shared.status).encode(), "application/json")
                    return
            self.send_error(HTTPStatus.NOT_FOUND)

        def send_payload(self, payload: bytes, content_type: str) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    return Handler


def find_page(browser: Browser) -> Page:
    for context in browser.contexts:
        for page in context.pages:
            if "mahjongsoul.com" in page.url:
                return page
    raise RuntimeError("No Mahjong Soul page found on the CDP browser")


def capture_cdp_screenshot(session: Any) -> bytes:
    """Capture without Playwright's page screenshot/viewport emulation.

    The operator owns the game page's viewport.  A second Playwright client's
    ``page.screenshot()`` can race that ownership and restore its inferred
    viewport later, so the read-only dashboard uses the raw CDP command.
    """
    result = session.send("Page.captureScreenshot", {
        "format": "png",
        "fromSurface": True,
        "captureBeyondViewport": False,
    })
    return base64.b64decode(result["data"], validate=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only Mahjong Soul browser monitor")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument("--operator-log")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    references = load_references(root / "artifacts" / "live")
    shared = SharedFrame()
    server = ThreadingHTTPServer((args.host, args.port), handler_for(shared))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Dashboard: http://{args.host}:{args.port}", flush=True)
    operator_log = Path(args.operator_log).resolve() if args.operator_log else None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(args.cdp)
            page = find_page(browser)
            session = page.context.new_cdp_session(page)
            while True:
                image = capture_cdp_screenshot(session)
                state, confidence = classify_screen(image, references)
                with shared.lock:
                    shared.image = image
                    shared.status = {
                        "screenState": state,
                        "screenConfidence": confidence,
                        "capturedAt": datetime.now(timezone.utc).isoformat(),
                        "pageUrl": page.url,
                        **read_operator_status(operator_log),
                    }
                time.sleep(max(0.1, args.interval))
    except KeyboardInterrupt:
        return 0
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
