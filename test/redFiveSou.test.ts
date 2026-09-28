import assert from "node:assert/strict";
import test from "node:test";
import sharp from "sharp";
import { redFiveSouEvidence } from "../src/recognition/redFiveSou.js";

async function evidence(image: string, left: number, top: number, width: number, height: number) {
  const rgb = await sharp(image).extract({ left, top, width, height })
    .resize(44, 64, { fit: "fill" }).removeAlpha().toColourspace("srgb").raw().toBuffer();
  return redFiveSouEvidence(rgb);
}

test("central bamboo distinguishes visually labelled ordinary and red five sou renderings", async () => {
  // Labels are from the visible glyphs, not bootstrap filenames or model output.
  const prompt = "artifacts/live/green-dragon-pon-missed-after-called-river-removal-20260928.png";
  assert.equal((await evidence(prompt, 600, 923, 95, 149)).supportsRed, true);
  assert.equal((await evidence(prompt, 695, 923, 95, 149)).supportsRed, false);
  const live = await evidence("artifacts/live/red-five-sou-read-normal-in-fixed-regression-20260928.jpg",
    1266, 926, 93, 146);
  assert.deepEqual(live, { red: 161, green: 0, supportsRed: true });
  const fullRed = await evidence("artifacts/live/left-melds-chi-pon-20260928.jpg", 982, 926, 92, 146);
  assert.equal(fullRed.supportsRed, true);
});

test("blank evidence and malformed pixel buffers cannot support red five sou", () => {
  assert.equal(redFiveSouEvidence(new Uint8Array(44 * 64 * 3).fill(240)).supportsRed, false);
  assert.throws(() => redFiveSouEvidence(new Uint8Array(44 * 64 * 4)), /44x64 RGB/);
});
