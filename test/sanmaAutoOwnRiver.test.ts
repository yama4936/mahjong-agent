import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import sharp from 'sharp';
import {layoutSchema} from '../src/recognition/layout.js';
import {EXPERIMENTAL_BUTTONS, type ExperimentalTemplates} from '../src/recognition/sanmaButtonExperiment.js';
import {observeSanmaFrameAutomatically} from '../src/recognition/sanmaAutoFrameObservation.js';

const layout = layoutSchema.parse(JSON.parse(await readFile('config/layout-runtime.json','utf8')));
const buttonTemplates = Object.fromEntries(await Promise.all(EXPERIMENTAL_BUTTONS.map(async n=>[n,await readFile(`test/fixtures/sanma-buttons/${n}.png`)]))) as ExperimentalTemplates;
const crop = await readFile('test/fixtures/sanma-own-river-portable/after.png');
const frame = await sharp({create:{width:1920,height:1080,channels:3,background:'black'}}).composite([{input:crop,left:750,top:535}]).png().toBuffer();
const digest = createHash('sha256').update(frame).digest('hex');
const classifier = {async classifyTileImages(images:Buffer[]) {return images.map(()=>({tile:'8p' as const,confidence:.99,runnerUpTile:'2s' as const,runnerUpConfidence:.001}));}};
const boardObserver = {async observe() {return {frame_sha256:digest,board:{verified:false,reason:'unsupported_opposite_right_layout'},north:{status:'unknown',verified:false,complete:false}};}};
test('own river is available as an unverified image candidate when wind mapping is unknown',async()=>{
 const result=await observeSanmaFrameAutomatically({frame,layout,buttonTemplates,publicClassifier:classifier,templates:'templates/bootstrap',boardObserver});
 assert.equal(result.ownSeat.status,'unknown');
 assert.equal(result.report.publicTiles.status,'unresolved');
 assert.ok('ownRiver' in result);
 assert.equal(result.ownRiver.frameSha256,digest);
 assert.deepEqual(result.ownRiver?.candidates.map(c=>c.tile),['8p']);
 assert.equal(result.ownRiver?.verified,false);
 assert.equal(result.ownRiver?.complete,false);
 assert.equal(result.ownRiver?.operationAuthorized,false);
 assert.equal(result.operationAuthorized,false);
});
test('failed own-river classifier is not reported as an empty river',async()=>{
 const broken={async classifyTileImages():Promise<never>{throw new Error('unavailable')}};
 const result=await observeSanmaFrameAutomatically({frame,layout,buttonTemplates,publicClassifier:broken,templates:'templates/bootstrap',boardObserver});
 assert.equal('ownRiver' in result,false);
 assert.ok('ownRiverError' in result);
 assert.equal(result.ownRiverError,'unavailable');
 assert.equal(result.operationAuthorized,false);
});

test('score-total uncertainty does not suppress the physical own-river candidate',async()=>{
 const region=await readFile('test/fixtures/sanma-own-river-121/own-river.png');
 const image=await sharp({create:{width:1920,height:1080,channels:3,background:'black'}})
  .composite([{input:region,left:750,top:535}]).png().toBuffer();
 const imageDigest=createHash('sha256').update(image).digest('hex');
 const uncertainBoard={async observe(){return {frame_sha256:imageDigest,
  board:{verified:false,reason:'expected_total_points_unknown',candidate:{seat:'west'}},
  north:{status:'unknown',verified:false,complete:false}};}};
 const nine={async classifyTileImages(images:Buffer[]){return images.map(()=>({tile:'9m' as const,confidence:.924,runnerUpTile:'1m' as const,runnerUpConfidence:.02}));}};
 const result=await observeSanmaFrameAutomatically({frame:image,layout,buttonTemplates,publicClassifier:nine,templates:'templates/bootstrap',boardObserver:uncertainBoard});
 assert.equal(result.board.reason,'expected_total_points_unknown');
 assert.ok('ownRiver' in result);
 assert.equal(result.ownRiver?.frameSha256,imageDigest);
 assert.deepEqual(result.ownRiver?.candidates.map(c=>c.tile),['9m']);
 assert.deepEqual(result.ownRiver?.candidates.map(c=>[c.x,c.y]),[[769,545]]);
 assert.equal(result.ownRiver?.status,'unknown');
 assert.equal(result.ownRiver?.verified,false);
 assert.equal(result.ownRiver?.complete,false);
 assert.equal(result.ownRiver?.operationAuthorized,false);
 assert.equal(result.operationAuthorized,false);
 const broken={async classifyTileImages():Promise<never>{throw new Error('classifier unavailable')}};
 const failed=await observeSanmaFrameAutomatically({frame:image,layout,buttonTemplates,publicClassifier:broken,templates:'templates/bootstrap',boardObserver:uncertainBoard});
 assert.equal('ownRiver' in failed,false);
 assert.ok('ownRiverError' in failed);
 assert.equal(failed.ownRiverError,'classifier unavailable');
 assert.equal(failed.operationAuthorized,false);
});

test('all three physical river branches share one inference queue',async()=>{
 let active=0, maxActive=0, calls=0;
 const singleWorker={async classifyTileImages(images:Buffer[]){
  calls++; maxActive=Math.max(maxActive,++active);
  await new Promise(resolve=>setTimeout(resolve,5));
  active--;
  return images.map(()=>({tile:'8p' as const,confidence:.99,runnerUpTile:'2s' as const,runnerUpConfidence:.001}));
 }};
 const board={async observe(){return {frame_sha256:digest,board:{verified:false,
  reason:'unsupported_right_opponent_layout',layoutCandidate:{verified:false,opponents:['left','right']}},
  north:{status:'unknown',verified:false,complete:false}};}};
 const result=await observeSanmaFrameAutomatically({frame,layout,buttonTemplates,publicClassifier:singleWorker,templates:'templates/bootstrap',boardObserver:board});
 assert.ok(calls>0);
 assert.equal(maxActive,1);
 assert.ok('ownRiver' in result);
 assert.equal(result.ownRiver.frameSha256,digest);
 assert.equal(result.leftRiver?.frameSha256,digest);
 assert.equal(result.rightRiver?.frameSha256,digest);
 for(const river of [result.ownRiver,result.leftRiver,result.rightRiver]) {
  assert.equal(river?.verified,false);assert.equal(river?.complete,false);assert.equal(river?.operationAuthorized,false);
 }
});

test('river worker errors remain missing, not empty or authorized',async()=>{
 let active=0, maxActive=0;
 const broken={async classifyTileImages():Promise<never>{
  maxActive=Math.max(maxActive,++active); await new Promise(resolve=>setTimeout(resolve,5)); active--;
  throw new Error('worker failed');
 }};
 const board={async observe(){return {frame_sha256:digest,board:{verified:false,
  reason:'unsupported_right_opponent_layout',layoutCandidate:{verified:false,opponents:['left','right']}},
  north:{status:'unknown',verified:false,complete:false}};}};
 const result=await observeSanmaFrameAutomatically({frame,layout,buttonTemplates,publicClassifier:broken,templates:'templates/bootstrap',boardObserver:board});
 assert.equal(maxActive,1);
 assert.equal('ownRiver' in result,false);
 assert.ok('ownRiverError' in result);
 assert.equal(result.ownRiverError,'worker failed');
 assert.equal(result.operationAuthorized,false);
});

test('failed frame drains pending board and river work before rejection',async()=>{
 const bad=await sharp({create:{width:1921,height:1080,channels:3,background:'black'}})
  .composite([{input:crop,left:750,top:535}]).png().toBuffer();
 const hash=createHash('sha256').update(bad).digest('hex');
 let boardFinished=false, active=0, calls=0, maxActive=0;
 const delayedBoard={async observe(){await new Promise(resolve=>setTimeout(resolve,30));boardFinished=true;
  return {frame_sha256:hash,board:{verified:false,reason:'expected_total_points_unknown'},
   north:{status:'unknown',verified:false,complete:false}};}};
 const slowClassifier={async classifyTileImages(images:Buffer[]){calls++;active++;maxActive=Math.max(maxActive,active);
  await new Promise(resolve=>setTimeout(resolve,20));active--;
  return images.map(()=>({tile:'8p' as const,confidence:.99,runnerUpTile:'2s' as const,runnerUpConfidence:.001}));}};
 await assert.rejects(observeSanmaFrameAutomatically({frame:bad,layout,buttonTemplates,publicClassifier:slowClassifier,
  templates:'templates/bootstrap',boardObserver:delayedBoard}),/Unreviewed frame dimensions/);
 assert.equal(boardFinished,true); assert.equal(calls,0); assert.equal(active,0);
 const valid=await observeSanmaFrameAutomatically({frame,layout,buttonTemplates,publicClassifier:slowClassifier,
  templates:'templates/bootstrap',boardObserver});
 assert.equal(valid.digest,digest); assert.ok(calls>0); assert.equal(active,0); assert.equal(maxActive,1);
});
