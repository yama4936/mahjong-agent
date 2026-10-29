import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

class Element {
  textContent = ''; hidden = false; dataset: Record<string, string> = {};
  children: Element[] = []; parent?: Element; scrollTop = 0; clientHeight = 100;
  onclick?: () => void;
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
  let ws: FakeSocket;
  class FakeSocket {
    onmessage?: (event: { data: string }) => void;
    onclose?: () => void;
    constructor() { ws = this; }
    close() { this.onclose?.(); }
  }
  let tick = () => {};
  const context = {
    document: { hidden: false, querySelector: element, createElement: () => new Element(), addEventListener() {} },
    window: { addEventListener() {} }, WebSocket: FakeSocket,
    setTimeout() {}, clearTimeout() {}, setInterval(callback: () => void) { tick = callback; },
    URL: { revokeObjectURL() {} }, performance: { now: () => 0 }, Date, console,
  };
  runInNewContext(readFileSync(new URL('../web/live/live.js', import.meta.url), 'utf8'), context);
  return {
    element, context, tick: () => tick(),
    send(telemetry: unknown, state = 'match') { ws.onmessage?.({ data: JSON.stringify({ state, telemetry }) }); },
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
});
