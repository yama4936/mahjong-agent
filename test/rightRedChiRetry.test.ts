import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import sharp from 'sharp';
import { layoutSchema } from '../src/recognition/layout.js';
import { HybridTileRecognizer } from '../src/recognition/hybridTileRecognizer.js';
import { recognizeConfiguredPublicTilesWithVit, toPublicTileObservation } from '../src/recognition/publicTileRecognizer.js';
import { normalizeRedManNumeral } from '../src/recognition/redManNumeral.js';
import type { VitTilePrediction } from '../src/recognition/vitRecognizer.js';
const source = 'test/fixtures/right-red-chi-source-20261022.png';
const control = 'test/fixtures/right-red-chi-red-pon-control-20261022.png';
async function fixtureLayout() {
  const base = layoutSchema.parse(JSON.parse(await readFile('config/layout-300-regression.json','utf8')));
  return {...base,publicTileRegions:{rightMelds:{...base.publicTileRegions!.rightMelds!,x:0,y:0}}};
}
function prediction(tile:VitTilePrediction['tile'],confidence:number,runnerUpTile:VitTilePrediction['tile']='P',runnerUpConfidence=.001):VitTilePrediction {
  return {tile,confidence,runnerUpTile,runnerUpConfidence};
}
function model(retry=[prediction('5m',.994,'3m',.004),prediction('4m',.999,'6m',.001)],backend:'hybrid'|'vit'='hybrid',strongAnchor=true) {
  const calls:number[]=[];
  return {backend,calls,async classifyTileImages(images:Buffer[]) {calls.push(images.length);return calls.length===1
    ? [prediction('5m',.46,'9m',.24),prediction('3m',strongAnchor ? .98 : .94,'8m',.01),prediction('4m',.43,'5m',.40)]:retry;}};
}
test('native right red chi recovers all faces with separate red evidence and unchanged coordinates',{
  skip:!existsSync('.runtime/hybrid-vision/cvmaj-pretrained.tar')||!existsSync('.runtime/hybrid-vision/automajsoul-best-model.pt'),
},async()=>{
  const layout=await fixtureLayout(),recognizer=new HybridTileRecognizer();
  try {
    const before=await recognizeConfiguredPublicTilesWithVit(source,layout,recognizer,{retryRightRedMeld:false});
    assert.equal(before.rightMelds!.classificationSafe,false);
    assert.deepEqual(before.rightMelds!.recognized.map(t=>t.tile),['5m','3m','4m']);
    const result=await recognizeConfiguredPublicTilesWithVit(source,layout,recognizer);
    const opponent=toPublicTileObservation(result,'west').opponentDiscards[0]!;
    assert.equal(opponent.seat,'north');assert.equal(opponent.meldsObserved,true);
    assert.deepEqual(opponent.melds?.map(m=>({type:m.type,tiles:[...m.tiles].sort()})),[{type:'chi',tiles:['0m','3m','4m']}]);
    const red=result.rightMelds!.recognized[0]!;
    assert.deepEqual([red.x,red.y,red.width,red.height],[5,17,65,25]);
    assert.ok(red.confidence>=.95);assert.ok(red.ambiguityMargin>=.9);assert.ok(red.redNumeralEvidence!.redFraction>=.8);
    const ordinary=result.rightMelds!.recognized[1]!;assert.equal(ordinary.tile,'3m');assert.equal(ordinary.confidence,0.9727947115898132);
    const controlBefore=await recognizeConfiguredPublicTilesWithVit(control,layout,recognizer,{retryRightRedMeld:false});
    const retained=await recognizeConfiguredPublicTilesWithVit(control,layout,recognizer);
    assert.equal(controlBefore.rightMelds!.classificationSafe,false);
    assert.deepEqual(toPublicTileObservation(retained).opponentDiscards[0]!.melds?.map(m=>({type:m.type,tiles:[...m.tiles].sort()})),[{type:'pon',tiles:['0m','5m','5m']}]);
    assert.deepEqual(retained.rightMelds!.recognized[0],controlBefore.rightMelds!.recognized[0]);
    assert.deepEqual(retained.rightMelds!.recognized[2],controlBefore.rightMelds!.recognized[2]);
  }finally{await recognizer.close();}
});
test('right red chi requires two strong families, a strong anchor, configured thresholds and Hybrid',async()=>{
  const layout=await fixtureLayout(),classifier=model();
  const r=await recognizeConfiguredPublicTilesWithVit(source,layout,classifier);
  assert.deepEqual(classifier.calls,[3,2]);assert.equal(toPublicTileObservation(r).opponentDiscards[0]!.meldsObserved,true);
  for(const retries of [[prediction('5m',.94),prediction('4m',.999)],[prediction('5m',.99,'3m',.1),prediction('4m',.999)],[prediction('9m',.999),prediction('4m',.999)],[prediction('5m',.999),prediction('4m',.94)]]) {
    const result=await recognizeConfiguredPublicTilesWithVit(source,layout,model(retries));
    assert.equal(toPublicTileObservation(result).opponentDiscards[0]!.meldsObserved,false);
    assert.deepEqual(result.rightMelds!.recognized.map(t=>t.tile),['5m','3m','4m']);
  }
  for(const classifier of [model(undefined,'vit'),model(undefined,'hybrid',false)]) {
    await recognizeConfiguredPublicTilesWithVit(source,layout,classifier);assert.deepEqual(classifier.calls,[3]);
  }
  const strict=await recognizeConfiguredPublicTilesWithVit(source,layout,model(),{minimumConfidence:.9999});
  assert.equal(toPublicTileObservation(strict).opponentDiscards[0]!.meldsObserved,false);
});
test('red numeral evidence excludes the red suit glyph on ordinary three/five man',async()=>{
  const red=await sharp(source).extract({left:7,top:17,width:63,height:22}).rotate(90).png().toBuffer();
  assert.ok(await normalizeRedManNumeral(red));
  const three=await sharp(source).extract({left:14,top:45,width:64,height:26}).rotate(90).png().toBuffer();
  assert.equal(await normalizeRedManNumeral(three),undefined);
  const five=await sharp(control).extract({left:20,top:17,width:54,height:34}).rotate(180).png().toBuffer();
  assert.equal(await normalizeRedManNumeral(five),undefined);
});

test('red pon confirmation batches one family and does not refine other regions',async()=>{
  const layout=await fixtureLayout();
  function ponModel(){const calls:number[]=[];return {backend:'hybrid' as const,calls,async classifyTileImages(images:Buffer[]){calls.push(images.length);return calls.length===1
    ?[prediction('5m',.992),prediction('5m',.379),prediction('5m',.879)]:[prediction('5m',.99,'3m',.008)];}};}
  const classifier=ponModel();const result=await recognizeConfiguredPublicTilesWithVit(control,layout,classifier);
  assert.deepEqual(classifier.calls,[3,1]);assert.equal(result.rightMelds!.recognized[1]!.tile,'0m');
  assert.equal(toPublicTileObservation(result).opponentDiscards[0]!.meldsObserved,true);
  const other=ponModel();await recognizeConfiguredPublicTilesWithVit(control,{...layout,publicTileRegions:{leftMelds:layout.publicTileRegions.rightMelds}},other);
  assert.deepEqual(other.calls,[3]);
});
