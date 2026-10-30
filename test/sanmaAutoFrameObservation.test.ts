import test from "node:test";
import assert from "node:assert/strict";
import {existsSync} from "node:fs";
import {readFile} from "node:fs/promises";
import {createHash} from "node:crypto";
import sharp from "sharp";
import {layoutSchema} from "../src/recognition/layout.js";
import {HybridTileRecognizer} from "../src/recognition/hybridTileRecognizer.js";
import {EXPERIMENTAL_BUTTONS, type ExperimentalTemplates} from "../src/recognition/sanmaButtonExperiment.js";
import {observeSanmaFrameAutomatically} from "../src/recognition/sanmaAutoFrameObservation.js";

const file = "artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-05-55-331Z-before.png";
const available = existsSync(file) && existsSync(".runtime/python-auto-venv/bin/python") &&
  existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar") && existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt") &&
  existsSync("templates/bootstrap/1m__hf_base.png");

test("automatic same-frame board, hand, public and UI candidates remain unverified", {skip:!available}, async () => {
  const layout = layoutSchema.parse(JSON.parse(await readFile("config/layout-runtime.json", "utf8")));
  const buttonTemplates = Object.fromEntries(await Promise.all(EXPERIMENTAL_BUTTONS.map(async name =>
    [name, await readFile(`test/fixtures/sanma-buttons/${name}.png`)]))) as ExperimentalTemplates;
  const skipRow = await readFile("test/fixtures/sanma-button-rows/kita.png");
  const buttonRowReferences = {skip:await sharp(skipRow).extract({left:580,top:0,width:245,height:90}).png().toBuffer(),
    emptyRow:await readFile("test/fixtures/sanma-button-rows/empty.png")};
  const model = new HybridTileRecognizer();
  try {
    const frame = await readFile(file);
    const result = await observeSanmaFrameAutomatically({frame,layout,buttonTemplates,buttonRowReferences,
      templates:"templates/bootstrap",publicClassifier:model});
    assert.equal(result.digest, createHash("sha256").update(frame).digest("hex"));
    assert.equal(result.report.digest,result.digest);
    assert.equal(result.board.verified,false);
    assert.equal(result.board.reason,"expected_total_points_unknown");
    assert.deepEqual(result.ownSeat,{status:"candidate",value:"west",verified:false});
    assert.equal(result.report.publicTiles.status,"candidate");
    if(result.report.publicTiles.status === "candidate") assert.deepEqual(result.report.publicTiles.value.observation.opponentDiscards.map(o=>o.seat),["east","south"]);
    assert.equal(result.report.hand.status,"candidate");
    assert.equal(result.report.buttonRow.status,"candidate");
    if(result.report.buttonRow.status === "candidate") assert.deepEqual(result.report.buttonRow.value.slots.flatMap(s=>s.status==="candidate"?[s.action]:[]),["kita","skip"]);
    assert.equal(result.report.ownMelds.status,"candidate");
    if(result.report.ownMelds.status === "candidate") assert.equal(result.report.ownMelds.value.reason,"hand_extent_unknown");
    assert.equal(result.report.decision.status,"blocked");
    assert.equal(result.operationAuthorized,false);
    // The same black 1920x1080 image has no identifiable board or seat;
    // mapping is withheld, not silently assigned East.
    const blank = await sharp({create:{width:1920,height:1080,channels:3,background:"black"}}).png().toBuffer();
    const negative = await observeSanmaFrameAutomatically({frame:blank,layout,buttonTemplates,buttonRowReferences,
      templates:"templates/bootstrap",publicClassifier:model});
    assert.equal(negative.ownSeat.status,"unknown");
    assert.equal(negative.report.publicTiles.status,"unresolved");
    assert.equal(negative.operationAuthorized,false);
    const four = await readFile("test/fixtures/board-cache-score-25400-20261020.jpg");
    const fourResult = await observeSanmaFrameAutomatically({frame:four,layout,buttonTemplates,buttonRowReferences,
      templates:"templates/bootstrap",publicClassifier:model});
    assert.equal(fourResult.board.reason,"unexpected_right_score");
    assert.equal(fourResult.ownSeat.status,"unknown");
    assert.equal(fourResult.report.publicTiles.status,"unresolved");
    assert.equal(fourResult.operationAuthorized,false);
  } finally { await model.close(); }
});
