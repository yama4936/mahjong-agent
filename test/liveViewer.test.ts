import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

class Element {
  textContent = ''; hidden = false; dataset: Record<string, string> = {};
  children: Element[] = []; parent?: Element; scrollTop = 0; clientHeight = 100;
  onclick?: () => void;
  listeners: Record<string, () => void> = {};
  addEventListener(name: string, callback: () => void) { this.listeners[name] = callback; }
  get scrollHeight() { return this.children.length * 20; }
  get firstElementChild() { return this.children[0]; }
  append(...children: Element[]) { children.forEach(child => { child.parent = this; this.children.push(child); }); }
  remove() { this.parent!.children = this.parent!.children.filter(child => child !== this); }
  removeAttribute() {}
  getBoundingClientRect() { return { height: 20 }; }
  querySelector(selector: string) { return this.children[selector === 'strong' ? 0 : 1]; }
}

function viewer() {
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
    URL: { revokeObjectURL() {} }, performance: { now: () => 0 }, Date, console,
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

test('live viewer displays probabilities independently from recognition confidence and flags old decisions', () => {
  const v = viewer();
  v.element('#screen').hidden = false;
  v.send({ decision: decision(), logs: [] });
  assert.equal(v.element('#decision-action').textContent, '打牌 2p');
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
  assert.equal(logs.children[0].children[2].textContent, '<img src=x onerror=alert(1)>');
  assert.equal(logs.scrollTop, logs.scrollHeight);
  v.send({ logs: entries });
  assert.equal(logs.children.length, 100);
  logs.scrollTop = 500;
  v.send({ logs: [...entries.slice(1), { ...entries[0], id: '100' }] });
  assert.equal(logs.children.length, 100);
  assert.equal(logs.children[0].dataset.id, '1');
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
  assert.equal(v.element('#decision-action').textContent, '打牌 2p');
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
  v.visibility.visibilitychange();
  assert.ok(v.sockets.every(socket => socket.closed));
  v.context.document.hidden = false;
  v.visibility.visibilitychange();
  assert.equal(v.sockets.length, 7);
  v.lifecycle.pagehide();
  assert.ok(v.sockets.every(socket => socket.closed));
});
