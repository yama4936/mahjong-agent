import {test} from "node:test";
import assert from "node:assert/strict";
import {existsSync} from "node:fs";
import {readFile} from "node:fs/promises";
import sharp from "sharp";
import {layoutSchema} from "../src/recognition/layout.js";
import {proposeLiveHandLayout} from "../src/recognition/handLayoutProposal.js";
import {recoverSanmaRaisedHand} from "../src/recognition/sanmaRaisedHandRecovery.js";
const positive="artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-21-44-430Z-before.png";
const closed="artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-05-55-331Z-before.png";
const available=existsSync(positive) && existsSync(closed);

test("real false two-tile proposal recovers only an unverified raised compact candidate",{skip:!available},async()=>{
  const frame=await readFile(positive),layout=layoutSchema.parse(JSON.parse(await readFile("config/layout-runtime.json","utf8")));
  const original=await proposeLiveHandLayout(frame);
  assert.equal(original.evidence.detectedTiles,2);
  assert.ok(original.handSlots[0]!.y<900);
  const recovered=await recoverSanmaRaisedHand(frame,layout,original);
  assert.ok(recovered);
  assert.equal(recovered.evidence.detectedTiles,11);
  assert.equal(recovered.handSlots.length,10);
  assert.equal(recovered.handSlots[9]?.y,873);
  assert.equal(recovered.drawSlot.x,1201);
  assert.equal(recovered.confidence,0);
  assert.equal(recovered.requiresHoldoutValidation,true);
  const altered={...layout,handSlots:layout.handSlots.map((slot,index)=>index===3?{...slot,x:slot.x+1}:slot)};
  assert.equal(await recoverSanmaRaisedHand(frame,altered,original),undefined);
});

test("closed sanma, four-player, and two-raised-band images cannot produce this recovery",{skip:!available},async()=>{
  const frame=await readFile(positive),layout=layoutSchema.parse(JSON.parse(await readFile("config/layout-runtime.json","utf8")));
  const rejected=await proposeLiveHandLayout(frame);
  for(const file of [closed,"test/fixtures/hand-seven-sou-control-a-20261021.jpg"]) {
    assert.equal(await recoverSanmaRaisedHand(await readFile(file),layout,rejected),undefined);
  }
  const fakeRaisedBand=await sharp(frame).extract({left:1076,top:879,width:93,height:26}).png().toBuffer();
  const twice=await sharp(frame).composite([{input:fakeRaisedBand,left:981,top:879}]).png().toBuffer();
  assert.equal(await recoverSanmaRaisedHand(twice,layout,rejected),undefined);
});
