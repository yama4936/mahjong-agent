import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {readFile} from 'node:fs/promises';
import {layoutSchema} from '../src/recognition/layout.js';
import {proposeLiveHandLayout} from '../src/recognition/handLayoutProposal.js';
import {recoverSanmaRaisedDrawAfterTwoCalls} from '../src/recognition/sanmaRaisedDrawRecovery.js';
import {recognizeTileSlots} from '../src/recognition/templateMatcher.js';
import {inspectSanmaFrame} from '../src/recognition/sanmaFrameExperiment.js';
import {EXPERIMENTAL_BUTTONS,type ExperimentalTemplates} from '../src/recognition/sanmaButtonExperiment.js';
import sharp from 'sharp';
const base='artifacts/sanma-manual-e48c562-20261031/actions';
const files=['2026-10-30T16-28-27-220Z-before.png','2026-10-30T16-30-00-848Z-before.png'];
const available=files.every(f=>existsSync(`${base}/${f}`)) && existsSync('templates/bootstrap/1m__hf_base.png');
test('two saved raised draws after two calls yield only unverified eight-tile candidates',{skip:!available,timeout:60000},async()=>{
  const layout=layoutSchema.parse(JSON.parse(await readFile('config/layout-runtime.json','utf8')));
  for (const file of files) {
    const frame=await readFile(`${base}/${file}`), rejected=await proposeLiveHandLayout(frame);
    assert.equal(rejected.evidence.detectedTiles,2);
    const p=await recoverSanmaRaisedDrawAfterTwoCalls(frame,layout,rejected);
    assert.ok(p);assert.equal(p.handSlots.length,7);assert.equal(p.drawSlot.x,917);assert.equal(p.drawSlot.y,873);
    assert.equal(p.confidence,0);assert.equal(p.requiresHoldoutValidation,true);
    const result=await recognizeTileSlots(frame,[...p.handSlots,p.drawSlot],{...layout,...p},'templates/bootstrap');
    assert.deepEqual(result.tiles,['1p','1p','2p','8p','5s','8s','9s',file === files[0] ? '1m' : 'E']);
    assert.equal(result.safe,false);
  }
  const eleven=await readFile(`${base}/2026-10-30T16-21-44-430Z-before.png`);
  assert.equal(await recoverSanmaRaisedDrawAfterTwoCalls(eleven,layout,await proposeLiveHandLayout(eleven)),undefined);
  const frame=await readFile(`${base}/${files[0]}`);
  const rejected=await proposeLiveHandLayout(frame);
  for (const name of ['2026-10-30T16-05-55-331Z-before.png']) {
    assert.equal(await recoverSanmaRaisedDrawAfterTwoCalls(await readFile(`${base}/${name}`),layout,rejected),undefined);
  }
  assert.equal(await recoverSanmaRaisedDrawAfterTwoCalls(await readFile('test/fixtures/hand-seven-sou-control-a-20261021.jpg'),layout,rejected),undefined);
  const raisedBand=await sharp(frame).extract({left:917,top:879,width:92,height:26}).png().toBuffer();
  const twice=await sharp(frame).composite([{input:raisedBand,left:602,top:879}]).png().toBuffer();
  assert.equal(await recoverSanmaRaisedDrawAfterTwoCalls(twice,layout,rejected),undefined);
  const buttonTemplates=Object.fromEntries(await Promise.all(EXPERIMENTAL_BUTTONS.map(async n=>[n,await readFile(`test/fixtures/sanma-buttons/${n}.png`)]))) as ExperimentalTemplates;
  const report=await inspectSanmaFrame({frame,layout,templates:'templates/bootstrap',buttonTemplates,ownSeat:'south',
    publicClassifier:{async classifyTileImages(){throw new Error('not available')}}});
  assert.equal(report.hand.status,'candidate');
  if(report.hand.status==='candidate') {assert.equal(report.hand.value.tiles.length,8);assert.equal(report.hand.value.safe,false);assert.equal(report.hand.value.turnReady,false);}
  assert.equal(report.operationAuthorized,false);
});
