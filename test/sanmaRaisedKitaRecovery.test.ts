import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {readFile} from 'node:fs/promises';
import sharp from 'sharp';
import {recoverSanmaRaisedClosedHand} from '../src/recognition/sanmaRaisedClosedHandRecovery.js';
import {inspectSanmaFrame} from '../src/recognition/sanmaFrameExperiment.js';
import {EXPERIMENTAL_BUTTONS, type ExperimentalTemplates} from '../src/recognition/sanmaButtonExperiment.js';
import type {ScreenLayout} from '../src/recognition/layout.js';

const root='/home/yama1/.codex/sanma-run-d0ff500-20261031';
test('raised south with north prompt recovers only untrusted physical candidates', {skip:!existsSync(`${root}/manual-01-before.png`)}, async()=>{
 const layout=JSON.parse(await readFile('config/layout-runtime.json','utf8')) as ScreenLayout;
 const frame=await readFile(`${root}/manual-01-before.png`);
 const recovered=await recoverSanmaRaisedClosedHand(frame,layout);
 assert.ok(recovered);assert.equal(recovered.handSlots[9]?.y,873);assert.equal(recovered.confidence,0);
 assert.equal(recovered.evidence.detectedTiles,-1);
 const buttonTemplates=Object.fromEntries(await Promise.all(EXPERIMENTAL_BUTTONS.map(async n=>[n,await readFile(`test/fixtures/sanma-buttons/${n}.png`)]))) as ExperimentalTemplates;
 const report=await inspectSanmaFrame({frame,layout,templates:'templates/bootstrap',buttonTemplates,publicClassifier:{async classifyTileImages(){throw new Error('unavailable')}}});
 assert.equal(report.hand.status,'candidate');if(report.hand.status==='candidate'){
  assert.equal(report.hand.value.tiles.filter(x=>x==='N').length,2);assert.equal(report.hand.value.safe,false);
  assert.equal(report.hand.value.turnReady,false);
 }
 assert.equal(report.operationAuthorized,false);
 const other=await readFile(`${root}/manual-02-before.png`);assert.equal(await recoverSanmaRaisedClosedHand(other,layout),undefined);
 const band=await sharp(frame).extract({left:1076,top:879,width:92,height:26}).png().toBuffer();
 const twice=await sharp(frame).composite([{input:band,left:1266,top:879}]).png().toBuffer();
 assert.equal(await recoverSanmaRaisedClosedHand(twice,layout),undefined);
});
