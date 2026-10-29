import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import sharp from "sharp";
import { cachedPublicStatePatch } from "../src/agent/publicCache.js";
import { publicGameStateSchema } from "../src/game/state.js";
import { layoutSchema } from "../src/recognition/layout.js";
import { HybridTileRecognizer } from "../src/recognition/hybridTileRecognizer.js";
import { opponentStatesFromObservation, recognizeConfiguredPublicTilesWithVit, toPublicTileObservation } from "../src/recognition/publicTileRecognizer.js";
import type { VitTilePrediction } from "../src/recognition/vitRecognizer.js";
// @ts-expect-error Repository launch helpers are native JavaScript modules.
import { defaultOperatorLayoutArgs } from "../scripts/operator-layout.mjs";

async function fixture() {
  const args = defaultOperatorLayoutArgs(path.resolve(import.meta.dirname, ".."), []);
  const layout = layoutSchema.parse(JSON.parse(await readFile(args[1]!, "utf8")));
  const native = JSON.parse(await readFile("test/fixtures/runtime-public-left-melds-20261030.json", "utf8"));
  const screenshot = await sharp({ create: { width: layout.viewport.width, height: layout.viewport.height,
    channels: 3, background: "black" } }).composite([{ input: Buffer.from(native.pngBase64, "base64"),
    left: native.region.left, top: native.region.top }]).png().toBuffer();
  return { layout, screenshot };
}

function prediction(tile: VitTilePrediction["tile"], confidence = 0.9999, runnerUpConfidence = 0.00001): VitTilePrediction {
  return { tile, confidence, runnerUpTile: "2s", runnerUpConfidence };
}
function originalPredictions() {
  return [prediction("0s", 0.919), prediction("4s"), prediction("6s"), prediction("P", 0.9968),
    { ...prediction("P", 0.48246, 0.37992), runnerUpTile: "4s" as const }, prediction("P", 0.9955)];
}
function model(original = originalPredictions(), retry = prediction("P"), backend: "hybrid" | "vit" = "hybrid") {
  const calls: Buffer[][] = [];
  return { backend, calls, async classifyTileImages(images: Buffer[]) {
    calls.push(images);
    assert.ok(calls.length <= 2, "only the initial batch and one bounded retry are permitted");
    return calls.length === 1 ? original : [retry];
  } };
}

test("native sideways white pon recovers using the default layout and preserves empty/ghost-kan rejection", {
  skip: !existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar")
    || !existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt"),
}, async () => {
  const { layout, screenshot } = await fixture();
  const classifier = new HybridTileRecognizer();
  try {
    const before = await recognizeConfiguredPublicTilesWithVit(screenshot, layout, classifier, { retryLeftWhitePon: false });
    assert.equal(before.leftMelds?.classificationSafe, false);
    const after = await recognizeConfiguredPublicTilesWithVit(screenshot, layout, classifier);
    const left = toPublicTileObservation(after, "north").opponentDiscards[2]!;
    assert.equal(left.meldsObserved, true);
    assert.deepEqual(left.melds?.map(meld => [meld.type, meld.tiles]), [
      ["pon", ["P", "P", "P"]], ["chi", ["6s", "4s", "0s"]],
    ]);
    const old = before.leftMelds!.recognized[4]!, current = after.leftMelds!.recognized[4]!;
    for (const key of ["x", "y", "width", "height", "sideways"] as const) assert.equal(current[key], old[key]);
    assert.equal(current.whitePonRotationEvidence?.originalConfidence, old.confidence);
    assert.ok(current.confidence >= 0.99);
    const observation = toPublicTileObservation(after, "north");
    const patch = cachedPublicStatePatch({ ...observation, capturedAt: "2026-10-29T18:10:37Z",
      recognizedAt: "2026-10-29T18:10:38Z", recognitionLatencyMs: 100, configuredRegions: Object.keys(layout.publicTileRegions!) },
    ["1m", "2m", "3m", "7m", "8m", "9m", "4s", "4s", "7s", "7s", "8s", "8s", "P", "8p"]);
    const west = publicGameStateSchema.parse(patch.patch).opponents.find(opponent => opponent.seat === "west")!;
    assert.equal(patch.rejectedTiles, 0);
    assert.equal(west.openMelds, 2);
    assert.equal(west.openMeldsObserved, true);
    assert.ok(west.melds!.every(meld => meld.type !== "minkan"));
    const empty = toPublicTileObservation(await recognizeConfiguredPublicTilesWithVit(
      "test/fixtures/left-meld-boundary-empty-control-20261022.jpg", layout, classifier), "north").opponentDiscards[2]!;
    assert.equal(empty.meldsObserved, true);
    assert.deepEqual(empty.melds, []);
    const ghost = toPublicTileObservation(await recognizeConfiguredPublicTilesWithVit(
      "artifacts/live/ghost-white-kan-cache-698264b-20260929.jpg", layout, classifier), "west");
    const cleared = opponentStatesFromObservation(ghost, [{ seat: "east", discards: [], riichi: false,
      openMelds: 1, openMeldsObserved: false, melds: [{ type: "minkan", tiles: ["P", "P", "P", "P"] }] }])
      .find(opponent => opponent.seat === "east")!;
    assert.equal(cleared.openMelds, 0);
    assert.deepEqual(cleared.melds, []);
    assert.equal(cleared.openMeldsObserved, true);
  } finally { await classifier.close(); }
});

test("retry rotates the identical native crop without trimming and retains original confidence evidence", async () => {
  const { layout, screenshot } = await fixture();
  const classifier = model();
  const result = await recognizeConfiguredPublicTilesWithVit(screenshot, layout, classifier);
  assert.deepEqual(classifier.calls.map(images => images.length), [6, 1]);
  const actual = await sharp(classifier.calls[1]![0]!).raw().toBuffer();
  const expected = await sharp(classifier.calls[0]![4]!).rotate(180).raw().toBuffer();
  assert.deepEqual(actual, expected);
  assert.equal(result.leftMelds?.classificationSafe, true);
  assert.equal(result.leftMelds?.recognized[4]?.whitePonRotationEvidence?.originalConfidence, 0.48246);
  assert.equal(result.leftMelds?.recognized[4]?.whitePonRotationEvidence?.additionalRotation, 180);
});

test("non-white, four-white kan, weak anchors, weak original margin and malformed rows cannot request a retry", async () => {
  const { layout, screenshot } = await fixture();
  const cases = [
    (p: VitTilePrediction[]) => { p[4] = prediction("C", 0.482, 0.379); },
    (p: VitTilePrediction[]) => { p[0] = prediction("P"); },
    (p: VitTilePrediction[]) => { p[3] = prediction("P", 0.98); },
    (p: VitTilePrediction[]) => { p[3] = prediction("P", 0.999, 0.02); },
    (p: VitTilePrediction[]) => { p[4] = prediction("P", 0.399, 0.1); },
    (p: VitTilePrediction[]) => { p[4] = prediction("P", 0.482, 0.45); },
    (p: VitTilePrediction[]) => { p[0] = prediction("1m"); },
    (p: VitTilePrediction[]) => { p[2] = prediction("6s", 0.4); },
  ];
  for (const change of cases) {
    const predictions = originalPredictions(); change(predictions);
    const classifier = model(predictions);
    const result = await recognizeConfiguredPublicTilesWithVit(screenshot, layout, classifier);
    assert.deepEqual(classifier.calls.map(images => images.length), [6]);
    assert.equal(result.leftMelds?.classificationSafe, false);
    assert.ok(result.leftMelds?.recognized.every(tile => !tile.whitePonRotationEvidence));
  }
});

test("safe ordinary rows, disabled retries, other players and other backends avoid the extra classification", async () => {
  const { layout, screenshot } = await fixture();
  const safe = originalPredictions(); safe[4] = prediction("P");
  const ordinary = model(safe);
  const result = await recognizeConfiguredPublicTilesWithVit(screenshot, layout, ordinary);
  assert.equal(result.leftMelds?.classificationSafe, true);
  assert.deepEqual(ordinary.calls.map(images => images.length), [6]);
  assert.ok(result.leftMelds?.recognized.every(tile => !tile.whitePonRotationEvidence));
  for (const classifier of [model(), model(undefined, undefined, "vit")]) {
    const result = await recognizeConfiguredPublicTilesWithVit(screenshot, layout, classifier,
      classifier.backend === "hybrid" ? { retryLeftWhitePon: false } : {});
    assert.equal(result.leftMelds?.classificationSafe, false);
    assert.deepEqual(classifier.calls.map(images => images.length), [6]);
  }
  const other = model();
  await recognizeConfiguredPublicTilesWithVit(screenshot, { ...layout,
    publicTileRegions: { rightMelds: layout.publicTileRegions!.leftMelds! } }, other);
  assert.deepEqual(other.calls.map(images => images.length), [6]);
  for (const change of [{ rotationToUpright: 90 as const }, { sidewaysAspectRatio: 100 }, { sidewaysAspectRatio: 0.1 }]) {
    const classifier = model();
    await recognizeConfiguredPublicTilesWithVit(screenshot, { ...layout, publicTileRegions: {
      leftMelds: { ...layout.publicTileRegions!.leftMelds!, ...change },
    } }, classifier);
    assert.deepEqual(classifier.calls.map(images => images.length), [6]);
  }
});

test("a retry must independently confirm white with stronger confidence and margin and respect caller thresholds", async () => {
  const { layout, screenshot } = await fixture();
  for (const retry of [prediction("4s"), prediction("P", 0.989), prediction("P", 0.999, 0.02),
    prediction("P", Number.NaN)]) {
    const classifier = model(undefined, retry);
    const result = await recognizeConfiguredPublicTilesWithVit(screenshot, layout, classifier);
    assert.deepEqual(classifier.calls.map(images => images.length), [6, 1]);
    assert.equal(result.leftMelds?.classificationSafe, false);
    assert.equal(result.leftMelds?.recognized[4]?.confidence, originalPredictions()[4]!.confidence);
    assert.equal(result.leftMelds?.recognized[4]?.whitePonRotationEvidence, undefined);
  }
  const strict = model();
  const result = await recognizeConfiguredPublicTilesWithVit(screenshot, layout, strict, { minimumConfidence: 1 });
  assert.equal(result.leftMelds?.classificationSafe, false);
  assert.deepEqual(strict.calls.map(images => images.length), [6]);
});
