import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { layoutSchema } from '../src/recognition/layout.js';
import { HybridTileRecognizer } from '../src/recognition/hybridTileRecognizer.js';
import { recognizeConfiguredPublicTilesWithVit, toPublicTileObservation } from '../src/recognition/publicTileRecognizer.js';
import type { VitTilePrediction } from '../src/recognition/vitRecognizer.js';
const source = 'test/fixtures/right-pons-sideways-eight-20261022.png';
async function fixtureLayout() {
  const layout = layoutSchema.parse(JSON.parse(await readFile('config/layout-300-regression.json', 'utf8')));
  return { ...layout, publicTileRegions: { rightMelds: { ...layout.publicTileRegions!.rightMelds!, x: 0, y: 0 } } };
}
function prediction(tile: VitTilePrediction['tile'], confidence = .999, runnerUpTile: VitTilePrediction['tile'] = 'P', runnerUpConfidence = .001): VitTilePrediction {
  return { tile, confidence, runnerUpTile, runnerUpConfidence };
}
const initial = () => ['2p','2p','2p','8m','8m','6m','C','C','C'].map((t,i) => i === 5
  ? prediction('6m', .71, '8m', .25) : prediction(t as VitTilePrediction['tile']));
function classifier(first = initial(), retry = prediction('8m', .98, '6m', .016), backend: 'hybrid' | 'vit' = 'hybrid') {
  const calls: number[] = [];
  return { backend, calls, async classifyTileImages(images: Buffer[]) {
    calls.push(images.length); return calls.length === 1 ? first : images.map(() => retry);
  } };
}
test('native right-side three pons recover sideways eight-man and preserve detection coordinates', {
  skip: !existsSync('.runtime/hybrid-vision/cvmaj-pretrained.tar') || !existsSync('.runtime/hybrid-vision/automajsoul-best-model.pt'),
}, async () => {
  const layout = await fixtureLayout();
  const recognizer = new HybridTileRecognizer();
  try {
    const result = await recognizeConfiguredPublicTilesWithVit(source, layout, recognizer);
    const opponent = toPublicTileObservation(result, 'south').opponentDiscards[0]!;
    assert.equal(opponent.seat, 'west');
    assert.equal(opponent.meldsObserved, true);
    assert.deepEqual(opponent.melds?.map(m => m.tiles), [['2p','2p','2p'], ['8m','8m','8m'], ['C','C','C']]);
    const tile = result.rightMelds!.recognized[5]!;
    assert.deepEqual([tile.x,tile.y,tile.width,tile.height,tile.sideways], [68,175,59,39,true]);
    assert.ok(tile.confidence >= .95);
    assert.ok(tile.ambiguityMargin >= .9);
  } finally { await recognizer.close(); }
});
test('right meld retry requires strong image evidence, anchors and complete legal partition', async () => {
  const layout = await fixtureLayout();
  const model = classifier();
  const result = await recognizeConfiguredPublicTilesWithVit(source, layout, model);
  assert.deepEqual(model.calls, [9,1]);
  assert.equal(toPublicTileObservation(result).opponentDiscards[0]!.meldsObserved, true);
  for (const retry of [prediction('8m', .94), prediction('8m', .97, '6m', .08), prediction('6m', .999)]) {
    const r = await recognizeConfiguredPublicTilesWithVit(source, layout, classifier(initial(), retry));
    assert.equal(toPublicTileObservation(r).opponentDiscards[0]!.meldsObserved, false);
  }
  const bad = initial(); bad[8] = prediction('F');
  const r = await recognizeConfiguredPublicTilesWithVit(source, layout, classifier(bad));
  assert.equal(toPublicTileObservation(r).opponentDiscards[0]!.meldsObserved, false);
  const strict = await recognizeConfiguredPublicTilesWithVit(source, layout, classifier(), { minimumConfidence: .99 });
  assert.equal(toPublicTileObservation(strict).opponentDiscards[0]!.meldsObserved, false);
});
test('valid six-man pon, stronger originals, wrong runner-up, absent anchors and other backends do not retry', async () => {
  const layout = await fixtureLayout();
  const valid = initial(); valid[3] = prediction('6m'); valid[4] = prediction('6m');
  const strong = initial(); strong[5] = prediction('6m', .94, '8m', .05);
  const wrong = initial(); wrong[5] = prediction('6m', .71, '7m', .25);
  const unanchored = initial(); unanchored[4] = prediction('8m', .94);
  for (const model of [classifier(valid), classifier(strong), classifier(wrong), classifier(unanchored), classifier(initial(), undefined, 'vit')]) {
    await recognizeConfiguredPublicTilesWithVit(source, layout, model);
    assert.deepEqual(model.calls, [9]);
  }
});
