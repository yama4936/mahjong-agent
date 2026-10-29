import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

class Element {
  textContent = ''; hidden = false; dataset: Record<string, string> = {};
  children: Element[] = []; parent?: Element; scrollTop = 0; clientHeight = 100;
  onclick?: () => void;
  onerror?: () => void;
  src = ''; alt = ''; title = '';
  listeners: Record<string, () => void> = {};
  addEventListener(name: string, callback: () => void) { this.listeners[name] = callback; }
  get scrollHeight() { return this.children.length * 20; }
  get firstElementChild() { return this.children[0]; }
  append(...children: Element[]) { children.forEach(child => { child.parent = this; this.children.push(child); }); }
  replaceChildren(...children: Element[]) { this.children = []; this.append(...children); }
  remove() { this.parent!.children = this.parent!.children.filter(child => child !== this); }
  removeAttribute(name: string) { if (name === 'src') this.src = ''; }
  getBoundingClientRect() { return { height: 20 }; }
  querySelector(selector: string) { return this.children[selector === 'strong' ? 0 : 1]; }
}

function child(element: Element, index: number): Element {
  const result = element.children[index];
  assert.ok(result, `missing child ${index}`);
  return result;
}

function callback(value: (() => void) | undefined): () => void {
  assert.ok(value, 'missing callback');
  return value;
}

function viewer(extra: Record<string, unknown> = {}) {
  const elements = new Map<string, Element>();
  const element = (selector: string) => {
    if (!elements.has(selector)) elements.set(selector, new Element());
    return elements.get(selector)!;
  };
  element('#screen').hidden = true;
  element('#placeholder').append(new Element(), new Element());
  const sockets: FakeSocket[] = [];
  class FakeSocket {
    onmessage?: (event: { data: string }) => void;
    onopen?: () => void;
    onclose?: () => void;
    closed = false;
    constructor(public url: string) { sockets.push(this); }
    close() { this.closed = true; this.onclose?.(); }
  }
  let tick = () => {};
  const timers = new Map<number, () => void>();
  let timerId = 0;
  const visibility: Record<string, () => void> = {};
  const lifecycle: Record<string, () => void> = {};
  const context = {
    document: { hidden: false, querySelector: element, createElement: () => new Element(), addEventListener(name: string, callback: () => void) { visibility[name] = callback; } },
    window: { addEventListener(name: string, callback: () => void) { lifecycle[name] = callback; } }, WebSocket: FakeSocket,
    setTimeout(callback: () => void) { timers.set(++timerId, callback); return timerId; }, clearTimeout(id: number) { timers.delete(id); }, setInterval(callback: () => void) { tick = callback; },
    URL: { revokeObjectURL() {} }, performance: { now: () => 0 }, Date, console, ...extra,
  };
  runInNewContext(readFileSync(new URL('../web/live/live.js', import.meta.url), 'utf8'), context);
  return {
    element, context, sockets, visibility, lifecycle, tick: () => tick(),
    retry() { const pending = [...timers.values()]; timers.clear(); pending.forEach(callback => callback()); },
    events() { return sockets.filter(socket => socket.url.endsWith('/events')).at(-1)!; },
    sendEvent(telemetry: unknown) { this.events().onmessage?.({ data: JSON.stringify({ type: 'telemetry', telemetry }) }); },
    send(telemetry: unknown, state = 'match') { sockets.filter(socket => socket.url.endsWith('/ws')).at(-1)!.onmessage?.({ data: JSON.stringify({ state, telemetry }) }); },
  };
}
const decision = () => ({ timestamp: new Date().toISOString(), action: 'discard', tile: '2p', source: 'jev', winProbability: 0.1234, dealInProbability: 0, recognitionConfidence: 0.9, recognitionSafe: false, shanten: 1 });

test('candidate strip shows tile images, Jev selection probabilities, selection and estimate details', () => {
  const v = viewer();
  const candidates = [
    { action: 'discard', tile: 'E', selected: true, selectionProbability: 0.7, winProbability: 0.2, dealInProbability: 0.1, shanten: 1 },
    { action: 'discard', tile: '0p', selected: false, selectionProbability: 0.3 },
  ];
  v.send({ decision: { ...decision(), candidates } });
  const list = v.element('#decision-options');
  assert.equal(list.hidden, false);
  assert.equal(v.element('#decision-options-empty').hidden, true);
  assert.equal(list.children.length, 2);
  const first = child(list, 0);
  assert.equal(first.dataset.selected, 'true');
  assert.equal(child(first, 0).textContent, '打牌');
  assert.equal(child(child(first, 1), 0).alt, '東');
  assert.equal(child(first, 2).textContent, '70.0%');
  assert.equal(child(first, 3).textContent, '選択');
  assert.match(first.title, /推定和了率 20.0%.*推定放銃率 10.0%.*シャンテン数 1/);
  assert.equal(child(child(list, 1), 1).dataset.red, 'true');
  v.send({ decision: { ...decision(), candidates } });
  assert.equal(list.children[0], first, 'unchanged snapshots preserve DOM and scroll position');
  v.send({ decision: { ...decision(), candidates: [{ action: 'ron', tile: null, selected: false, selectionProbability: null }] } });
  assert.equal(list.children.length, 1);
  assert.equal(child(child(list, 0), 0).textContent, 'ロン');
  assert.equal(child(child(list, 0), 1).textContent, '—');
  v.send({ decision: null });
  assert.equal(list.children.length, 0);
  assert.equal(list.hidden, true);
  assert.equal(v.element('#decision-options-empty').hidden, false);
});

test('candidate strip limits entries and does not interpret unknown tile paths as images', () => {
  const v = viewer();
  v.send({ decision: { ...decision(), candidates: Array.from({ length: 80 }, () => ({ action: 'discard', tile: '../other', selectionProbability: 2 })) } });
  const list = v.element('#decision-options');
  assert.equal(list.children.length, 64);
  assert.equal(child(child(list, 0), 1).textContent, '牌不明');
  assert.equal(child(child(list, 0), 2).textContent, '—');
});

test('live viewer displays probabilities independently from recognition confidence and flags old decisions', () => {
  const v = viewer();
  v.element('#screen').hidden = false;
  v.send({ decision: decision(), logs: [] });
  assert.equal(v.element('#decision-action-label').textContent, '打牌');
  assert.equal(v.element('#decision-tile').src, 'tiles/2p.png?v=8c0f22e7');
  assert.equal(v.element('#decision-win').textContent, '12.3%');
  assert.equal(v.element('#decision-deal-in').textContent, '0.0%');
  assert.equal(v.element('#decision-confidence').textContent, '90.0%');
  assert.match(v.element('#decision-safety').textContent, /safe=false/);
  assert.equal(v.element('.decision-panel').dataset.current, 'true');
  v.send({ decision: decision(), logs: [] }, 'live');
  assert.equal(v.element('.decision-panel').dataset.current, 'true');
  v.send({ decision: { ...decision(), timestamp: '2020-01-01T00:00:00Z' } });
  assert.equal(v.element('.decision-panel').dataset.current, 'false');
  assert.match(v.element('#decision-freshness').textContent, /過去の判断/);
  v.send({ decision: { ...decision(), winProbability: null, dealInProbability: 8 } });
  assert.equal(v.element('#decision-win').textContent, '—');
  assert.equal(v.element('#decision-deal-in').textContent, '—');
});

test('pause, offline and result views do not present previous decisions as current', () => {
  for (const state of ['offline', 'match_result']) {
    const v = viewer();
    v.element('#screen').hidden = false;
    v.send({ decision: decision() }, state);
    assert.equal(v.element('.decision-panel').dataset.current, 'false');
  }
  const v = viewer();
  v.element('#screen').hidden = false;
  v.send({ decision: decision() });
  v.element('#toggle').onclick!();
  assert.equal(v.element('.decision-panel').dataset.current, 'false');
  assert.match(v.element('#decision-freshness').textContent, /一時停止/);
});

test('logs deduplicate snapshots, retain 100 rows, keep text inert and preserve manual scroll', () => {
  const v = viewer();
  const entries = Array.from({ length: 100 }, (_, i) => ({ id: String(i), timestamp: new Date().toISOString(), event: 'click_sent', message: '<img src=x onerror=alert(1)>' }));
  v.send({ logs: entries });
  const logs = v.element('#logs');
  assert.equal(logs.children.length, 100);
  assert.equal(child(child(logs, 0), 2).textContent, '<img src=x onerror=alert(1)>');
  assert.equal(logs.scrollTop, logs.scrollHeight);
  v.send({ logs: entries });
  assert.equal(logs.children.length, 100);
  logs.scrollTop = 500;
  v.send({ logs: [...entries.slice(1), { ...entries[0], id: '100' }] });
  assert.equal(logs.children.length, 100);
  assert.equal(child(logs, 0).dataset.id, '1');
  assert.equal(logs.scrollTop, 480);
  assert.equal(v.element('#logs-latest').hidden, false);
  v.element('#logs-latest').onclick!();
  assert.equal(logs.scrollTop, logs.scrollHeight);
  assert.equal(v.element('#logs-latest').hidden, true);
});

test('event stream updates decisions without video and cannot be overwritten by video metadata', () => {
  const v = viewer();
  v.events().onopen!();
  v.sendEvent({ decision: decision(), logs: [] });
  assert.equal(v.element('#screen').hidden, true);
  assert.equal(v.element('.decision-panel').dataset.current, 'true');
  assert.equal(v.element('#events-status').textContent, 'LIVE');
  assert.match(v.element('#events-received').textContent, /データ受信 /);
  v.send({ decision: { ...decision(), tile: '9m' } });
  assert.equal(v.element('#decision-action-label').textContent, '打牌');
  assert.equal(v.element('#decision-tile').src, 'tiles/2p.png?v=8c0f22e7');
  v.send(null, 'offline');
  v.tick();
  assert.equal(v.element('.decision-panel').dataset.current, 'true');
  v.send(null, 'match_result');
  assert.equal(v.element('.decision-panel').dataset.current, 'false');
});

test('event reconnect and viewer lifecycle close both sockets and cancel pending retries', () => {
  const v = viewer();
  v.events().onopen!();
  v.events().close();
  assert.equal(v.element('#events-status').textContent, '再接続中');
  v.retry();
  assert.equal(v.sockets.length, 3);
  v.events().onopen!();
  v.element('#toggle').onclick!();
  assert.ok(v.sockets.every(socket => socket.closed));
  assert.equal(v.element('#events-status').textContent, '停止');
  v.retry();
  assert.equal(v.sockets.length, 3);
  v.element('#toggle').onclick!();
  assert.equal(v.sockets.length, 5);
  v.context.document.hidden = true;
  callback(v.visibility.visibilitychange)();
  assert.ok(v.sockets.every(socket => socket.closed));
  v.context.document.hidden = false;
  callback(v.visibility.visibilitychange)();
  assert.equal(v.sockets.length, 7);
  callback(v.lifecycle.pagehide)();
  assert.ok(v.sockets.every(socket => socket.closed));
});

test('decision tiles use local allowlisted images, Japanese alt text, and red-five badges', () => {
  const v = viewer();
  v.send({ decision: { ...decision(), tile: 'E' } });
  assert.equal(v.element('#decision-tile').src, 'tiles/E.png?v=8c0f22e7');
  assert.equal(v.element('#decision-tile').alt, '東');
  assert.equal(v.element('#decision-tile-wrap').title, '東');
  assert.equal(v.element('#decision-tile-wrap').hidden, false);
  for (const [tile, name] of [['0m', '赤五萬'], ['0p', '赤五筒'], ['0s', '赤五索']] as const) {
    v.send({ decision: { ...decision(), tile } });
    assert.equal(v.element('#decision-tile').src, `tiles/5${tile[1]}.png?v=8c0f22e7`);
    assert.equal(v.element('#decision-tile').alt, name);
    assert.equal(v.element('#decision-tile-wrap').title, name);
    assert.equal(v.element('#decision-tile-wrap').dataset.red, 'true');
  }
  v.send({ decision: { ...decision(), tile: '../external' } });
  assert.equal(v.element('#decision-tile').src, '');
  assert.equal(v.element('#decision-tile').hidden, true);
  assert.equal(v.element('#decision-tile-fallback').textContent, '牌不明');
  assert.equal(v.element('#decision-tile-wrap').dataset.red, 'false');
  v.send({ decision: { ...decision(), action: 'ron', tile: null } });
  assert.equal(v.element('#decision-action-label').textContent, 'ロン');
  assert.equal(v.element('#decision-tile-wrap').hidden, true);
  assert.equal(v.element('#decision-tile').src, '');
});

test('failed tile images display Japanese tile names and recover when the tile changes', () => {
  const v = viewer();
  v.send({ decision: { ...decision(), tile: 'P' } });
  v.element('#decision-tile').onerror!();
  assert.equal(v.element('#decision-tile').hidden, true);
  assert.equal(v.element('#decision-tile-fallback').hidden, false);
  assert.equal(v.element('#decision-tile-fallback').textContent, '白');
  v.send({ decision: { ...decision(), tile: '9m' } });
  assert.equal(v.element('#decision-tile').hidden, false);
  assert.equal(v.element('#decision-tile-fallback').hidden, true);
  assert.equal(v.element('#decision-tile').alt, '九萬');
  v.send({ decision: null });
  assert.equal(v.element('#decision-action-label').textContent, '—');
  assert.equal(v.element('#decision-tile-wrap').hidden, true);
});

test('decision log entries show tile images while other logs retain their text', () => {
  const v = viewer();
  const entry = { id: 'decision-1', timestamp: new Date().toISOString(), event: 'decision', action: 'discard', tile: 'E', message: '判断を更新: discard E' };
  v.send({ logs: [entry, { ...entry, id: 'other-1', event: 'click_sent' }] });
  const rows = v.element('#logs').children;
  const row = rows[0];
  assert.ok(row);
  const message = child(row, 2);
  assert.equal(message.textContent, '判断を更新: 打牌 ');
  assert.equal(child(child(message, 0), 0).src, 'tiles/E.png?v=8c0f22e7');
  assert.equal(child(child(message, 0), 0).alt, '東');
  callback(child(child(message, 0), 0).onerror)();
  assert.equal(child(child(message, 0), 1).hidden, false);
  const other = rows[1];
  assert.ok(other);
  assert.equal(child(other, 2).textContent, entry.message);
  assert.equal(child(other, 2).children.length, 0);
});

const flush = () => new Promise<void>(resolve => setImmediate(resolve));
function imageResponse(type = 'image/png') {
  return { ok: true, type: 'basic', headers: { get: () => type }, clone() { return this; }, async blob() { return {}; } };
}
test('tile cache fetches lazily once, shares red five images and persists across viewers', async () => {
  const saved = new Map();
  let fetches = 0, blobs = 0;
  const revoked: string[] = [];
  const cache = { async match(url: string) { return saved.get(url); }, async put(url: string, response: unknown) { saved.set(url, response); } };
  const environment = {
    caches: { async open(name: string) { assert.equal(name, 'jantama-tiles-8c0f22e7'); return cache; } },
    async fetch() { fetches++; return imageResponse(); },
    URL: { createObjectURL: () => `blob:tile-${++blobs}`, revokeObjectURL: (url: string) => revoked.push(url) },
  };
  const v = viewer(environment);
  assert.equal(fetches, 0);
  v.send({ decision: { ...decision(), tile: '5m' } });
  await flush();
  const first = v.element('#decision-tile').src;
  assert.match(first, /^blob:/);
  v.send({ decision: { ...decision(), tile: '0m' } });
  await flush();
  assert.equal(v.element('#decision-tile').src, first);
  assert.equal(fetches, 1);
  assert.equal(blobs, 1);
  const second = viewer(environment);
  second.send({ decision: { ...decision(), tile: '5m' } });
  await flush();
  assert.equal(fetches, 1);
  assert.match(second.element('#decision-tile').src, /^blob:/);
  callback(v.lifecycle.pagehide)();
  assert.deepEqual(revoked, [first]);
});

test('tile cache falls back to normal versioned URLs on unavailable storage or invalid responses', async () => {
  for (const environment of [
    { caches: { async open() { throw new Error('denied'); } } },
    { caches: { async open() { return { async match() {} }; } }, async fetch() { throw new Error('offline'); } },
    { caches: { async open() { return { async match() {} }; } }, async fetch() { return imageResponse('text/html'); } },
  ]) {
    const v = viewer(environment);
    v.send({ decision: { ...decision(), tile: 'E' } });
    await flush();
    assert.equal(v.element('#decision-tile').src, 'tiles/E.png?v=8c0f22e7');
  }
});

test('late cached images cannot overwrite a newer tile or survive page exit', async () => {
  let finishEast: (response: ReturnType<typeof imageResponse>) => void = () => {};
  const revoked: string[] = [];
  const v = viewer({
    caches: { async open() { return { async match() {}, async put() {} }; } },
    fetch(url: string) { return url.includes('/E.') ? new Promise(resolve => { finishEast = resolve; }) : Promise.resolve(imageResponse()); },
    URL: { createObjectURL: () => 'blob:late', revokeObjectURL: (url: string) => revoked.push(url) },
  });
  v.send({ decision: { ...decision(), tile: 'E' } });
  await flush();
  v.send({ decision: { ...decision(), tile: null } });
  finishEast(imageResponse());
  await flush();
  assert.equal(v.element('#decision-tile').src, '');
  assert.equal(v.element('#decision-tile-wrap').hidden, true);
  callback(v.lifecycle.pagehide)();
  assert.deepEqual(revoked, ['blob:late']);
  const exiting = viewer({
    caches: { async open() { return { async match() {}, async put() {} }; } },
    fetch() { return new Promise(resolve => { finishEast = resolve; }); },
    URL: { createObjectURL: () => 'blob:after-exit', revokeObjectURL: (url: string) => revoked.push(url) },
  });
  exiting.send({ decision: { ...decision(), tile: 'E' } });
  await flush();
  callback(exiting.lifecycle.pagehide)();
  finishEast(imageResponse());
  await flush();
  assert.equal(exiting.element('#decision-tile').src, '');
  assert.deepEqual(revoked, ['blob:late', 'blob:after-exit']);
});
