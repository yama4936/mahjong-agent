import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import sharp from "sharp";
import { EXPERIMENTAL_BUTTONS, type ExperimentalTemplates } from "../src/recognition/sanmaButtonExperiment.js";
import { inspectKitaReceiptExperiment } from "../src/recognition/sanmaKitaReceiptExperiment.js";
const archive = process.env.SANMA_ARCHIVE_ROOT;
const enabled = Boolean(archive && existsSync(archive));
const hash = (b:Buffer)=>createHash("sha256").update(b).digest("hex");
async function templates() {
 const refs=Object.fromEntries(await Promise.all(EXPERIMENTAL_BUTTONS.map(async n=>[n,await readFile(`test/fixtures/sanma-buttons/${n}.png`)]))) as ExperimentalTemplates;
 const kita=await readFile("test/fixtures/sanma-button-rows/kita.png");
 return {buttonTemplates:refs,skipTemplate:await sharp(kita).extract({left:580,top:0,width:245,height:90}).png().toBuffer(),emptyRow:await readFile("test/fixtures/sanma-button-rows/empty.png")};
}
async function scenario(name:string,beforeHand:string[],afterHand:string[],drawBefore:string,drawAfter:string,wall:number) {
 const beforeFrame=await readFile(`${archive}/actions/${name}-before.png`),afterFrame=await readFile(`${archive}/actions/${name}-after.png`);
 const before={frameSha256:hash(beforeFrame),atMs:1,roundId:"E",hand:beforeHand,drawn:drawBefore,meldCount:0,ownKitaCount:0,wallRemaining:wall};
 const after={...before,frameSha256:hash(afterFrame),atMs:3,hand:afterHand,drawn:drawAfter,ownKitaCount:1,wallRemaining:wall-1};
 return {beforeFrame,afterFrame,before,after,click:{action:"kita" as const,atMs:2,x:1010,y:825},maxBeforeClickMs:1,maxAfterClickMs:1,...await templates()};
}
test("archived north extraction stitches candidate button and manual state observations",{skip:!enabled},async()=>{
 const input=await scenario("2026-10-30T16-05-55-331Z",["1m","9m","9m","4p","0p","5p","6p","8p","2s","6s","S","S","N","E"],["1m","9m","9m","4p","0p","5p","6p","8p","2s","6s","E","S","S","4s"],"E","4s",52);
 const r=await inspectKitaReceiptExperiment(input);assert.equal(r.status,"consistent_candidate");assert.equal(r.operationAuthorized,false);
 const wrong=await inspectKitaReceiptExperiment({...input,after:{...input.after,ownKitaCount:0}});assert.equal(wrong.status,"unresolved");
 const stale=await inspectKitaReceiptExperiment({...input,before:{...input.before,frameSha256:"a".repeat(64)}});assert.equal(stale.status,"unresolved");
 const click=await inspectKitaReceiptExperiment({...input,click:{...input.click,x:500}});assert.equal(click.status,"unresolved");
 for (const invalid of [
   {...input, before:{...input.before,atMs:0}},
   {...input, after:{...input.after,atMs:4}},
   {...input, after:{...input.after,atMs:2}},
   {...input, maxBeforeClickMs:0},
   {...input, maxAfterClickMs:NaN},
   {...input, before:{...input.before,atMs:Number.MAX_SAFE_INTEGER + 1}},
 ]) {
   const result=await inspectKitaReceiptExperiment(invalid);
   assert.equal(result.status,"unresolved");
   assert.equal(result.operationAuthorized,false);
 }
});
test("north replacement keeps button visible and hand multiset unchanged",{skip:!enabled},async()=>{
 const hand=["2p","6p","7p","7p","8p","3s","6s","S","W","N","N","P","C","5p"];
 const input=await scenario("2026-10-30T16-42-54-581Z",hand,hand,"5p","N",53);
 const r=await inspectKitaReceiptExperiment(input);assert.equal(r.status,"consistent_candidate");assert.equal(r.operationAuthorized,false);
 const hidden=await sharp(input.beforeFrame).composite([{input:await sharp({create:{width:245,height:90,channels:3,background:"black"}}).png().toBuffer(),left:890,top:785}]).png().toBuffer();
 const obscured=await inspectKitaReceiptExperiment({...input,beforeFrame:hidden,before:{...input.before,frameSha256:hash(hidden)}});
 assert.equal(obscured.status,"unresolved");
});
