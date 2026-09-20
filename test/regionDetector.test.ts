import assert from "node:assert/strict";
import test from "node:test";
import sharp from "sharp";
import { detectBrightTileCandidates, detectConfiguredPublicRegions, orderDiscardGridCandidates, type RegionCandidate } from "../src/recognition/regionDetector.js";
import { layoutSchema } from "../src/recognition/layout.js";

test("detects bright connected components only inside the calibrated region", async () => {
  const screenshot = await sharp({
    create: { width: 300, height: 180, channels: 3, background: "#111820" },
  }).composite([
    { input: { create: { width: 30, height: 46, channels: 3, background: "#f5f1df" } }, left: 70, top: 50 },
    { input: { create: { width: 28, height: 44, channels: 3, background: "#eee9d7" } }, left: 110, top: 52 },
    { input: { create: { width: 40, height: 50, channels: 3, background: "#ffffff" } }, left: 230, top: 20 },
  ]).png().toBuffer();
  const result = await detectBrightTileCandidates(screenshot, { x: 50, y: 30, width: 120, height: 90 });
  assert.deepEqual(result.candidates.map(({ x, y, width, height }) => ({ x, y, width, height })), [
    { x: 70, y: 50, width: 30, height: 46 },
    { x: 110, y: 52, width: 28, height: 44 },
  ]);
});

test("detects all configured public regions without inventing missing ones", async () => {
  const screenshot = await sharp({
    create: { width: 300, height: 180, channels: 3, background: "#101010" },
  }).composite([
    { input: { create: { width: 24, height: 36, channels: 3, background: "#eeeeee" } }, left: 20, top: 20 },
    { input: { create: { width: 24, height: 36, channels: 3, background: "#eeeeee" } }, left: 180, top: 100 },
  ]).png().toBuffer();
  const layout = layoutSchema.parse({
    viewport: { width: 300, height: 180 },
    handSlots: Array.from({ length: 13 }, (_, index) => ({ x: index * 10, y: 140, width: 8, height: 30 })),
    clickPoints: Array.from({ length: 13 }, (_, index) => ({ x: index * 10 + 4, y: 155 })),
    publicTileRegions: {
      leftDiscards: { x: 0, y: 0, width: 80, height: 80 },
      ownDiscards: { x: 150, y: 80, width: 100, height: 80 },
    },
  });
  const result = await detectConfiguredPublicRegions(screenshot, layout);
  assert.equal(result.leftDiscards?.candidates.length, 1);
  assert.equal(result.ownDiscards?.candidates.length, 1);
  assert.equal(result.rightDiscards, undefined);
});

test("rejects bright UI panels that are too large to be tiles", async () => {
  const screenshot = await sharp({
    create: { width: 300, height: 180, channels: 3, background: "#111111" },
  }).composite([
    { input: { create: { width: 90, height: 150, channels: 3, background: "#ffffff" } }, left: 20, top: 10 },
    { input: { create: { width: 250, height: 25, channels: 3, background: "#ffffff" } }, left: 25, top: 100 },
  ]).png().toBuffer();
  const result = await detectBrightTileCandidates(screenshot, { x: 0, y: 0, width: 300, height: 180 });
  assert.equal(result.candidates.length, 0);
});

test("orders perspective-jittered discards as a six-column grid", () => {
  const candidate = (x: number, y: number, id: number, width = 30, height = 46): RegionCandidate => ({
    x, y, width, height, area: id, fillRatio: 0.8,
  });
  const shuffled = [
    candidate(50, 72, 8), candidate(10, 10, 1), candidate(90, 8, 3), candidate(170, 11, 5),
    candidate(10, 70, 7), candidate(210, 9, 6), candidate(130, 12, 4), candidate(50, 7, 2),
  ];
  const result = orderDiscardGridCandidates(shuffled, {
    x: 0, y: 0, width: 260, height: 160, rotationToUpright: 0, detectionMode: "discard_grid",
  });
  assert.deepEqual(result.candidates.map((item) => item.area), [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.deepEqual(result.gridRows, [6, 2]);
  assert.equal(result.gridValid, true);
  assert.deepEqual(result.candidates.map((item) => item.gridIndex), [0, 1, 2, 3, 4, 5, 6, 7]);
});

test("normalizes the opposite player's grid before assigning discard order", () => {
  const candidates: RegionCandidate[] = [
    { x: 210, y: 120, width: 30, height: 46, area: 1, fillRatio: 0.8 },
    { x: 170, y: 121, width: 30, height: 46, area: 2, fillRatio: 0.8 },
    { x: 130, y: 119, width: 30, height: 46, area: 3, fillRatio: 0.8 },
    { x: 90, y: 120, width: 30, height: 46, area: 4, fillRatio: 0.8 },
    { x: 50, y: 121, width: 30, height: 46, area: 5, fillRatio: 0.8 },
    { x: 10, y: 119, width: 30, height: 46, area: 6, fillRatio: 0.8 },
  ];
  const result = orderDiscardGridCandidates(candidates.reverse(), {
    x: 0, y: 0, width: 260, height: 200, rotationToUpright: 180, detectionMode: "discard_grid",
  });
  assert.deepEqual(result.candidates.map((item) => item.area), [1, 2, 3, 4, 5, 6]);
  assert.equal(result.gridValid, true);
});

test("rejects a river whose earlier grid row is incomplete", () => {
  const candidates: RegionCandidate[] = [
    { x: 10, y: 10, width: 30, height: 46, area: 1, fillRatio: 0.8 },
    { x: 50, y: 10, width: 30, height: 46, area: 2, fillRatio: 0.8 },
    { x: 10, y: 70, width: 30, height: 46, area: 3, fillRatio: 0.8 },
  ];
  const result = orderDiscardGridCandidates(candidates, {
    x: 0, y: 0, width: 260, height: 160, rotationToUpright: 0, detectionMode: "discard_grid",
  });
  assert.deepEqual(result.gridRows, [2, 1]);
  assert.equal(result.gridValid, false);
});

test("infers a partially filled third row when perspective overlap merges its faces", async () => {
  const tiles = [];
  for (const y of [10, 70]) {
    for (let column = 0; column < 6; column += 1) {
      tiles.push({ input: { create: { width: 30, height: 46, channels: 3 as const, background: "#f4f0df" } }, left: 10 + column * 40, top: y });
    }
  }
  for (let column = 0; column < 5; column += 1) {
    tiles.push({ input: { create: { width: 30, height: 46, channels: 3 as const, background: "#f4f0df" } }, left: 10 + column * 40, top: 130 });
    if (column < 4) tiles.push({ input: { create: { width: 10, height: 4, channels: 3 as const, background: "#f4f0df" } }, left: 40 + column * 40, top: 150 });
  }
  const screenshot = await sharp({ create: { width: 270, height: 190, channels: 3, background: "#102820" } })
    .composite(tiles)
    .png()
    .toBuffer();
  const layout = layoutSchema.parse({
    viewport: { width: 270, height: 190 },
    handSlots: Array.from({ length: 13 }, (_, index) => ({ x: index, y: 0, width: 1, height: 1 })),
    clickPoints: Array.from({ length: 13 }, (_, index) => ({ x: index, y: 0 })),
    publicTileRegions: {
      ownDiscards: { x: 0, y: 0, width: 260, height: 190, detectionMode: "discard_grid" },
    },
  });
  const detection = (await detectConfiguredPublicRegions(screenshot, layout, {
    minimumArea: 100,
    minimumWidth: 8,
    minimumHeight: 12,
    maximumWidth: 50,
    maximumHeight: 60,
  })).ownDiscards;
  assert.equal(detection?.candidates.length, 17);
  assert.deepEqual(detection?.gridRows, [6, 6, 5]);
  assert.equal(detection?.gridValid, true);
});
