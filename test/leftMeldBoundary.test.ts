import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { layoutSchema } from '../src/recognition/layout.js';
import { detectConfiguredPublicRegions } from '../src/recognition/regionDetector.js';
import { HybridTileRecognizer } from '../src/recognition/hybridTileRecognizer.js';
import { recognizeConfiguredPublicTilesWithVit, toPublicTileObservation } from '../src/recognition/publicTileRecognizer.js';
import { cachedPublicStatePatch } from '../src/agent/publicCache.js';
import { gameStateSchema, publicGameStateSchema } from '../src/game/state.js';
const source = 'test/fixtures/left-meld-boundary-source-20261022.jpg';
async function layout() {
  const base = layoutSchema.parse(JSON.parse(await readFile('config/layout-300-regression.json', 'utf8')));
  return {...base, publicTileRegions: {leftMelds: base.publicTileRegions!.leftMelds!}};
}

test('native left row extends across the crop boundary and excludes avatar and concealed tiles', async () => {
  const base = await layout();
  const before = (await detectConfiguredPublicRegions(source, base, {extendMeldBoundaries:false})).leftMelds!;
  const after = (await detectConfiguredPublicRegions(source, base)).leftMelds!;
  assert.equal(before.candidates.length, 6);
  assert.equal(after.candidates.length, 9);
  assert.deepEqual(after.candidates.slice(3), before.candidates);
  assert.deepEqual(after.candidates.slice(0,3).map(t=>[t.x,t.y,t.width,t.height]),
    [[214,454,83,37],[200,495,84,39],[181,539,72,54]]);
  assert.deepEqual(base.publicTileRegions.leftMelds, (await layout()).publicTileRegions.leftMelds);
  // The wider rectangle contains a bright avatar and concealed-hand faces;
  // none is part of this continuous slanted meld row.
  assert.ok(after.candidates.every(t => t.y >= 454 && t.y < 937));
  const two = (await detectConfiguredPublicRegions('test/fixtures/left-meld-boundary-two-pon-control-20261022.jpg',base)).leftMelds!;
  assert.equal(two.candidates.length,6);
  const empty = (await detectConfiguredPublicRegions('test/fixtures/left-meld-boundary-empty-control-20261022.jpg',base)).leftMelds!;
  assert.equal(empty.candidates.length,0);
  const wrongOrientation = {...base,publicTileRegions:{leftMelds:{...base.publicTileRegions.leftMelds,rotationToUpright:90 as const}}};
  assert.equal((await detectConfiguredPublicRegions(source,wrongOrientation)).leftMelds!.candidates.length,6);
});

test('real classifier recovers all three pons in two native frames and applies the missing yakuhai', {
  skip:!existsSync('.runtime/hybrid-vision/cvmaj-pretrained.tar') || !existsSync('.runtime/hybrid-vision/automajsoul-best-model.pt'),
}, async () => {
  const fixture = JSON.parse(await readFile('test/fixtures/left-meld-boundary-20261022.json','utf8'));
  const base = await layout(), classifier = new HybridTileRecognizer();
  try {
    for (const file of [source,'test/fixtures/left-meld-boundary-holdout-20261022.jpg']) {
      const old = toPublicTileObservation(await recognizeConfiguredPublicTilesWithVit(file,base,classifier,{extendMeldBoundaries:false}),'north');
      assert.equal(old.opponentDiscards[2]!.meldsObserved,true);
      assert.equal(old.opponentDiscards[2]!.melds!.length,2);
      const obs = toPublicTileObservation(await recognizeConfiguredPublicTilesWithVit(file,base,classifier),'north');
      const left = obs.opponentDiscards[2]!;
      assert.equal(left.meldsObserved,true);
      assert.deepEqual(left.melds!.map(m=>m.tiles), [['7s','7s','7s'],['3s','3s','3s'],['F','F','F']]);
      const state = gameStateSchema.parse(fixture.nativeDecisionState);
      obs.doraIndicators = state.doraIndicators;
      obs.ownDiscards = state.ownDiscards;
      obs.opponentDiscards = obs.opponentDiscards.map(opponent => ({...opponent,
        discards:state.opponents!.find(p=>p.seat===opponent.seat)!.discards}));
      const patch = cachedPublicStatePatch({...obs,capturedAt:'2026-10-22T13:11:14Z',recognizedAt:'2026-10-22T13:11:15Z',recognitionLatencyMs:100,configuredRegions:['leftMelds']},
        [...state.hand,...(state.draw?[state.draw]:[])],state.opponents);
      const applied = publicGameStateSchema.parse({...state,...patch.patch}).opponents!.find(p=>p.seat==='west')!;
      assert.equal(applied.openMelds,3);assert.equal(applied.openMeldsObserved,true);
      assert.ok(applied.melds!.some(m=>m.tiles.every(tile=>tile==='F')));
    }
    for (const [file,count] of [['two-pon-control',2],['empty-control',0]] as const) {
      const obs=toPublicTileObservation(await recognizeConfiguredPublicTilesWithVit(`test/fixtures/left-meld-boundary-${file}-20261022.jpg`,base,classifier),'north');
      assert.equal(obs.opponentDiscards[2]!.meldsObserved,true);
      assert.equal(obs.opponentDiscards[2]!.melds!.length,count);
    }
  } finally {await classifier.close();}
});
