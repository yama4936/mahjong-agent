import test from "node:test";
import assert from "node:assert/strict";
import {existsSync} from "node:fs";
import {readFile} from "node:fs/promises";
import sharp from "sharp";
import {layoutSchema} from "../src/recognition/layout.js";
import {inspectSanmaFrame} from "../src/recognition/sanmaFrameExperiment.js";
import {deriveSanmaActionCandidates} from "../src/recognition/sanmaAutoFrameObservation.js";
import {HybridTileRecognizer} from "../src/recognition/hybridTileRecognizer.js";
import {EXPERIMENTAL_BUTTONS,type ExperimentalTemplates} from "../src/recognition/sanmaButtonExperiment.js";
const base="artifacts/sanma-manual-e48c562-20261031/actions";
const file=`${base}/2026-10-30T16-21-44-430Z-before.png`;
const available=existsSync(file) && existsSync("templates/bootstrap/1m__hf_base.png") &&
  existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar") && existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt");

test("real kita button remains a hypothesis when cropped hand misses north",{skip:!available,timeout:30000},async()=>{
  const frame=await readFile(file),layout=layoutSchema.parse(JSON.parse(await readFile("config/layout-runtime.json","utf8")));
  const buttonTemplates=Object.fromEntries(await Promise.all(EXPERIMENTAL_BUTTONS.map(async n=>[n,await readFile(`test/fixtures/sanma-buttons/${n}.png`)]))) as ExperimentalTemplates;
  const row=await readFile("test/fixtures/sanma-button-rows/kita.png"),buttonRowReferences={skip:await sharp(row).extract({left:580,top:0,width:245,height:90}).png().toBuffer(),emptyRow:await readFile("test/fixtures/sanma-button-rows/empty.png")};
  const model=new HybridTileRecognizer();
  try{
    const report=await inspectSanmaFrame({frame,layout,templates:"templates/bootstrap",buttonTemplates,buttonRowReferences,publicClassifier:model,ownSeat:"south"});
    assert.equal(report.hand.status,"candidate");
    if(report.hand.status!=="candidate") return;
    assert.equal(report.hand.value.safe,false);
    assert.ok(report.hand.value.tiles.length<14);
    assert.equal(report.hand.value.tiles.includes("N"),false);
    const result=deriveSanmaActionCandidates(report,true);
    assert.deepEqual(result.candidates,[{action:"kita",slot:1,handSupport:"unknown"}]);
    assert.equal(result.status,"hypotheses");
    assert.equal(result.operationAuthorized,false);
    assert.equal(report.operationAuthorized,false);
    const noSeat=deriveSanmaActionCandidates(report,false);
    assert.equal(noSeat.status,"unresolved");assert.deepEqual(noSeat.candidates,[]);
  }finally{await model.close()}
});
