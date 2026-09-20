import assert from "node:assert/strict";
import test from "node:test";
import sharp from "sharp";
import { HandConsensus, combineTileEvidence } from "../src/recognition/consensus.js";
import { normalizeTileFace } from "../src/recognition/normalizeTileFace.js";
import { classifyTile, loadTemplates } from "../src/recognition/templateMatcher.js";
import type { GameTile } from "../src/game/tiles.js";
import { mkdtemp, readdir, copyFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { validateTemplateDirectory } from "../src/recognition/templateValidator.js";

test("validation detects exact training/holdout leakage and records matcher identity", async () => {
  const directory = await mkdtemp(path.join(tmpdir(), "jantama-leakage-"));
  const files = (await readdir("templates/bootstrap")).filter(f => f.includes("__hf_base") && f.endsWith(".png"));
  for (const file of files) await copyFile(path.join("templates/bootstrap", file), path.join(directory, file));
  await copyFile(path.join("templates/bootstrap", "1m__hf_base.png"), path.join(directory, "1m__holdout.png"));
  const report = await validateTemplateDirectory(directory, { tileMatcher: "face" });
  assert.equal(report.trainHoldoutCollisions.length, 1);
  assert.equal(report.passesAutoCalibration, false);
  assert.equal(report.tileMatcher, "face");
  assert.equal(report.matcherVersion, "2");
});

test("blank screenshots do not become certain white dragons", async () => {
  const templates = await loadTemplates("templates/bootstrap", f => f.includes("__hf_base"));
  for (const background of ["white", "black", "#cccccc"]) {
    const image = await sharp({ create: { width: 44, height: 64, channels: 3, background } }).png().toBuffer();
    const match = await classifyTile(image, templates, { rejectBlank: true });
    assert.equal(match.confidence, 0);
  }
});

test("face normalization removes dark margins without cropping the bright face", async () => {
  const face = await sharp({ create: { width: 40, height: 60, channels: 3, background: "#eeeeee" } }).png().toBuffer();
  const image = await sharp({ create: { width: 70, height: 90, channels: 3, background: "#102020" } }).composite([{ input: face, left: 15, top: 10 }]).png().toBuffer();
  const meta = await sharp(await normalizeTileFace(image)).metadata();
  assert.equal(meta.width, 40); assert.equal(meta.height, 60);
});

test("consensus rejects duplicates, changing hands, invalid counts and round changes", () => {
  const gate = new HandConsensus();
  const tiles: GameTile[] = ["1m","2m","3m","4m","5m","6m","3p","4p","5p","7s","8s","9s","E","E"];
  const frame = { roundId: "match1-east1", capturedAt: 1, tiles, accepted: true };
  assert.equal(gate.observe(frame), false);
  assert.equal(gate.observe(frame), false);
  assert.equal(gate.observe({ ...frame, capturedAt: 2 }), false);
  assert.equal(gate.observe({ ...frame, capturedAt: 3 }), false);
  assert.equal(gate.observe({ ...frame, capturedAt: 4 }), true);
  assert.equal(gate.observe({ ...frame, capturedAt: 5, roundId: "match1-east2" }), false);
  assert.equal(gate.observe({ ...frame, capturedAt: 6, tiles: Array(14).fill("E") }), false);
});

test("34-class model agreement cannot certify a red or ordinary five", () => {
  const template = { tile: "0s" as const, confidence: 0.999, runnerUpConfidence: 0.1 };
  const model = { tile: "5s" as const, confidence: 0.999, runnerUpTile: "6s" as const, runnerUpConfidence: 0.001 };
  assert.equal(combineTileEvidence(template, model).accepted, false);
  assert.equal(combineTileEvidence(template, model, true).accepted, true);
  assert.equal(combineTileEvidence({ ...template, tile: "5s" }, model).accepted, false);
});
