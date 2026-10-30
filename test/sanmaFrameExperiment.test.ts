import test from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import sharp from "sharp";
import { inspectSanmaFrame } from "../src/recognition/sanmaFrameExperiment.js";
import { EXPERIMENTAL_BUTTONS, type ExperimentalTemplates } from "../src/recognition/sanmaButtonExperiment.js";
import { HybridTileRecognizer } from "../src/recognition/hybridTileRecognizer.js";
import { layoutSchema } from "../src/recognition/layout.js";

const file = "artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-05-55-331Z-before.png";
const available = existsSync(file) && existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar")
  && existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt") && existsSync("templates/bootstrap/1m__hf_base.png");

test("one saved sanma frame is bound to untrusted hand, public and button observations", { skip: !available }, async () => {
  const frame = await readFile(file);
  const layout = layoutSchema.parse(JSON.parse(await readFile("config/layout-runtime.json", "utf8")));
  const buttonTemplates = Object.fromEntries(await Promise.all(EXPERIMENTAL_BUTTONS.map(async name =>
    [name, await readFile(`test/fixtures/sanma-buttons/${name}.png`)]))) as ExperimentalTemplates;
  const classifier = new HybridTileRecognizer();
  try {
    const report = await inspectSanmaFrame({frame, layout, templates:"templates/bootstrap", buttonTemplates,
      ownSeat:"west", publicClassifier:classifier});
    assert.equal(report.digest, createHash("sha256").update(frame).digest("hex"));
    assert.equal(report.hand.status, "candidate");
    if (report.hand.status === "candidate") assert.deepEqual(report.hand.value.tiles,
      ["1m","9m","9m","4p","0p","5p","6p","8p","2s","6s","S","S","N","E"]);
    assert.equal(report.button.status, "candidate");
    if (report.button.status === "candidate") assert.deepEqual([report.button.value.status, report.button.value.status === "matched" && report.button.value.action], ["matched", "kita"]);
    assert.equal(report.publicTiles.status, "candidate");
    if (report.publicTiles.status === "candidate") assert.deepEqual(report.publicTiles.value.observation.opponentDiscards.map(o => o.seat), ["east", "south"]);
    assert.equal(report.decision.status, "blocked");
    assert.equal(report.operationAuthorized, false);
  } finally { await classifier.close(); }
});

test("unsupported frame size is rejected before any recognition", async () => {
  const frame = await sharp({create: {width:20, height:20, channels:3, background:"black"}}).png().toBuffer();
  await assert.rejects(inspectSanmaFrame({frame} as never), /dimensions/);
});
