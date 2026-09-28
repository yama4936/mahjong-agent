import assert from "node:assert/strict";
import test from "node:test";
import path from "node:path";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { HybridTileRecognizer } from "../src/recognition/hybridTileRecognizer.js";
import sharp from "sharp";
import { layoutSchema } from "../src/recognition/layout.js";
import { opponentStatesFromObservation } from "../src/recognition/publicTileRecognizer.js";
import { detectConfiguredPublicRegions } from "../src/recognition/regionDetector.js";
import { knownTiles, knownTilesOutsideHand, parseGameState, parsePublicGameState } from "../src/game/state.js";
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

test("calibrated opposite meld faces recover red chi, adjacent pon and third chi with real Hybrid", {
  skip: !existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar") || !existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt"),
}, async () => {
  const base = layoutSchema.parse(JSON.parse(await readFile("config/layout-300-regression.json", "utf8")));
  const layout = { ...base, publicTileRegions: { oppositeMelds: base.publicTileRegions!.oppositeMelds! } };
  const recognizer = new HybridTileRecognizer();
  try {
    for (const [file, expected] of [
      ["adjacent-opposite-melds-20260928.jpg", ["chi:0s,4s,6s", "pon:E,E,E"]],
      ["board-score-opposite-low-confidence-20260928.png", ["chi:0p,3p,4p", "chi:0s,4s,6s", "pon:E,E,E"]],
      ["south4-riichi-before-loss-20260928.jpg", ["chi:6s,7s,8s"]],
    ] as const) {
      const recognition = await recognizeConfiguredPublicTilesWithVit(`artifacts/live/${file}`, layout, recognizer);
      const melds = recognizeExposedMelds(recognition.oppositeMelds);
      assert.deepEqual(melds.map(meld => `${meld.type}:${[...meld.tiles].sort().join(",")}`).sort(), [...expected].sort(), file);
      assert.equal(toPublicTileObservation(recognition).opponentDiscards[1]?.meldsObserved, true, file);
    }
  } finally {
    await recognizer.close();
  }
});

test("calibrated left melds recover chi and pon without picking up own hand edge", {
  skip: !existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar") || !existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt"),
}, async () => {
  const base = layoutSchema.parse(JSON.parse(await readFile("config/layout-300-regression.json", "utf8")));
  const layout = { ...base, publicTileRegions: { leftMelds: base.publicTileRegions!.leftMelds! } };
  const recognizer = new HybridTileRecognizer();
  try {
    const populated = await recognizeConfiguredPublicTilesWithVit("artifacts/live/left-melds-chi-pon-20260928.jpg", layout, recognizer);
    assert.equal(populated.leftMelds?.candidateCount, 6);
    const melds = recognizeExposedMelds(populated.leftMelds);
    assert.deepEqual(melds.map(meld => `${meld.type}:${[...meld.tiles].sort().join(",")}`).sort(), ["chi:6m,7m,8m", "pon:N,N,N"]);
    assert.equal(toPublicTileObservation(populated).opponentDiscards[2]?.meldsObserved, true);
    const empty = await recognizeConfiguredPublicTilesWithVit("artifacts/live/adjacent-opposite-melds-20260928.jpg", layout, recognizer);
    assert.equal(empty.leftMelds?.candidateCount, 0);
    assert.deepEqual(recognizeExposedMelds(empty.leftMelds), []);
  } finally {
    await recognizer.close();
  }
});

test("real Hybrid agrees on ordered red-aware hand across riichi shimmer phases", {
  skip: !existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar") || !existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt"),
}, async () => {
  const layout = layoutSchema.parse(JSON.parse(await readFile("config/layout-300-regression.json", "utf8")));
  const expected = ["3m", "3m", "0m", "7m", "3p", "4p", "5p", "6p", "8p", "8p", "2s", "3s", "4s", "6p"];
  const recognizer = new HybridTileRecognizer();
  try {
    for (const phase of ["before", "after"]) {
      const result = await recognizer.recognizeHand(`artifacts/live/riichi-shimmer-hand-${phase}-20260928.jpg`, layout);
      assert.equal(result.safe, true, phase);
      assert.deepEqual(result.tiles, expected, phase);
    }
  } finally {
    await recognizer.close();
  }
});

test("missing and undecodable meld regions are unknown, not confirmed closed hands", () => {
  const missing = toPublicTileObservation({});
  assert.equal(missing.opponentDiscards[0]?.meldsObserved, false);
  const prior = [{ seat: "south" as const, discards: [], riichi: true, openMelds: 2 }];
  const states = opponentStatesFromObservation(missing, prior);
  assert.equal(states[0]?.openMelds, 2);
  assert.equal(states[0]?.openMeldsObserved, false);
  assert.equal(states[0]?.riichi, true);
  assert.equal(states[1]?.openMeldsObserved, false);
  const malformed = toPublicTileObservation({ rightMelds: publicRegion([
    { tile: "1m", x: 0 }, { tile: "3m", x: 30 }, { tile: "5m", x: 60 },
  ]) });
  assert.equal(malformed.opponentDiscards[0]?.meldsObserved, false);
});

test("complete meld evidence updates counts but regressing evidence cannot erase them", () => {
  const region = publicRegion([
    { tile: "E", x: 0 }, { tile: "E", x: 30 }, { tile: "E", x: 60 },
  ]);
  const observation = toPublicTileObservation({ rightMelds: region });
  assert.equal(observation.opponentDiscards[0]?.meldsObserved, true);
  const current = opponentStatesFromObservation(observation);
  assert.equal(current[0]?.openMelds, 1);
  assert.equal(current[0]?.openMeldsObserved, true);
  const previous = [{ seat: "south" as const, discards: [], riichi: false, openMelds: 2 }];
  assert.equal(opponentStatesFromObservation(observation, previous)[0]?.openMelds, 2);
  assert.equal(opponentStatesFromObservation(observation, previous)[0]?.openMeldsObserved, false);
  region.candidateCount = 4;
  assert.equal(toPublicTileObservation({ rightMelds: region }).opponentDiscards[0]?.meldsObserved, false);
});

test("live perspective melds detect and normalize the called sideways tile", async () => {
  const screenshot = "artifacts/live/south4-riichi-before-loss-20260928.jpg";
  const raw = JSON.parse(await readFile("config/layout.json", "utf8"));
  raw.publicTileRegions = { rightMelds: raw.publicTileRegions.rightMelds, oppositeMelds: raw.publicTileRegions.oppositeMelds };
  const layout = layoutSchema.parse(raw);
  const detection = await detectConfiguredPublicRegions(screenshot, layout);
  assert.deepEqual(detection.rightMelds?.candidates.map((tile) => tile.sideways), [true, false, false]);
  assert.deepEqual(detection.oppositeMelds?.candidates.map((tile) => tile.sideways), [false, true, false]);
  const result = await recognizeConfiguredPublicTilesWithVit(screenshot, layout, {
    classifyTileImages: async (images) => {
      let index = 0;
      for (const name of ["rightMelds", "oppositeMelds"] as const) {
        for (const tile of detection[name]!.candidates) {
          const rotation = (layout.publicTileRegions![name]!.rotationToUpright + (tile.sideways ? 90 : 0)) % 360;
          const expected = await sharp(screenshot).extract({ left: tile.x, top: tile.y, width: tile.width, height: tile.height })
            .rotate(rotation).png().toBuffer();
          assert.deepEqual(images[index++], expected);
        }
      }
      return ["S", "S", "S", "6s", "7s", "8s"].map((tile) => ({ tile: tile as any, confidence: 0.999, runnerUpTile: "1m" as const, runnerUpConfidence: 0.001 }));
    },
  });
  const observation = toPublicTileObservation(result);
  assert.equal(observation.opponentDiscards[0]?.melds?.[0]?.type, "pon");
  assert.equal(observation.opponentDiscards[1]?.melds?.[0]?.type, "chi");
  assert.equal(observation.allMeldTiles?.length, 6);
});

test("live opponent meld tiles reach remaining-copy counts without duplicating rivers", async () => {
  const replay = JSON.parse(await readFile("artifacts/live/south4-riichi-replay-20260928.json", "utf8"));
  const observation = toPublicTileObservation({
    rightMelds: publicRegion([{ tile: "S", x: 0 }, { tile: "S", x: 30 }, { tile: "S", x: 60 }]),
    oppositeMelds: publicRegion([{ tile: "6s", x: 0 }, { tile: "7s", x: 30 }, { tile: "8s", x: 60 }]),
  });
  const opponents = opponentStatesFromObservation(observation, replay.state.opponents)
    .map((opponent) => ({ ...opponent, discards: replay.state.opponents.find((item: any) => item.seat === opponent.seat).discards }));
  const updated = parseGameState({ ...replay.state, opponents });
  assert.equal(knownTiles(updated).filter((tile) => tile === "7s").length, 4);
  assert.equal(knownTilesOutsideHand(updated).filter((tile) => tile === "7s").length, 2);
  assert.equal(knownTiles(updated).filter((tile) => tile === "S").length, 4);
  assert.equal(updated.visibleTiles.length, 0);
  assert.throws(() => parseGameState({ ...updated, visibleTiles: ["7s"] }), /More than four/);
  assert.throws(() => parsePublicGameState({ ...updated, visibleTiles: ["S"] }), /More than four/);
});

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

test("invalid river geometry cannot promote riichi from a sideways candidate", () => {
  const invalid = publicRegion([{ tile: "5m", x: 0, width: 48, height: 30 }]);
  invalid.classificationSafe = false;
  assert.equal(hasSidewaysRiichiTile(invalid), false);
  const observation = toPublicTileObservation({ ownDiscards: invalid, rightDiscards: invalid });
  assert.equal(observation.ownRiichiDeclared, false);
  assert.equal(observation.opponentDiscards[0]?.riichiDeclared, false);
});

test("keeps calibrated dora indicators separate from other visible tiles", () => {
  const observation = toPublicTileObservation({
    doraIndicators: publicRegion([{ tile: "4s", x: 0 }]),
    ownDiscards: publicRegion([{ tile: "1m", x: 0 }]),
  });
  assert.deepEqual(observation.doraIndicators, ["4s"]);
  assert.equal(observation.acceptedTiles, 2);
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

test("adjacent exposed melds split by unique legal composition without a large gap", () => {
  const region = publicRegion([
    { tile: "6s", x: 0 }, { tile: "7s", x: 30 }, { tile: "8s", x: 60 },
    { tile: "E", x: 90 }, { tile: "E", x: 120 }, { tile: "E", x: 150 },
  ]);
  const melds = recognizeExposedMelds(region);
  assert.deepEqual(melds.map((meld) => meld.type), ["chi", "pon"]);
  assert.equal(toPublicTileObservation({ oppositeMelds: region }).opponentDiscards[1]?.meldsObserved, true);
  const kan = publicRegion([
    { tile: "3p", x: 0 }, { tile: "3p", x: 30 }, { tile: "3p", x: 60 }, { tile: "3p", x: 90 },
    { tile: "4s", x: 120 }, { tile: "5s", x: 150 }, { tile: "6s", x: 180 },
  ]);
  assert.deepEqual(recognizeExposedMelds(kan).map((meld) => meld.type), ["minkan", "chi"]);
  region.recognized[4]!.tile = "W";
  assert.equal(toPublicTileObservation({ oppositeMelds: region }).opponentDiscards[1]?.meldsObserved, false);
});
