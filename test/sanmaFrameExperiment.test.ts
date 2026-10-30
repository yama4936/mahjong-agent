import test from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import sharp from "sharp";
import { bindSanmaDiscardHypothesis, inspectSanmaFrame } from "../src/recognition/sanmaFrameExperiment.js";
import { EXPERIMENTAL_BUTTONS, type ExperimentalTemplates } from "../src/recognition/sanmaButtonExperiment.js";
import { HybridTileRecognizer } from "../src/recognition/hybridTileRecognizer.js";
import { evaluateSanmaFrameCandidate } from "../src/recognition/sanmaFrameEvaluation.js";
import { evaluateDiscards } from "../src/game/ukeire.js";
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
    const evaluation = evaluateSanmaFrameCandidate({frame, report});
    assert.equal(evaluation.status, "blocked");
    if (evaluation.status === "blocked") {
      assert.ok(evaluation.reasons.includes("complete independent review missing"));
      assert.ok(evaluation.reasons.includes("hand recognition unconfirmed"));
      assert.ok(evaluation.reasons.includes("visible kita button needs separate handling"));
    }
    const bound = bindSanmaDiscardHypothesis(report, frame, 0);
    assert.equal(bound.status, "blocked");
    assert.equal(bound.operationAuthorized, false);
    assert.ok(bound.blockers.includes("hand recognition did not meet confidence requirements"));
    assert.ok(bound.blockers.includes("button kita is only a single unverified crop"));
    assert.ok(bound.blockers.includes("public tiles incomplete"));
    if (report.hand.status === "candidate") {
      const rows = evaluateDiscards(report.hand.value.tiles, [], 0, "sanma");
      const index = rows.findIndex(row => row.tile === "9m");
      const hypothetical = bindSanmaDiscardHypothesis({ ...report, shape: {status: "hypothesis", assumptions: ["synthetic test"], rows} }, frame, index);
      assert.equal(hypothetical.operationAuthorized, false);
      assert.deepEqual(hypothetical.hypothesis?.positions.map(position => position.index), [1, 2]);
      assert.ok(hypothetical.blockers.includes("hand recognition did not meet confidence requirements"));
    }
    const otherFrame = Buffer.from(frame);
    otherFrame[0] = otherFrame[0]! ^ 1;
    const mismatch = bindSanmaDiscardHypothesis(report, otherFrame, 0);
    assert.ok(mismatch.blockers.includes("frame digest differs from observation"));
    assert.equal("hypothesis" in mismatch, false);
    const unknownButton = bindSanmaDiscardHypothesis({ ...report, button: { status: "unresolved", reason: "test" } }, frame, 0);
    assert.ok(unknownButton.blockers.includes("button crop unrecognized"));

  } finally { await classifier.close(); }
});

test("unsupported frame size is rejected before any recognition", async () => {
  const frame = await sharp({create: {width:20, height:20, channels:3, background:"black"}}).png().toBuffer();
  await assert.rejects(inspectSanmaFrame({frame} as never), /dimensions/);
});
