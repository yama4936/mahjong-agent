import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import sharp from "sharp";
import { layoutSchema } from "../src/recognition/layout.js";
import { HybridTileRecognizer } from "../src/recognition/hybridTileRecognizer.js";
import { recognizeConfiguredPublicTilesWithVit, toPublicTileObservation } from "../src/recognition/publicTileRecognizer.js";
// @ts-expect-error Repository launch helpers are native JavaScript modules.
import { defaultOperatorLayoutArgs } from "../scripts/operator-layout.mjs";

const root = path.resolve(import.meta.dirname, "..");

test("operator defaults to the full public-board layout despite the saved hand-only layout", async () => {
  const baseline = JSON.parse(await readFile(
    path.join(root, "test/fixtures/runtime-hand-baseline-20260920.json"), "utf8"));
  const savedHand = layoutSchema.parse(baseline.handConfiguration);
  const args = defaultOperatorLayoutArgs(root, ["--action-deadline-ms=300000"]);
  assert.deepEqual(args, ["--layout", path.join(root, "config/layout-runtime.json")]);
  const layout = layoutSchema.parse(JSON.parse(await readFile(args[1]!, "utf8")));
  const { publicTileRegions: _newPublic, ...runtimeHand } = layout;
  assert.deepEqual(runtimeHand, savedHand);
  const calibrated = layoutSchema.parse(JSON.parse(await readFile(
    path.join(root, "config/layout-300-regression.json"), "utf8")));
  assert.deepEqual(layout.publicTileRegions, calibrated.publicTileRegions);
  assert.deepEqual(Object.keys(layout.publicTileRegions ?? {}).sort(), [
    "doraIndicators", "ownDiscards", "rightDiscards", "oppositeDiscards", "leftDiscards",
    "ownMelds", "rightMelds", "oppositeMelds", "leftMelds",
  ].sort());
});

test("operator preserves explicit layout overrides in both accepted forms", () => {
  for (const args of [["--layout", "custom.layout.json"], ["--layout=custom.layout.json"]]) {
    const original = [...args];
    assert.deepEqual(defaultOperatorLayoutArgs(root, args), []);
    assert.deepEqual(args, original);
  }
});

test("default runtime scans the native omitted left melds and preserves the weak-white confidence guard", {
  skip: !existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar")
    || !existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt"),
}, async () => {
  const args = defaultOperatorLayoutArgs(root, []);
  const layout = layoutSchema.parse(JSON.parse(await readFile(args[1]!, "utf8")));
  const fixture = JSON.parse(await readFile("test/fixtures/runtime-public-left-melds-20261030.json", "utf8"));
  const screenshot = await sharp({ create: { width: layout.viewport.width, height: layout.viewport.height,
    channels: 3, background: "black" } }).composite([{ input: Buffer.from(fixture.pngBase64, "base64"),
    left: fixture.region.left, top: fixture.region.top }]).png().toBuffer();
  const classifier = new HybridTileRecognizer();
  try {
    const result = await recognizeConfiguredPublicTilesWithVit(screenshot, layout, classifier, { retryLeftWhitePon: false });
    assert.equal(result.leftMelds?.candidateCount, 6);
    assert.deepEqual(result.leftMelds?.recognized.map(tile => tile.tile), ["0s", "4s", "6s", "P", "P", "P"]);
    // Enabling the missing region cannot certify a weak white tile as safe.
    assert.equal(result.leftMelds?.recognized[4]?.safe, false);
    const left = toPublicTileObservation(result, "north").opponentDiscards[2]!;
    assert.equal(left.seat, "west");
    assert.equal(left.meldsObserved, false);
    assert.deepEqual(left.melds, []);
    const empty = toPublicTileObservation(await recognizeConfiguredPublicTilesWithVit(
      "test/fixtures/left-meld-boundary-empty-control-20261022.jpg", layout, classifier), "north").opponentDiscards[2]!;
    assert.equal(empty.meldsObserved, true);
    assert.deepEqual(empty.melds, []);
  } finally { await classifier.close(); }
});
