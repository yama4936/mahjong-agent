import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { chromium } from 'playwright';

// Run against the repository static preview in an independent browser.
// No connection to the game browser or public WebSocket is made.
const base = process.env.LIVE_PREVIEW_URL || 'http://127.0.0.1:8769';
const frame = process.env.LIVE_PREVIEW_FRAME
  ? 'data:image/jpeg;base64,' + readFileSync(process.env.LIVE_PREVIEW_FRAME).toString('base64')
  : 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><rect width="1920" height="1080" fill="#152f31"/></svg>');
const browser = await chromium.launch({ headless: true });
try {
  for (const path of ['/web/results/src/live.html', '/web/live/live.html']) {
    const page = await browser.newPage();
    let tileFetches = 0;
    page.on('request', request => { if (request.url().includes('/tiles/E.png')) tileFetches++; });
    await page.routeWebSocket('**/*', ws => {
      if (ws.url().endsWith('/events')) ws.send(JSON.stringify({ type: 'telemetry', telemetry: {
        decision: { action: 'discard', tile: 'E', timestamp: new Date().toISOString() }, logs: [],
      } }));
    });
    for (const [width, height] of [[1440, 900], [1366, 768], [1280, 720], [1024, 768], [390, 844], [844, 390]]) {
      await page.setViewportSize({ width, height });
      await page.goto(base + path);
      await page.waitForFunction(() => {
        const image = document.querySelector('#decision-tile');
        return image?.alt === '東' && image.complete && image.naturalWidth > 0;
      });
      await page.evaluate(async frame => {
        document.querySelector('#decision-action-label').textContent = '打牌';
        document.querySelector('#decision-freshness').textContent = '直近の判断（15秒以内）';
        document.querySelector('#decision-time').textContent = '判断 2026/10/29 15:41:41 JST';
        document.querySelector('#decision-safety').textContent = '認識安全判定 safe=false（要確認）';
        document.querySelector('#events-received').textContent = 'データ受信 2026/10/29 15:41:41 JST';
        document.querySelector('#log-latest').textContent = '最新ログ 2026/10/29 15:41:41 JST';
        const logs = document.querySelector('#logs');
        for (let i = 0; i < 100; i++) {
          const row = document.createElement('li');
          for (const [tag, label, className] of [['time', '2026/10/29 15:41:41 JST', ''],
            ['span', 'own_discard_reconciled', 'log-event'], ['span', '打牌を確認', 'log-message']]) {
            const item = document.createElement(tag);
            item.textContent = label;
            item.className = className;
            row.append(item);
          }
          logs.append(row);
        }
        document.querySelector('#logs-latest').hidden = false;
        document.querySelector('#log-empty').hidden = true;
        const image = document.querySelector('#screen');
        await new Promise((resolve, reject) => {
          image.onload = resolve;
          image.onerror = reject;
          image.src = frame;
        });
        image.hidden = false;
        document.querySelector('#placeholder').hidden = true;
      }, frame);
      const geometry = await page.evaluate(() => {
        const box = selector => {
          const { x, y, width, height, bottom, right } = document.querySelector(selector).getBoundingClientRect();
          return { x, y, width, height, bottom, right };
        };
        return { scrollHeight: document.documentElement.scrollHeight, scrollWidth: document.documentElement.scrollWidth,
          player: box('.player'), controls: box('.controls'), logs: box('.log-panel'), decision: box('.decision-panel') };
      });
      assert.ok(geometry.scrollWidth <= width + 1, `${path} ${width} horizontal overflow`);
      if (height >= 550) {
        assert.ok(geometry.scrollHeight <= height + 1, `${path} ${width}x${height} page scroll: ${JSON.stringify(geometry)}`);
        for (const name of ['player', 'controls', 'logs', 'decision']) {
          const box = geometry[name];
          assert.ok(box.y >= 0 && box.bottom <= height + 1 && box.right <= width + 1,
            `${path} ${width}x${height} ${name} outside viewport: ${JSON.stringify(box)}`);
        }
        assert.ok(geometry.player.height >= 130 && geometry.logs.height >= 110, 'Media and logs must stay usable');
      }
      console.log(JSON.stringify({ path, width, height, ...geometry }));
      if (process.env.LIVE_SCREENSHOT_DIR && width === 1366) {
        await page.screenshot({ path: `${process.env.LIVE_SCREENSHOT_DIR}/${path.includes('results') ? 'site' : 'standalone'}.png` });
      }
    }
    assert.equal(tileFetches, 1, `${path}: tile should persist across reloads without another network request`);
    console.log(JSON.stringify({ path, tileFetches, reloads: 6, cache: 'persistent hit' }));
    await page.close();
  }
} finally {
  await browser.close();
}
