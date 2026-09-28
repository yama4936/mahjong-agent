import assert from "node:assert/strict";
import test from "node:test";
import sharp from "sharp";
import { existsSync } from "node:fs";
import { HybridTileRecognizer } from "../src/recognition/hybridTileRecognizer.js";
import { rectifyTileFace } from "../src/recognition/rectifyTileFace.js";

test("annotated perspective face preserves the real three-man identity in both models", {
  skip: !existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar") || !existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt"),
}, async () => {
  const frame = "artifacts/live/own-three-melds-two-man-read-eight-man-20260928.jpg";
  // Manually measured corners: this does not test automatic face localization.
  const face = await rectifyTileFace(frame, [{ x: 1739, y: 948 }, { x: 1801, y: 948 },
    { x: 1821, y: 1019 }, { x: 1753, y: 1019 }]);
  const recognizer = new HybridTileRecognizer();
  try {
    const [prediction] = await recognizer.classifyTileImages([face]);
    assert.equal(prediction?.tile, "3m");
    assert.equal(prediction?.normalPrediction.tile, "3m");
    assert.equal(prediction?.redPrediction.label, "3m");
    assert.ok((prediction?.confidence ?? 0) > 0.9);
  } finally { await recognizer.close(); }
});

test("rectangular face rectification preserves pixel identity", async () => {
  const pixels = Buffer.from(Array.from({ length: 8 * 10 * 3 }, (_, i) => i % 256));
  const source = await sharp(pixels, { raw: { width: 8, height: 10, channels: 3 } }).png().toBuffer();
  const output = await rectifyTileFace(source, [{ x: 0, y: 0 }, { x: 7, y: 0 },
    { x: 7, y: 9 }, { x: 0, y: 9 }], 8, 10);
  assert.deepEqual(await sharp(output).raw().toBuffer(), pixels);
});

test("perspective quad maps all four source corners to output corners", async () => {
  const pixels = Buffer.alloc(20 * 20 * 3);
  const corners = [{ x: 5, y: 2 }, { x: 17, y: 4 }, { x: 15, y: 18 }, { x: 2, y: 15 }];
  corners.forEach((p, i) => pixels.fill(40 + i * 50, (p.y * 20 + p.x) * 3, (p.y * 20 + p.x) * 3 + 3));
  const source = await sharp(pixels, { raw: { width: 20, height: 20, channels: 3 } }).png().toBuffer();
  const output = await sharp(await rectifyTileFace(source, corners, 8, 10)).raw().toBuffer();
  [0, 7, 79, 72].forEach((offset, i) => assert.equal(output[offset * 3], 40 + i * 50));
});

test("invalid or reversed faces cannot produce a recognized image", async () => {
  const source = await sharp({ create: { width: 20, height: 20, channels: 3, background: "white" } }).png().toBuffer();
  for (const corners of [[], [{ x: 0, y: 0 }, { x: 10, y: 10 }, { x: 10, y: 0 }, { x: 0, y: 10 }],
    [{ x: -1, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }, { x: 0, y: 10 }]]) {
    await assert.rejects(rectifyTileFace(source, corners));
  }
});
