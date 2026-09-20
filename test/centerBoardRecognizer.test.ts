import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import sharp from "sharp";
import { CenterBoardConsensus, recognizeCenterBoard } from "../src/recognition/centerBoardRecognizer.js";
import { layoutSchema } from "../src/recognition/layout.js";

const fieldNames = [
  "round", "honba", "riichiSticks", "remainingTiles", "ownSeat",
  "ownScore", "rightScore", "oppositeScore", "leftScore",
] as const;

const layout = layoutSchema.parse({
  viewport: { width: 900, height: 100 },
  handSlots: Array.from({ length: 13 }, (_, index) => ({ x: index, y: 0, width: 1, height: 1 })),
  clickPoints: Array.from({ length: 13 }, (_, index) => ({ x: index, y: 0 })),
  centerBoardRegions: Object.fromEntries(fieldNames.map((field, index) => [field, { x: index * 100, y: 0, width: 100, height: 100 }])),
});

function frame(labels: string[]): Buffer {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="900" height="100">
    <rect width="900" height="100" fill="#101820"/>
    ${labels.map((label, index) => `<g transform="translate(${index * 100},0)"><rect x="3" y="3" width="94" height="94" rx="8" fill="#202a38" stroke="#d8ad52"/><text x="50" y="59" text-anchor="middle" font-family="sans-serif" font-size="24" fill="#71e5da">${label}</text></g>`).join("")}
  </svg>`;
  return Buffer.from(svg);
}

test("center-board references recognize a complete structured state but remain untrusted", async () => {
  const directory = await mkdtemp(path.join(tmpdir(), "jantama-center-"));
  const first = path.join(directory, "first.png");
  const second = path.join(directory, "second.png");
  await sharp(frame(["E1", "0", "0", "47", "E", "250", "251", "252", "247"])).png().toFile(first);
  await sharp(frame(["E2", "1", "1", "32", "S", "310", "220", "240", "230"])).png().toFile(second);
  const manifest = path.join(directory, "manifest.json");
  await writeFile(manifest, JSON.stringify({
    schemaVersion: 1,
    viewport: layout.viewport,
    samples: [
      { screenshot: "first.png", round: "east_1", honba: 0, riichiSticks: 0, remainingTiles: 47, ownSeat: "east", scores: { east: 25000, south: 25100, west: 25200, north: 24700 } },
      { screenshot: "second.png", round: "east_2", honba: 1, riichiSticks: 1, remainingTiles: 32, ownSeat: "south", scores: { east: 23000, south: 31000, west: 22000, north: 24000 } },
    ],
  }));
  const result = await recognizeCenterBoard(first, layout, manifest, { minimumMargin: 0.001 });
  assert.equal(result.complete, true);
  assert.equal(result.trusted, false);
  assert.equal(result.round, "east_1");
  assert.equal(result.remainingTiles, 47);
  assert.equal(result.ownSeat, "east");
  assert.deepEqual(result.scores, { east: 25000, south: 25100, west: 25200, north: 24700 });
  assert.deepEqual(result.safetyReasons, ["center_board_independent_calibration_missing"]);
});

test("center-board consensus requires identical complete observations", async () => {
  const consensus = new CenterBoardConsensus(3);
  const observation = {
    round: "east_1", honba: 0, riichiSticks: 0, remainingTiles: 47, ownSeat: "east" as const,
    scores: { east: 25000, south: 25000, west: 25000, north: 25000 }, fields: {} as never,
    confidence: 1, complete: true, trusted: false as const, safetyReasons: ["uncalibrated"], referenceSetFingerprint: "a",
    consistencyErrors: [],
  };
  assert.equal(consensus.observe(observation), undefined);
  assert.equal(consensus.observe(observation), undefined);
  assert.equal(consensus.observe(observation), observation);
  assert.equal(consensus.observe({ ...observation, remainingTiles: 46 }), undefined);
});
