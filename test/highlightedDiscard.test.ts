import assert from "node:assert/strict";
import test from "node:test";
import { recognizeHighlightedDiscard } from "../src/recognition/highlightedDiscard.js";
import { detectConfiguredPublicRegions } from "../src/recognition/regionDetector.js";
import { layoutSchema } from "../src/recognition/layout.js";
import type { PublicTileRecognitionRegion } from "../src/recognition/publicTileRecognizer.js";

const layout = layoutSchema.parse({
  viewport: { width: 1920, height: 1080 },
  handSlots: Array.from({ length: 13 }, (_, i) => ({ x: i * 10, y: 900, width: 8, height: 30 })),
  clickPoints: Array.from({ length: 13 }, (_, i) => ({ x: i * 10 + 4, y: 915 })),
  publicTileRegions: {
    leftDiscards: { x: 500, y: 285, width: 305, height: 250, rotationToUpright: 270, detectionMode: "discard_grid" },
  },
});

test("prompt highlight must dominate on a safe final discard and rotates seats", async () => {
  for (const [file, expected] of [["highlight-merged-left-river-20260928.png", "4p"],
    ["pass-before-self-riichi-20260928.png", "2s"]] as const) {
    const frame = `artifacts/live/${file}`;
    const detected = (await detectConfiguredPublicRegions(frame, layout, { luminanceThreshold: 190 })).leftDiscards!;
    const region: PublicTileRecognitionRegion = {
      backend: "hybrid", candidateCount: detected.candidates.length,
      rotationToUpright: 270, classificationSafe: detected.gridValid === true,
      recognized: detected.candidates.map((c, i) => ({ ...c, tile: i === detected.candidates.length - 1 ? expected : "P",
        safe: true, confidence: 1, runnerUpConfidence: 0, ambiguityMargin: 1 })),
    };
    assert.deepEqual(await recognizeHighlightedDiscard(frame, { leftDiscards: region }, "north"),
      { tile: expected, fromSeat: "west" });
    assert.equal(await recognizeHighlightedDiscard(frame, { leftDiscards: { ...region, classificationSafe: false } }), undefined);
    assert.equal(await recognizeHighlightedDiscard(frame,
      { leftDiscards: { ...region, recognized: region.recognized.slice(0, -1) } }), undefined);
    assert.equal(await recognizeHighlightedDiscard("artifacts/live/pass-to-self-riichi-20260928.png",
      { leftDiscards: region }), undefined);
  }
});

test("target triangle disambiguates a border spilling onto the previous right discard", async () => {
  const rightLayout = { ...layout, publicTileRegions: {
    rightDiscards: { x: 1115, y: 285, width: 305, height: 250, rotationToUpright: 90 as const,
      detectionMode: "discard_grid" as const },
  } };
  const frame = "artifacts/live/right-pon-highlight-spill-20260928.png";
  const detected = (await detectConfiguredPublicRegions(frame, rightLayout, { luminanceThreshold: 190 })).rightDiscards!;
  const region: PublicTileRecognitionRegion = {
    backend: "hybrid", candidateCount: detected.candidates.length, rotationToUpright: 90,
    classificationSafe: detected.gridValid === true,
    recognized: detected.candidates.map((c, i) => ({ ...c, tile: i === detected.candidates.length - 1 ? "2m" : "P",
      safe: true, confidence: 1, runnerUpConfidence: 0, ambiguityMargin: 1 })),
  };
  assert.deepEqual(await recognizeHighlightedDiscard(frame, { rightDiscards: region }, "west"),
    { tile: "2m", fromSeat: "north" });
  assert.equal(await recognizeHighlightedDiscard(frame, { rightDiscards: { ...region, classificationSafe: false } }, "west"), undefined);
  assert.equal(await recognizeHighlightedDiscard(frame,
    { rightDiscards: { ...region, recognized: region.recognized.slice(0, -1) } }, "west"), undefined);
});
