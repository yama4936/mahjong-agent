import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { assertPublicObservationAllowed, assertRecognizerAllowedForAuto, assertTemplateSetMatchesCalibration, expectedSelfTurnTileCount, TurnRearmGate } from "../src/agent/controller.js";
import { layoutSchema } from "../src/recognition/layout.js";
import { fingerprintTemplateDirectory } from "../src/recognition/templateValidator.js";

test("turn gate suppresses duplicate safe frames", () => {
  const gate = new TurnRearmGate(3);
  assert.equal(gate.observe(true).shouldProcess, true);
  assert.equal(gate.observe(true).shouldProcess, false);
  assert.equal(gate.observe(true).shouldProcess, false);
});

test("turn gate requires consecutive unsafe frames before rearming", () => {
  const gate = new TurnRearmGate(3);
  gate.observe(true);
  assert.equal(gate.observe(false).rearmed, false);
  gate.observe(true);
  assert.equal(gate.observe(false).rearmed, false);
  assert.equal(gate.observe(false).rearmed, false);
  assert.equal(gate.observe(false).rearmed, true);
  assert.equal(gate.observe(true).shouldProcess, true);
});

test("expected turn tile count comes only from known open melds", () => {
  assert.equal(expectedSelfTurnTileCount(0), 14);
  assert.equal(expectedSelfTurnTileCount(1), 11);
  assert.equal(expectedSelfTurnTileCount(4), 2);
  assert.notEqual(expectedSelfTurnTileCount(0), 2);
});

test("turn gate rearms after a changed safe hand remains stable", () => {
  const gate = new TurnRearmGate(3);
  assert.equal(gate.observe(true, "self_turn:1m,2m").shouldProcess, true);
  assert.equal(gate.observe(true, "self_turn:1m,3m").rearmed, false);
  assert.equal(gate.observe(true, "self_turn:1m,3m").rearmed, false);
  assert.equal(gate.observe(true, "self_turn:1m,3m").shouldProcess, true);
  assert.equal(gate.observe(true, "self_turn:1m,3m").shouldProcess, false);
});

test("advisor turn gate rearms on one unsafe frame or two stable changed-hand frames", () => {
  const unsafeGate = new TurnRearmGate(1, 2);
  unsafeGate.observe(true, "self_turn:1m,2m");
  assert.equal(unsafeGate.observe(false).rearmed, true);
  assert.equal(unsafeGate.observe(true, "self_turn:1m,3m").shouldProcess, true);

  const changedGate = new TurnRearmGate(1, 2);
  changedGate.observe(true, "self_turn:1m,2m");
  assert.equal(changedGate.observe(true, "self_turn:1m,3m").shouldProcess, false);
  assert.equal(changedGate.observe(true, "self_turn:1m,3m").shouldProcess, true);
});

test("turn gate does not rearm for unstable changed-hand recognition", () => {
  const gate = new TurnRearmGate(3);
  gate.observe(true, "self_turn:1m,2m");
  assert.equal(gate.observe(true, "self_turn:1m,3m").rearmed, false);
  assert.equal(gate.observe(true, "self_turn:1m,4m").rearmed, false);
  assert.equal(gate.observe(true, "self_turn:1m,3m").rearmed, false);
  assert.equal(gate.observe(true, "self_turn:1m,2m").rearmed, false);
});

test("auto calibration fingerprint rejects a changed template set", async () => {
  const directory = await mkdtemp(path.join(tmpdir(), "jantama-fingerprint-"));
  await writeFile(path.join(directory, "1m.png"), Buffer.from("first"));
  const fingerprint = await fingerprintTemplateDirectory(directory);
  const base = {
    viewport: { width: 100, height: 100 },
    handSlots: Array.from({ length: 13 }, (_, index) => ({ x: index, y: 0, width: 1, height: 1 })),
    clickPoints: Array.from({ length: 13 }, (_, index) => ({ x: index, y: 0 })),
  };
  const layout = layoutSchema.parse({
    ...base,
    autoOperation: {
      enabled: true,
      matcherVersion: "2",
      tileMatcher: "raw",
      samples: 185,
      accuracy: 1,
      automationSafeRate: 1,
      validatedAt: "2026-09-19T00:00:00.000Z",
      templateSetFingerprint: fingerprint,
    },
  });
  await assertTemplateSetMatchesCalibration(layout, directory);
  await assert.rejects(assertTemplateSetMatchesCalibration({ ...layout, tileMatcher: "face" }, directory), /Matcher does not match/);
  await writeFile(path.join(directory, "1m.png"), Buffer.from("changed"));
  await assert.rejects(assertTemplateSetMatchesCalibration(layout, directory), /does not match/);
});

test("ViT remains Advisor-only until its separate live calibration exists", () => {
  const recognition = {
    backend: "vit" as const,
    tiles: [],
    matches: [],
    confidence: 1,
    ambiguityMargin: 1,
    presenceFractions: [],
    turnReady: true,
    safe: true,
    redFiveClassification: "unsupported" as const,
  };
  assert.doesNotThrow(() => assertRecognizerAllowedForAuto("advisor", recognition));
  assert.throws(() => assertRecognizerAllowedForAuto("auto", recognition), /Advisor-only/);
});

test("hybrid recognizer remains Advisor-only until independent live calibration", () => {
  const recognition = {
    backend: "hybrid" as const,
    tiles: ["0m" as const],
    matches: [],
    confidence: 1,
    ambiguityMargin: 1,
    presenceFractions: [],
    turnReady: true,
    safe: true,
    redFiveClassification: "supported" as const,
  };
  assert.doesNotThrow(() => assertRecognizerAllowedForAuto("advisor", recognition));
  assert.throws(() => assertRecognizerAllowedForAuto("auto", recognition), /Advisor-only/);
});

test("uncalibrated public observations remain Advisor-only", () => {
  assert.doesNotThrow(() => assertPublicObservationAllowed("advisor", true));
  assert.doesNotThrow(() => assertPublicObservationAllowed("auto", false));
  assert.throws(() => assertPublicObservationAllowed("auto", true), /forbidden in Auto mode/);
});
