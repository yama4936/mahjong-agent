import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { layoutSchema } from '../src/recognition/layout.js';
import { detectConfiguredPublicRegions } from '../src/recognition/regionDetector.js';

test('blue tinted sanma discard faces are found beside neutral tiles', async () => {
  const layout = layoutSchema.parse(JSON.parse(await readFile('config/layout-runtime.json', 'utf8')));
  const source = 'test/fixtures/sanma-rivers/blue-highlight-redacted.png';
  const baseline = await detectConfiguredPublicRegions(source, layout, { luminanceThreshold: 190 });
  assert.equal(baseline.leftDiscards?.candidates.length, 3);
  assert.equal(baseline.oppositeDiscards?.candidates.length, 2);
  const results = await detectConfiguredPublicRegions(source, layout, { luminanceThreshold: 190, sanmaBlueFaces: true });
  assert.equal(results.leftDiscards?.gridValid, true);
  assert.equal(results.leftDiscards?.candidates.length, 4);
  assert.ok(results.leftDiscards?.candidates.some(tile => tile.x === 699 && tile.y === 326));
  assert.equal(results.oppositeDiscards?.gridValid, true);
  assert.equal(results.oppositeDiscards?.candidates.length, 3);
  assert.ok(results.oppositeDiscards?.candidates.some(tile => tile.x === 1070 && tile.y === 242));
});

test('separate blue mask recovers three tinted tiles in a two-row river', async () => {
  const layout = layoutSchema.parse(JSON.parse(await readFile('config/layout-runtime.json', 'utf8')));
  const result = await detectConfiguredPublicRegions('test/fixtures/sanma-rivers/blue-highlight-multiple-redacted.png', layout, { luminanceThreshold: 190, sanmaBlueFaces: true });
  assert.equal(result.ownDiscards?.gridValid, true);
  assert.deepEqual(result.ownDiscards?.gridRows, [6, 6]);
  assert.equal(result.ownDiscards?.candidates.length, 12);
});
