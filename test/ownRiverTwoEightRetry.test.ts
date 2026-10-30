import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { layoutSchema } from '../src/recognition/layout.js';
import { HybridTileRecognizer } from '../src/recognition/hybridTileRecognizer.js';
import { recognizeConfiguredPublicTilesWithVit, toPublicTileObservation } from '../src/recognition/publicTileRecognizer.js';
import type { VitTilePrediction } from '../src/recognition/vitRecognizer.js';
const source = 'test/fixtures/own-river-two-eight-source-20261022.png';
async function fixtureLayout() {
  const layout = layoutSchema.parse(JSON.parse(await readFile('config/layout-300-regression.json', 'utf8')));
  return { ...layout, publicTileRegions: { ownDiscards: { ...layout.publicTileRegions!.ownDiscards!, x: 0, y: 0 } } };
}
function prediction(tile: VitTilePrediction['tile'], confidence = .999, runnerUpTile: VitTilePrediction['tile'] = 'P', runnerUpConfidence = .001): VitTilePrediction {
  return { tile, confidence, runnerUpTile, runnerUpConfidence };
}
function model(retry = prediction('2m', .98, '8m', .01), backend: 'hybrid' | 'vit' = 'hybrid', original = prediction('8m', .75, '2m', .24)) {
  const calls: number[] = [];
  return { backend, calls, async classifyTileImages(images: Buffer[]) {
    calls.push(images.length);
    return calls.length === 1 ? [prediction('S'), prediction('W'), prediction('9m'), prediction('5m'), prediction('9p'), original] : images.map(() => retry);
  } };
}
test('native two-man river is restored without changing accepted neighbors or genuine eight-man', {
  skip: !existsSync('.runtime/hybrid-vision/cvmaj-pretrained.tar') || !existsSync('.runtime/hybrid-vision/automajsoul-best-model.pt'),
}, async () => {
  const layout = await fixtureLayout(); const recognizer = new HybridTileRecognizer();
  try {
    const result = await recognizeConfiguredPublicTilesWithVit(source, layout, recognizer);
    assert.deepEqual(toPublicTileObservation(result).ownDiscards, ['S','W','9m','5m','9p','2m']);
    assert.equal(result.ownDiscards!.classificationSafe, true);
    const tile = result.ownDiscards!.recognized.at(-1)!;
    assert.deepEqual([tile.x,tile.y,tile.width,tile.height], [328,10,62,55]);
    assert.ok(tile.confidence >= .95);
    const control = await recognizeConfiguredPublicTilesWithVit('test/fixtures/own-river-two-eight-eight-control-20261022.png', layout, recognizer);
    assert.deepEqual(toPublicTileObservation(control).ownDiscards, ['S','6s','W','1m','3m','7s','7s','N','9m','3m','5p','8m']);
    assert.equal(control.ownDiscards!.classificationSafe, true);
  } finally { await recognizer.close(); }
});
test('weak eight/two-man confusion needs strong padded evidence for either identity', async () => {
  const layout = await fixtureLayout();
  for (const tile of ['2m','8m'] as const) {
    const classifier = model(prediction(tile,.98,tile === '2m' ? '8m' : '2m',.01));
    const r = await recognizeConfiguredPublicTilesWithVit(source, layout, classifier);
    assert.deepEqual(classifier.calls,[6,1]);
    assert.equal(r.ownDiscards!.recognized.at(-1)!.tile,tile);
    assert.equal(r.ownDiscards!.classificationSafe,true);
  }
  for (const retry of [prediction('2m',.94),prediction('2m',.97,'8m',.08),prediction('7m',.999)]) {
    const r = await recognizeConfiguredPublicTilesWithVit(source,layout,model(retry));
    assert.equal(r.ownDiscards!.recognized.at(-1)!.tile,'8m');
    assert.equal(r.ownDiscards!.recognized.at(-1)!.safe,false);
    assert.equal(r.ownDiscards!.classificationSafe,false);
  }
});
test('strong eight-man, other runner-up and ViT avoid the new retry; strict thresholds remain', async () => {
  const layout = await fixtureLayout();
  for (const classifier of [model(undefined,'hybrid',prediction('8m',.96,'2m',.03)), model(undefined,'hybrid',prediction('8m',.75,'6m',.24)), model(undefined,'vit')]) {
    await recognizeConfiguredPublicTilesWithVit(source,layout,classifier);
    assert.deepEqual(classifier.calls,[6]);
  }
  const strict = await recognizeConfiguredPublicTilesWithVit(source,layout,model(),{minimumConfidence:.99});
  assert.equal(strict.ownDiscards!.classificationSafe,false);
});
test('borderline 2m retry requires a matching strong six-pixel crop', async () => {
  const layout = await fixtureLayout();
  for (const [second, safe] of [[prediction('2m', .97, '8m', .01), true],
    [prediction('8m', .99, '2m', .01), false], [prediction('2m', .94, '8m', .01), false]] as const) {
    const classifier = model(prediction('2m', .939, '8m', .048));
    const base = classifier.classifyTileImages.bind(classifier);
    classifier.classifyTileImages = async (images: Buffer[]) => {
      if (classifier.calls.length === 2) { classifier.calls.push(images.length); return images.map(() => second); }
      return base(images);
    };
    const result = await recognizeConfiguredPublicTilesWithVit(source, layout, classifier);
    assert.deepEqual(classifier.calls.slice(0, 3), [6, 1, 1]);
    assert.equal(result.ownDiscards!.classificationSafe, safe);
    assert.equal(result.ownDiscards!.recognized.at(-1)!.tile, safe ? '2m' : '8m');
  }
});
