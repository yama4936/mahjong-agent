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
