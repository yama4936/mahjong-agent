import test from "node:test";
import assert from "node:assert/strict";
import {advanceSanmaFrameTimeline} from "../src/recognition/sanmaFrameTimeline.js";

type Observation = Parameters<typeof advanceSanmaFrameTimeline>[2];
function fake(digest: string, round: string | undefined, northMatch: boolean, hand: string[] = ["1m"]) {
  return {digest, board:{verified:false, ...(round ? {candidate:{seat:"east",round,honba:0}} : {})},
    north:{status:"unknown",complete:false,verified:false,positions:{
      own:{verified:false,complete:false,matches:northMatch?[{x:1395,y:775}]:[]},
      left:{verified:false,complete:false,candidate:null},opposite:{verified:false,complete:false,candidate:null}}},
    report:{digest,hand:{status:"candidate",value:{tiles:hand}},publicTiles:{status:"candidate",value:{observation:{ownDiscards:[],opponentDiscards:[]}}}}} as unknown as Observation;
}

test("timeline keeps untrusted frame evidence and treats disappearance as unknown", () => {
  const first = advanceSanmaFrameTimeline(undefined,1,fake("a","east_1",true));
  const second = advanceSanmaFrameTimeline(first,2,fake("b","east_1",false));
  assert.equal(second.relationship,"unproven_equal_board");
  assert.equal(second.comparison.north.own,"unknown");
  assert.equal(second.comparison.rivers,"unknown");
  assert.equal(second.comparison.hand,"same_candidates");
  assert.equal(second.latest.observation.north.positions?.own.matches instanceof Array,true);
  assert.deepEqual(second.latest.observation.north.positions?.own.matches,[]);
  assert.equal(second.operationAuthorized,false);
});

test("round differences, incomplete OCR, duplicate and reverse order withhold comparisons", () => {
  const first = advanceSanmaFrameTimeline(undefined,5,fake("a","east_1",true));
  for (const [index, observation, expected] of [
    [6,fake("b","east_2",true),"possible_hand_boundary"],
    [6,fake("b",undefined,true),"board_unknown"],
    [6,fake("a","east_1",true),"duplicate_frame"],
    [4,fake("b","east_1",true),"invalid_frame_order"],
    [6,{...fake("b","east_1",true), report:{...fake("b","east_1",true).report,digest:"wrong"}},"inconsistent_frame"],
  ] as const) {
    const next = advanceSanmaFrameTimeline(first,index,observation);
    assert.equal(next.relationship,expected);
    assert.equal(next.comparison.north.own,"unknown");
    assert.equal(next.comparison.hand,"unknown");
    assert.equal(next.status,"unknown");
    if (expected === "duplicate_frame" || expected === "invalid_frame_order" || expected === "inconsistent_frame") {
      assert.equal(next.latest.index,5);
      assert.equal(next.rejected?.index,index);
    }
  }
});

import { existsSync } from "node:fs";
import { readFile, readdir } from "node:fs/promises";
import sharp from "sharp";
import { observeSanmaFrameTimeline } from "../src/recognition/sanmaFrameTimeline.js";
import { layoutSchema } from "../src/recognition/layout.js";
import { HybridTileRecognizer } from "../src/recognition/hybridTileRecognizer.js";
import { EXPERIMENTAL_BUTTONS, type ExperimentalTemplates } from "../src/recognition/sanmaButtonExperiment.js";
const folder = "artifacts/sanma-manual-e48c562-20261031/continuous";
const available = existsSync(folder) && existsSync(".runtime/python-auto-venv/bin/python") &&
  existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar") && existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt") &&
  existsSync("templates/bootstrap/1m__hf_base.png");

test("timeline preserves two actual frames across own-north occlusion", {skip:!available}, async () => {
  const files = await readdir(folder);
  const source = async (index:number) => {
    const prefix = `frame-${String(index).padStart(6,"0")}-`;
    const name = files.find(file=>file.startsWith(prefix));
    assert.ok(name);
    return readFile(`${folder}/${name}`);
  };
  const layout = layoutSchema.parse(JSON.parse(await readFile("config/layout-runtime.json","utf8")));
  const buttonTemplates = Object.fromEntries(await Promise.all(EXPERIMENTAL_BUTTONS.map(async name =>
    [name, await readFile(`test/fixtures/sanma-buttons/${name}.png`)]))) as ExperimentalTemplates;
  const skip = await sharp(await readFile("test/fixtures/sanma-button-rows/kita.png")).extract({left:580,top:0,width:245,height:90}).png().toBuffer();
  const buttonRowReferences = {skip,emptyRow:await readFile("test/fixtures/sanma-button-rows/empty.png")};
  const model = new HybridTileRecognizer();
  try {
    const state = await observeSanmaFrameTimeline({frames:[{index:1003,frame:await source(1003)},{index:1004,frame:await source(1004)}],
      layout,templates:"templates/bootstrap",buttonTemplates,buttonRowReferences,publicClassifier:model});
    assert.ok(state?.previous);
    assert.equal(state.latest.index,1004);
    assert.equal(state.previous.index,1003);
    assert.notEqual(state.latest.observation.digest,state.previous.observation.digest);
    assert.equal(state.operationAuthorized,false);
    assert.equal(state.latest.observation.north.complete,false);
    assert.equal(state.previous.observation.north.complete,false);
    assert.equal(state.comparison.rivers,"unknown");
    assert.equal(state.comparison.north.own,"unknown");
  } finally { await model.close(); }
});
