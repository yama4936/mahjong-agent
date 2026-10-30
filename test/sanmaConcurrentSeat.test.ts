import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import sharp from "sharp";
import { layoutSchema } from "../src/recognition/layout.js";
import { inspectSanmaFrame } from "../src/recognition/sanmaFrameExperiment.js";
import { HybridTileRecognizer } from "../src/recognition/hybridTileRecognizer.js";
import { EXPERIMENTAL_BUTTONS, type ExperimentalTemplates } from "../src/recognition/sanmaButtonExperiment.js";
const file = "artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-05-55-331Z-before.png";
const available = existsSync(file) && existsSync("templates/bootstrap/1m__hf_base.png") &&
  existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar") && existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt");

test("delayed or failed seat does not alter the same-frame branches or authorize actions", {skip:!available,timeout:30_000}, async () => {
  const frame = await readFile(file), layout = layoutSchema.parse(JSON.parse(await readFile("config/layout-runtime.json", "utf8")));
  const buttonTemplates = Object.fromEntries(await Promise.all(EXPERIMENTAL_BUTTONS.map(async name =>
    [name, await readFile(`test/fixtures/sanma-buttons/${name}.png`)]))) as ExperimentalTemplates;
  const row = await readFile("test/fixtures/sanma-button-rows/kita.png");
  const buttonRowReferences = {skip:await sharp(row).extract({left:580,top:0,width:245,height:90}).png().toBuffer(),
    emptyRow:await readFile("test/fixtures/sanma-button-rows/empty.png")};
  const h = new HybridTileRecognizer();
  try {
    const common = {frame,layout,templates:"templates/bootstrap",buttonTemplates,buttonRowReferences,publicClassifier:h};
    const direct = await inspectSanmaFrame({...common,ownSeat:"west"});
    const delayed = await inspectSanmaFrame({...common,ownSeatPromise:Promise.resolve("west")});
    assert.deepEqual(delayed, direct);
    const failure = await inspectSanmaFrame({...common,ownSeatPromise:Promise.reject(new Error("seat unavailable"))});
    assert.equal(failure.publicTiles.status,"unresolved");
    if (failure.publicTiles.status === "unresolved") assert.match(failure.publicTiles.reason,/seat unavailable/);
    assert.deepEqual(failure.hand, direct.hand);
    assert.deepEqual(failure.buttonRow, direct.buttonRow);
    assert.equal(failure.operationAuthorized,false);
    assert.equal(failure.decision.status,"blocked");
  } finally { await h.close(); }
});
