import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { layoutSchema } from "../src/recognition/layout.js";
import { HybridTileRecognizer } from "../src/recognition/hybridTileRecognizer.js";
import { recognizeConfiguredPublicTilesWithVit, recognizeSanmaPublicCandidates } from "../src/recognition/publicTileRecognizer.js";

const modelPresent = existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar") && existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt");
const layout = async () => { const l = layoutSchema.parse(JSON.parse(await readFile("config/layout-runtime.json", "utf8")));
  return { ...l, publicTileRegions: { ownDiscards: l.publicTileRegions!.ownDiscards! } }; };

test("blue one man misread as unavailable two man is unsafe in sanma", { skip: !modelPresent }, async () => {
  const l = await layout(), h = new HybridTileRecognizer(), file = "test/fixtures/sanma-impossible-river/2461.png";
  try {
    const original = await recognizeConfiguredPublicTilesWithVit(file, l, h, { sanmaBlueFaces: true });
    const generic = original.ownDiscards!.recognized[9]!;
    assert.equal(generic.tile, "2m"); assert.equal(generic.safe, true);
    const result = await recognizeSanmaPublicCandidates(file, l, "east", h, { sanmaBlueFaces: true });
    const tile = result.recognition.ownDiscards!.recognized[9]!;
    assert.equal(tile.tile, "2m"); assert.equal(tile.safe, false); assert.equal(tile.sanmaUnavailableTile, true);
    assert.equal(result.recognition.ownDiscards!.classificationSafe, false);
    assert.equal(result.observation.ownDiscardsObserved, false);
    assert.deepEqual(result.observation.ownDiscards, []);
  } finally { await h.close(); }
});

test("same river on a later neutral frame preserves valid one man", { skip: !modelPresent }, async () => {
  const l = await layout(), h = new HybridTileRecognizer();
  try {
    const result = await recognizeSanmaPublicCandidates("test/fixtures/sanma-impossible-river/2491.png", l, "east", h, { sanmaBlueFaces: true });
    const tile = result.recognition.ownDiscards!.recognized[9]!;
    assert.equal(tile.tile, "1m"); assert.equal(tile.safe, true); assert.equal(tile.sanmaUnavailableTile, undefined);
    assert.equal(result.observation.ownDiscardsObserved, false);
  } finally { await h.close(); }
});

test("sanma isolation does not change default yonma predictions for genuine two man", async () => {
  const l = await layout();
  const model = { backend: "vit" as const, async classifyTileImages(images: Buffer[]) {
    return images.map(() => ({ tile: "2m" as const, confidence: .99, runnerUpTile: "1m" as const, runnerUpConfidence: .001 }));
  } };
  const file = "test/fixtures/sanma-impossible-river/2491.png";
  const yonma = await recognizeConfiguredPublicTilesWithVit(file, l, model);
  assert.ok(yonma.ownDiscards!.recognized.length > 0);
  assert.ok(yonma.ownDiscards!.recognized.every(t => t.tile === "2m" && t.safe && t.sanmaUnavailableTile === undefined));
  const sanma = await recognizeSanmaPublicCandidates(file, l, "east", model);
  assert.ok(sanma.recognition.ownDiscards!.recognized.every(t => t.tile === "2m" && !t.safe && t.sanmaUnavailableTile));
  assert.equal(sanma.recognition.ownDiscards!.classificationSafe, false);
  assert.deepEqual(sanma.observation.ownDiscards, []);
  assert.equal(sanma.observation.ownDiscardsObserved, false);
});
