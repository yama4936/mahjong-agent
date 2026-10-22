import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { layoutSchema } from '../src/recognition/layout.js';
import { HybridTileRecognizer } from '../src/recognition/hybridTileRecognizer.js';
import { recognizeConfiguredPublicTilesWithVit, toPublicTileObservation, opponentStatesFromObservation } from '../src/recognition/publicTileRecognizer.js';
import type { VitTilePrediction } from '../src/recognition/vitRecognizer.js';
const source = 'test/fixtures/right-chi-678m-source-20261022.png';
async function layout() {
  const base = layoutSchema.parse(JSON.parse(await readFile('config/layout-300-regression.json', 'utf8')));
  return { ...base, publicTileRegions: { rightMelds: { ...base.publicTileRegions!.rightMelds!, x: 0, y: 0 } } };
}
const p = (tile: VitTilePrediction['tile'], confidence: number, runnerUpTile: VitTilePrediction['tile'] = 'P', runnerUpConfidence = .001): VitTilePrediction => ({tile,confidence,runnerUpTile,runnerUpConfidence});
const initial = () => [p('E',.999),p('E',.999),p('E',.999),p('7m',.872,'8m',.127),p('6m',.995),p('6m',.710,'8m',.251)];
function model(retry = [p('8m',.982,'6m',.016),p('8m',.996,'6m',.003)], values = initial(), backend: 'hybrid'|'vit' = 'hybrid') {
  const calls: number[] = [];
  return {backend,calls,async classifyTileImages(images: Buffer[]) { calls.push(images.length);return calls.length===1?values:retry; }};
}

test('two independent face trims recover native right chi and retain full-region coordinates', async()=>{
  const classifier=model(),result=await recognizeConfiguredPublicTilesWithVit(source,await layout(),classifier);
  assert.deepEqual(classifier.calls,[6,2]);
  const obs=toPublicTileObservation(result,'south'),right=obs.opponentDiscards[0]!;
  assert.equal(right.seat,'west');assert.equal(right.meldsObserved,true);
  assert.deepEqual(right.melds!.map(m=>({type:m.type,tiles:[...m.tiles].sort()})),[{type:'pon',tiles:['E','E','E']},{type:'chi',tiles:['6m','7m','8m']}]);
  const tile=result.rightMelds!.recognized[5]!;
  assert.deepEqual([tile.x,tile.y,tile.width,tile.height],[68,175,59,39]);assert.equal(tile.confidence,.982);
  const applied=opponentStatesFromObservation(obs,[{seat:'west',discards:[],riichi:false,openMelds:1,openMeldsObserved:false,melds:[{type:'pon',tiles:['E','E','E']}]}]);
  assert.equal(applied[0]!.openMelds,2);assert.equal(applied[0]!.openMeldsObserved,true);
});

test('legal shape alone, weak/disagreeing retries or configured thresholds cannot promote a chi',async()=>{
  for(const retries of [
    [p('8m',.94),p('8m',.99)], [p('8m',.99),p('8m',.96,'6m',.08)],
    [p('8m',.99),p('6m',.999)], [p('6m',.999),p('6m',.999)],
  ]) {
    const result=await recognizeConfiguredPublicTilesWithVit(source,await layout(),model(retries));
    assert.equal(toPublicTileObservation(result).opponentDiscards[0]!.meldsObserved,false);
    assert.equal(result.rightMelds!.recognized[5]!.tile,'6m');
  }
  for(const options of [{minimumConfidence:.99},{minimumMargin:.98},{retryRightChiMeld:false}]) {
    const result=await recognizeConfiguredPublicTilesWithVit(source,await layout(),model(),options);
    assert.equal(toPublicTileObservation(result).opponentDiscards[0]!.meldsObserved,false);
  }
  const strong=initial();strong[5]=p('6m',.89,'8m',.10);
  const result=await recognizeConfiguredPublicTilesWithVit(source,await layout(),model(undefined,strong));
  assert.equal(toPublicTileObservation(result).opponentDiscards[0]!.meldsObserved,false); // <.15 independent gain
});

test('complete melds, weak anchors, unsafe region, other backend and wrong runner avoid retries',async()=>{
  const complete=initial();complete[5]=p('8m',.98);
  const weak=initial();weak[3]=p('7m',.84,'8m',.15);
  const wrong=initial();wrong[5]=p('6m',.71,'9m',.25);
  const strong=initial();strong[5]=p('6m',.91,'8m',.08);
  const unsafe=initial();unsafe[0]=p('E',.49,'W',.48);
  for(const classifier of [model(undefined,complete),model(undefined,weak),model(undefined,wrong),model(undefined,strong),model(undefined,unsafe),model(undefined,initial(),'vit')]) {
    await recognizeConfiguredPublicTilesWithVit(source,await layout(),classifier);assert.deepEqual(classifier.calls,[6]);
  }
  const other=await layout();const classifier=model();
  await recognizeConfiguredPublicTilesWithVit(source,{...other,publicTileRegions:{ownMelds:other.publicTileRegions.rightMelds}},classifier);
  assert.deepEqual(classifier.calls,[6]);
});

test('native source and later unused frame recover the same chi with real Hybrid',{
  skip:!existsSync('.runtime/hybrid-vision/cvmaj-pretrained.tar')||!existsSync('.runtime/hybrid-vision/automajsoul-best-model.pt'),
},async()=>{
  const fixture=JSON.parse(await readFile('test/fixtures/right-chi-678m-20261022.json','utf8'));
  const recognizer=new HybridTileRecognizer();
  try {for(const row of fixture.cases){
    const before=await recognizeConfiguredPublicTilesWithVit(row.file,await layout(),recognizer,{retryRightChiMeld:false});
    assert.equal(toPublicTileObservation(before).opponentDiscards[0]!.meldsObserved,false,row.kind);
    const after=await recognizeConfiguredPublicTilesWithVit(row.file,await layout(),recognizer);
    const right=toPublicTileObservation(after,'south').opponentDiscards[0]!;
    assert.equal(right.meldsObserved,true,row.kind);
    assert.deepEqual(right.melds!.map(m=>({type:m.type,tiles:[...m.tiles].sort()})),row.expectedMelds,row.kind);
    assert.ok(after.rightMelds!.recognized[5]!.confidence>=.95);
  }}finally{await recognizer.close();}
});
