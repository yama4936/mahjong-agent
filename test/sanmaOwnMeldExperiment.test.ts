import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";
import sharp from "sharp";
import { layoutSchema } from "../src/recognition/layout.js";
import { HybridTileRecognizer } from "../src/recognition/hybridTileRecognizer.js";
import { sanmaOwnMeldExperiment } from "../src/recognition/sanmaOwnMeldExperiment.js";
import { recognizeConfiguredPublicTilesWithVit, recognizeExposedMelds } from "../src/recognition/publicTileRecognizer.js";

const fixture = "test/fixtures/sanma-melds/own-pon-kan-redacted.png";
const loadLayout = async () => layoutSchema.parse(JSON.parse(await readFile("config/layout-runtime.json", "utf8")));
const failModel = { async classifyTileImages(): Promise<never> { throw new Error("unexpected model invocation"); } };

test("the optional crop refuses unknown, invalid, or overlapping hand extent", async () => {
  const l = await loadLayout();
  for (const x of [undefined, -1, 1.1, 1921, 1221, 1578]) {
    const r = await sanmaOwnMeldExperiment(fixture, l, failModel, x);
    assert.equal(r.status, "unknown");
    assert.equal(r.complete, false);
    assert.deepEqual(r.hypotheses, []);
    assert.ok(r.reason);
  }
  const bad = { ...l, publicTileRegions: { ownMelds: { ...l.publicTileRegions!.ownMelds!, x: 1500 } } };
  assert.equal((await sanmaOwnMeldExperiment(fixture, bad, failModel, 1000)).reason, "uncalibrated");
});

test("the real seven-tile row extends beyond the existing own meld crop", {
  skip: !existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar") || !existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt"),
}, async () => {
  const l = await loadLayout();
  const h = new HybridTileRecognizer();
  try {
    const baseline = await recognizeConfiguredPublicTilesWithVit(fixture, { ...l, publicTileRegions: { ownMelds: l.publicTileRegions!.ownMelds! } }, h);
    assert.deepEqual(recognizeExposedMelds(baseline.ownMelds), []);
    // The saved unredacted frame shows the drawn tile ending before x=1010.
    // Supplying this bound is a manual assumption; the function cannot prove it.
    const result = await sanmaOwnMeldExperiment(fixture, l, h, 1010);
    assert.equal(result.status, "unknown");
    assert.equal(result.complete, false);
    assert.deepEqual(result.hypotheses.map(m => [m.type, m.tiles]), [
      ["pon", ["7p", "7p", "7p"]], ["minkan", ["F", "F", "F", "F"]],
    ]);
  } finally { await h.close(); }
});

test("real 3p and 4p full concealed hands overlap the extended region", async () => {
  const layout = await loadLayout();
  // The real source images each contain a drawn tile extending to x≈1578.
  for (const image of ["test/fixtures/sanma-melds/own-no-meld-redacted.png",
    "test/fixtures/hand-seven-sou-control-a-20261021.jpg"]) {
    const result = await sanmaOwnMeldExperiment(image, layout, failModel, 1578);
    assert.equal(result.reason, "hand_overlaps_extended_region");
    assert.equal(result.status, "unknown");
    assert.equal(result.complete, false);
    assert.deepEqual(result.hypotheses, []);
  }
});

test("existing left-opponent detector finds the three visible dragons in a real sanma frame", {
  skip: !existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar") || !existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt"),
}, async () => {
  const l = await loadLayout();
  const h = new HybridTileRecognizer();
  try {
    const recognition = await recognizeConfiguredPublicTilesWithVit("test/fixtures/sanma-melds/left-pon-redacted.png",
      { ...l, publicTileRegions: { leftMelds: l.publicTileRegions!.leftMelds! } }, h);
    assert.deepEqual(recognizeExposedMelds(recognition.leftMelds).map(m => [m.type, m.tiles]),
      [["pon", ["C", "C", "C"]]]);
  } finally { await h.close(); }
});


test("no visible candidate remains unknown rather than an observed empty meld row", async () => {
  const layout = await loadLayout();
  const blank = await sharp({ create: { width: 1920, height: 1080, channels: 3, background: "#000" } }).png().toBuffer();
  const result = await sanmaOwnMeldExperiment(blank, layout, failModel, 1000);
  assert.equal(result.reason, "incomplete_or_uncertain");
  assert.equal(result.status, "unknown");
  assert.equal(result.complete, false);
  assert.deepEqual(result.hypotheses, []);
});
