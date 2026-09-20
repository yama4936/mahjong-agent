import assert from "node:assert/strict";
import test from "node:test";
import path from "node:path";
import sharp from "sharp";
import { layoutSchema } from "../src/recognition/layout.js";
import { assertTemporalPublicObservation, hasSidewaysRiichiTile, recognizeConfiguredPublicTiles, recognizeConfiguredPublicTilesWithVit, recognizeExposedMelds, toPublicTileObservation, type PublicTileObservation, type PublicTileRecognitionRegion } from "../src/recognition/publicTileRecognizer.js";

function publicRegion(tiles: Array<{ tile: any; x: number; y?: number; width?: number; height?: number }>, rotationToUpright: 0 | 90 | 180 | 270 = 0): PublicTileRecognitionRegion {
  return {
    backend: "template",
    candidateCount: tiles.length,
    classificationSafe: true,
    rotationToUpright,
    recognized: tiles.map((tile) => ({
      x: tile.x, y: tile.y ?? 0, width: tile.width ?? 30, height: tile.height ?? 46,
      area: 1000, fillRatio: 0.8, tile: tile.tile, confidence: 0.995,
      runnerUpConfidence: 0.2, ambiguityMargin: 0.795, safe: true,
    })),
  };
}

test("classifies upright and rotated public tile candidates after orientation normalization", { timeout: 30_000 }, async () => {
  const workspace = path.resolve(import.meta.dirname, "..");
  const upright = await sharp(path.join(workspace, "templates/bootstrap/1m__hf_base.png"))
    .resize(40, 60, { fit: "fill" })
    .png()
    .toBuffer();
  const rotated = await sharp(upright).rotate(90).png().toBuffer();
  const screenshot = await sharp({
    create: { width: 320, height: 160, channels: 3, background: "#101820" },
  }).composite([
    { input: upright, left: 40, top: 50 },
    { input: rotated, left: 200, top: 60 },
  ]).png().toBuffer();
  const layout = layoutSchema.parse({
    viewport: { width: 320, height: 160 },
    handSlots: Array.from({ length: 13 }, (_, index) => ({ x: index, y: 0, width: 1, height: 1 })),
    clickPoints: Array.from({ length: 13 }, (_, index) => ({ x: index, y: 0 })),
    minimumTileConfidence: 0.9,
    publicTileRegions: {
      ownDiscards: { x: 20, y: 30, width: 100, height: 100 },
      rightDiscards: { x: 170, y: 30, width: 120, height: 100, rotationToUpright: 270 },
      oppositeDiscards: { x: 130, y: 0, width: 30, height: 30 },
    },
  });
  const result = await recognizeConfiguredPublicTiles(screenshot, layout, path.join(workspace, "templates/bootstrap"), {
    minimumArea: 100,
    minimumWidth: 20,
    minimumHeight: 20,
  });
  assert.equal(result.ownDiscards?.recognized[0]?.tile, "1m");
  assert.equal(result.rightDiscards?.recognized[0]?.tile, "1m");
  assert.equal(result.ownDiscards?.classificationSafe, true);
  assert.equal(result.rightDiscards?.classificationSafe, true);
  assert.equal(result.oppositeDiscards?.candidateCount, 0);
  assert.equal(result.oppositeDiscards?.classificationSafe, false);
  assert.equal(result.ownDiscards?.backend, "template");
});

test("batch-classifies configured public candidates with ViT", async () => {
  const upright = await sharp({ create: { width: 30, height: 46, channels: 3, background: "#f5f1df" } }).png().toBuffer();
  const screenshot = await sharp({ create: { width: 200, height: 120, channels: 3, background: "#101820" } })
    .composite([{ input: upright, left: 50, top: 40 }]).png().toBuffer();
  const layout = layoutSchema.parse({
    viewport: { width: 200, height: 120 },
    handSlots: Array.from({ length: 13 }, (_, index) => ({ x: index, y: 0, width: 1, height: 1 })),
    clickPoints: Array.from({ length: 13 }, (_, index) => ({ x: index, y: 0 })),
    publicTileRegions: { ownDiscards: { x: 30, y: 20, width: 80, height: 80 } },
  });
  let batchSize = 0;
  const result = await recognizeConfiguredPublicTilesWithVit(screenshot, layout, {
    classifyTileImages: async (images) => {
      batchSize = images.length;
      return images.map(() => ({ tile: "3p" as const, confidence: 0.96, runnerUpTile: "4p" as const, runnerUpConfidence: 0.02 }));
    },
  }, { minimumArea: 100, minimumWidth: 20, minimumHeight: 20 });
  assert.equal(batchSize, 1);
  assert.equal(result.ownDiscards?.backend, "vit");
  assert.equal(result.ownDiscards?.recognized[0]?.tile, "3p");
  assert.equal(result.ownDiscards?.classificationSafe, true);
  const observation = toPublicTileObservation(result);
  assert.deepEqual(observation.ownDiscards, ["3p"]);
  assert.deepEqual(observation.doraIndicators, []);
  assert.deepEqual(observation.opponentDiscards.map((opponent) => opponent.seat), ["south", "west", "north"]);
  assert.deepEqual(observation.otherVisibleTiles, []);
  assert.equal(observation.complete, false);
});

test("public river observations preserve seat assignment and temporal prefixes", () => {
  const base: PublicTileObservation = {
    doraIndicators: [],
    ownDiscards: ["1m"],
    opponentDiscards: [
      { seat: "south" as const, discards: ["2m" as const] },
      { seat: "west" as const, discards: [] },
      { seat: "north" as const, discards: [] },
    ],
    ownMeldTiles: [], otherVisibleTiles: ["2m"], acceptedTiles: 2, detectedCandidates: 2, complete: false as const,
  };
  const next = { ...base, ownDiscards: ["1m" as const, "3m" as const] };
  assert.doesNotThrow(() => assertTemporalPublicObservation(base, next));
  assert.throws(() => assertTemporalPublicObservation(next, base), /Own river regressed/);
});

test("does not promote individually confident tiles from an invalid river grid", () => {
  const invalid = publicRegion([{ tile: "3p", x: 0 }]);
  invalid.classificationSafe = false;
  const observation = toPublicTileObservation({ ownDiscards: invalid });
  assert.deepEqual(observation.ownDiscards, []);
  assert.equal(observation.acceptedTiles, 0);
});

test("keeps calibrated dora indicators separate from other visible tiles", () => {
  const observation = toPublicTileObservation({
    doraIndicators: publicRegion([{ tile: "4s", x: 0 }]),
    ownDiscards: publicRegion([{ tile: "1m", x: 0 }]),
  });
  assert.deepEqual(observation.doraIndicators, ["4s"]);
  assert.deepEqual(observation.ownDiscards, ["1m"]);
  assert.deepEqual(observation.otherVisibleTiles, []);
});

test("detects sideways riichi evidence after table-orientation normalization", () => {
  assert.equal(hasSidewaysRiichiTile(publicRegion([{ tile: "5m", x: 0, width: 48, height: 30 }])), true);
  // A right-player normal tile is landscape on screen, then upright after 90°.
  assert.equal(hasSidewaysRiichiTile(publicRegion([{ tile: "5m", x: 0, width: 48, height: 30 }], 90)), false);
  const previous = toPublicTileObservation({
    rightDiscards: publicRegion([{ tile: "5m", x: 0, width: 30, height: 48 }], 90),
  }, "east");
  const current = toPublicTileObservation({
    rightDiscards: publicRegion([{ tile: "5m", x: 0, width: 48, height: 30 }], 90),
  }, "east");
  assert.equal(current.opponentDiscards[0]?.riichiDeclared, false);
  assert.throws(() => assertTemporalPublicObservation(previous, current), /River regressed|Riichi evidence regressed/);
});

test("promotes only complete unambiguous exposed meld groups", () => {
  const chi = recognizeExposedMelds(publicRegion([
    { tile: "3p", x: 0 }, { tile: "4p", x: 30 }, { tile: "5p", x: 60 },
  ]));
  const pon = recognizeExposedMelds(publicRegion([
    { tile: "E", x: 0 }, { tile: "E", x: 30 }, { tile: "E", x: 60 },
  ]));
  const minkan = recognizeExposedMelds(publicRegion([
    { tile: "7s", x: 0 }, { tile: "7s", x: 30 }, { tile: "7s", x: 60 }, { tile: "7s", x: 90 },
  ]));
  assert.equal(chi[0]?.type, "chi");
  assert.equal(pon[0]?.type, "pon");
  assert.equal(minkan[0]?.type, "minkan");
  assert.deepEqual(recognizeExposedMelds(publicRegion([
    { tile: "1m", x: 0 }, { tile: "3m", x: 30 }, { tile: "5m", x: 60 },
  ])), []);
});
