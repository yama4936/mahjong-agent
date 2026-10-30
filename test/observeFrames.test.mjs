import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { parseOptions, selectGamePage, captureFrames } from '../scripts/observe-frames.mjs';

test('requires explicit positive count and interval and rejects unknown options', () => {
  assert.throws(() => parseOptions(['--output', 'x']));
  assert.throws(() => parseOptions(['--output', 'x', '--count', '0', '--interval-ms', '20']));
  assert.throws(() => parseOptions(['--output', 'x', '--count', '1', '--interval-ms', '20', '--start']));
  assert.equal(parseOptions(['--output', 'x', '--count', '2', '--interval-ms', '20']).count, 2);
});
test('rejects missing, multiple, and deceptive page URLs', () => {
  const context = urls => ({ pages: () => urls.map(url => ({ url: () => url })) });
  assert.throws(() => selectGamePage([context(['https://game.mahjongsoul.com.evil.test/'])]));
  assert.throws(() => selectGamePage([context(['https://game.mahjongsoul.com/', 'https://game.mahjongsoul.com/index.html'])]));
  assert.equal(selectGamePage([context(['https://game.mahjongsoul.com/index.html'])]).url(), 'https://game.mahjongsoul.com/index.html');
});
test('captures requested frames with timestamps and digest, without other page operations', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'frame-test-'));
  try {
    const image = Buffer.from('test image'); let calls = 0; const waits = [];
    const page = { screenshot: async () => { calls++; return image; } };
    await captureFrames(page, { output: dir, count: 2, intervalMs: 123 }, { sleep: async ms => waits.push(ms), now: () => new Date('2026-10-30T15:00:00Z') });
    const rows = (await readFile(path.join(dir, 'manifest.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
    assert.equal(calls, 2); assert.deepEqual(waits, [123]); assert.equal(rows.length, 2);
    for (const row of rows) { assert.equal(row.sha256, createHash('sha256').update(image).digest('hex')); assert.deepEqual(await readFile(path.join(dir, row.filename)), image); assert.equal(row.capturedAt, '2026-10-30T15:00:00.000Z'); }
  } finally { await rm(dir, { recursive: true, force: true }); }
});
