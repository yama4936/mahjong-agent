import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { layoutSchema } from '../src/recognition/layout.js';
import { HybridTileRecognizer } from '../src/recognition/hybridTileRecognizer.js';
import { recognizeConfiguredPublicTilesWithVit, toPublicTileObservation } from '../src/recognition/publicTileRecognizer.js';
import type { VitTilePrediction } from '../src/recognition/vitRecognizer.js';

async function fixtureLayout() {
  const layout = layoutSchema.parse(JSON.parse(await readFile('config/layout-300-regression.json', 'utf8')));
  return { ...layout, publicTileRegions: { oppositeMelds: { ...layout.publicTileRegions!.oppositeMelds!, x: 0, y: 0 } } };
}
const source = 'test/fixtures/opposite-chi-source-20261021.png';
function prediction(tile: VitTilePrediction['tile'], confidence: number, runnerUpTile: VitTilePrediction['tile'] = 'P', runnerUpConfidence = .01): VitTilePrediction {
  return { tile, confidence, runnerUpTile, runnerUpConfidence };
}
function classifier(initial: VitTilePrediction[], retry = prediction('7m', .97, '6m', .02), backend = 'hybrid' as 'hybrid' | 'vit') {
  const calls: number[] = [];
  return { backend, calls, async classifyTileImages(images: Buffer[]) {
    calls.push(images.length);
    return calls.length === 1 ? initial : images.map(() => retry);
  } };
}
const initial = () => [prediction('8m', .98), prediction('6m', .997), prediction('6m', .8, '7m', .19)];

test('actual upside-down chi crops recover the seven, retain coordinates, and leave empty region empty', {
  skip: !existsSync('.runtime/hybrid-vision/cvmaj-pretrained.tar') || !existsSync('.runtime/hybrid-vision/automajsoul-best-model.pt'),
}, async () => {
  const layout = await fixtureLayout();
  const fixture = JSON.parse(await readFile('test/fixtures/opposite-chi-20261021.json', 'utf8'));
  const recognizer = new HybridTileRecognizer();
  try {
    for (const row of fixture.cases) {
      const recognition = await recognizeConfiguredPublicTilesWithVit(row.file, layout, recognizer);
      const opponent = toPublicTileObservation(recognition, 'north').opponentDiscards[1]!;
      assert.equal(opponent.seat, 'south');
      assert.equal(opponent.meldsObserved, true, row.file);
      assert.deepEqual(opponent.melds?.map(m => ({ type: m.type, tiles: [...m.tiles].sort() })), row.expectedMelds, row.file);
      if (row.expectedMelds.length) {
        const seven = recognition.oppositeMelds!.recognized.find(t => t.tile === '7m')!;
        assert.ok(seven.confidence >= .95);
        assert.equal(seven.y, 16); // Original candidate coordinates, not padded crop bounds.
        assert.equal(seven.height, 32);
      }
    }
  } finally { await recognizer.close(); }
});

test('retry requires stronger independent evidence and publishes the complete chi at the observation boundary', async () => {
  const layout = await fixtureLayout();
  const model = classifier(initial());
  const result = await recognizeConfiguredPublicTilesWithVit(source, layout, model);
  assert.deepEqual(model.calls, [3, 1]);
  assert.deepEqual(toPublicTileObservation(result, 'north').opponentDiscards[1]!.melds?.[0]!.tiles, ['6m', '7m', '8m']);
  assert.equal(toPublicTileObservation(result, 'north').opponentDiscards[1]!.meldsObserved, true);
  for (const retry of [prediction('7m', .94), prediction('7m', .97, '6m', .08), prediction('6m', .999)]) {
    const result = await recognizeConfiguredPublicTilesWithVit(source, layout, classifier(initial(), retry));
    assert.equal(toPublicTileObservation(result).opponentDiscards[1]!.meldsObserved, false);
    assert.deepEqual(toPublicTileObservation(result).opponentDiscards[1]!.melds, []);
  }
  const strict = await recognizeConfiguredPublicTilesWithVit(source, layout, classifier(initial()), { minimumConfidence: .99 });
  assert.equal(toPublicTileObservation(strict).opponentDiscards[1]!.meldsObserved, false);
});

test('valid melds, other backends, wrong runner-up and stronger originals avoid retries', async () => {
  const layout = await fixtureLayout();
  const cases = [
    classifier([prediction('6m', .98), prediction('6m', .997), prediction('6m', .8, '7m', .19)]),
    classifier(initial(), undefined, 'vit'),
    classifier([prediction('8m', .98), prediction('6m', .997), prediction('6m', .8, '8m', .19)]),
    classifier([prediction('8m', .98), prediction('6m', .997), prediction('6m', .94, '7m', .05)]),
  ];
  for (const model of cases) {
    await recognizeConfiguredPublicTilesWithVit(source, layout, model);
    assert.deepEqual(model.calls, [3]);
  }
  const model = classifier(initial());
  const otherRegion = { ...layout, publicTileRegions: { ownMelds: layout.publicTileRegions.oppositeMelds } };
  await recognizeConfiguredPublicTilesWithVit(source, otherRegion, model);
  assert.deepEqual(model.calls, [3]);
});
