import assert from "node:assert/strict";
import test from "node:test";
import sharp from "sharp";
import { HandConsensus, combineTileEvidence } from "../src/recognition/consensus.js";
import { normalizeTileFace } from "../src/recognition/normalizeTileFace.js";
import { classifyTile, loadTemplates, matchTile, recognizeHand } from "../src/recognition/templateMatcher.js";
import type { GameTile } from "../src/game/tiles.js";
import { mkdtemp, readdir, copyFile, readFile } from "node:fs/promises";
import { layoutSchema } from "../src/recognition/layout.js";
import { tmpdir } from "node:os";
import path from "node:path";
import { validateTemplateDirectory } from "../src/recognition/templateValidator.js";
import { parseGameState } from "../src/game/state.js";
import { decide } from "../src/agent/decision.js";

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

test("template upper-red gate preserves red pin and sou without recoloring ordinary fives", async () => {
  const layout = layoutSchema.parse(JSON.parse(await readFile("config/layout-300-regression.json", "utf8")));
  const templates = await loadTemplates("templates/bootstrap", file => !/(?:holdout|capture|test)/i.test(file));
  assert.equal((await matchTile("artifacts/live/left-melds-chi-pon-20260928.jpg", layout.handSlots[8]!, templates)).tile, "0s");
  assert.equal((await matchTile("artifacts/live/template-red-five-pin-20260928.jpg", layout.handSlots[4]!, templates)).tile, "0p");
  assert.equal((await matchTile("artifacts/live/riichi-shimmer-hand-before-20260928.jpg", layout.handSlots[6]!, templates)).tile, "5p");
  assert.equal((await classifyTile("templates/bootstrap/5s__hf_base.png", templates)).tile, "5s");
  // The center-only red bamboo is an ordinary-five rendering, not an aka five.
  // The historical fixture name reflects a withdrawn diagnosis; do not use
  // that filename as the ground-truth red identity.
  assert.equal((await matchTile("artifacts/live/red-five-sou-read-normal-in-fixed-regression-20260928.jpg",
    layout.handSlots[11]!, templates)).tile, "5s");
});

test("live hand templates distinguish five through eight pin including diagonal seven", async () => {
  const layout = layoutSchema.parse(JSON.parse(await readFile("config/layout-300-regression.json", "utf8")));
  const templates = await loadTemplates("templates/bootstrap", file => !/(?:holdout|capture|test)/i.test(file));
  const matches = await Promise.all([6, 7, 8, 9].map(index => matchTile(
    "artifacts/live/hand-pin-six-seven-distinction-20260928.jpg", layout.handSlots[index]!, templates,
  )));
  // Human-labelled image: seven has three diagonal black pips above four red pips.
  // Do not use the auxiliary classifier's confidence as the ground-truth label.
  assert.deepEqual(matches.map(match => match.tile), ["5p", "6p", "7p", "8p"]);
});

test("three red bamboo rows prevent the actual nine-sou glare from becoming seven", async () => {
  const layout = layoutSchema.parse(JSON.parse(await readFile("config/layout-300-regression.json", "utf8")));
  const fixture = JSON.parse(await readFile("test/fixtures/nine-sou-as-seven-deal-in-20261021.json", "utf8"));
  const recognition = await recognizeHand("test/fixtures/hand-nine-sou-glare-20261021.jpg", layout, "templates/bootstrap");
  assert.deepEqual(recognition.tiles, fixture.physicalHand);
  // Color evidence rejects an impossible label; it does not manufacture
  // confidence or relax the existing automatic-calibration safety threshold.
  assert.ok(recognition.matches[12]!.confidence < layout.minimumTileConfidence);
  assert.equal(recognition.safe, false);
  const templates = await loadTemplates("templates/bootstrap", file => !/(?:holdout|capture|test)/i.test(file));
  for (const [name, index, expected] of [
    ["hand-nine-sou-before-glare-20261021.jpg", 12, "9s"],
    ["hand-seven-sou-control-a-20261021.jpg", 10, "7s"],
    ["hand-seven-sou-control-b-20261021.jpg", 11, "7s"],
  ] as const) {
    assert.equal((await matchTile(`test/fixtures/${name}`, layout.handSlots[index]!, templates)).tile, expected);
  }
});

test("correcting the actual concealed nine sou removes the false genbutsu from Jev choices", async () => {
  const fixture = JSON.parse(await readFile("test/fixtures/nine-sou-as-seven-deal-in-20261021.json", "utf8"));
  const before = parseGameState(fixture.state);
  const after = parseGameState({ ...before, hand: fixture.physicalHand.slice(0, 13), draw: fixture.physicalHand[13] });
  const offered: string[][] = [];
  const jev = { chooseDiscard: async (_state: unknown, candidates: Array<{ actionId: string; tile: string }>) => {
    offered.push(candidates.map(candidate => candidate.tile));
    return { actionId: candidates[0]!.actionId, confidence: 1, probabilities: { [candidates[0]!.actionId]: 1 },
      model: "first-offered-test", promptVersion: "test", latencyMs: 0 };
  } };
  await decide(before, { mode: "force-auto", jev: jev as any });
  await decide(after, { mode: "force-auto", jev: jev as any });
  assert.deepEqual(offered, [["7s"], ["8p"]]);
});

test("positive upper red ink keeps the actual red five sou from becoming six under glare", async () => {
  const layout = layoutSchema.parse(JSON.parse(await readFile("config/layout-300-regression.json", "utf8")));
  const fixture = JSON.parse(await readFile("test/fixtures/red-five-sou-as-six-20261021.json", "utf8"));
  const recognition = await recognizeHand("test/fixtures/hand-red-five-sou-glare-20261021.jpg", layout, "templates/bootstrap");
  assert.deepEqual(recognition.tiles, fixture.physicalHand);
  assert.ok(recognition.matches[12]!.confidence < layout.minimumTileConfidence);
  assert.equal(recognition.safe, false);
  const templates = await loadTemplates("templates/bootstrap", file => !/(?:holdout|capture|test)/i.test(file));
  // Independently labelled live controls contain green four bamboo and an
  // ordinary five with a central red mark; neither is an aka five.
  for (const [index, expected] of [[8, "4s"], [9, "5s"], [10, "7s"]] as const) {
    assert.equal((await matchTile("test/fixtures/hand-seven-sou-control-a-20261021.jpg",
      layout.handSlots[index]!, templates)).tile, expected);
  }
});

test("correcting the actual red five sou recovers tenpai and preserves it in Jev choices", async () => {
  const fixture = JSON.parse(await readFile("test/fixtures/red-five-sou-as-six-20261021.json", "utf8"));
  const before = parseGameState(fixture.state);
  const after = parseGameState({ ...before, hand: fixture.physicalHand.slice(0, 13), draw: fixture.physicalHand[13] });
  const offered: string[][] = [];
  const jev = { chooseDiscard: async (_state: unknown, candidates: Array<{ actionId: string; tile: string }>) => {
    offered.push(candidates.map(candidate => candidate.tile));
    return { actionId: candidates[0]!.actionId, confidence: 1, probabilities: { [candidates[0]!.actionId]: 1 },
      model: "first-offered-test", promptVersion: "test", latencyMs: 0 };
  } };
  const original = await decide(before, { mode: "force-auto", jev: jev as any });
  const corrected = await decide(after, { mode: "force-auto", jev: jev as any });
  assert.deepEqual(offered, [["3s", "6s", "9p"], ["9p"]]);
  assert.equal(original.candidates[0]!.shanten, 1);
  assert.equal(corrected.candidates[0]!.shanten, 0);
  // The real evaluated screenshot shows the riichi button. This verifies
  // the action on corrected tiles, not a counterfactual win or point gain.
  assert.deepEqual(corrected.selectedAction, { id: "riichi_discard_9p", action: "riichi", tile: "9p" });
});
