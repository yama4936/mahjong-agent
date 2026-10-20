import assert from "node:assert/strict";
import test from "node:test";
import sharp from "sharp";
import { readFile } from "node:fs/promises";
import { classifyTile, loadTemplates, recognizeTileSlots } from "../src/recognition/templateMatcher.js";
import { layoutSchema } from "../src/recognition/layout.js";

test("shadowed white draw is not misclassified as eight man; remaining hand stays exact", async () => {
  const layout = layoutSchema.parse(JSON.parse(await readFile("config/layout-300-regression.json", "utf8")));
  const result = await recognizeTileSlots("test/fixtures/shadowed-white-draw-20261020.jpg",
    [...layout.handSlots, layout.drawSlot!], layout, "templates/bootstrap");
  assert.deepEqual(result.tiles, ["1m", "2m", "3m", "4m", "6m", "8m", "0p", "6p", "7p", "1s", "2s", "4s", "4s", "P"]);
  // The blank policy still refuses to certify blank/glare as a safe tile.
  assert.equal(result.matches.at(-1)!.confidence, 0);
  assert.equal(result.safe, false);
});

test("neutral lighting gradients retain the uncertain blank policy", async () => {
  const templates = await loadTemplates("templates/bootstrap", file => file.includes("__hf_base"));
  for (const diagonal of [false, true]) {
    const data = Buffer.alloc(44 * 64 * 3);
    for (let y = 0; y < 64; y++) for (let x = 0; x < 44; x++) {
      const level = diagonal ? (x + y > 55 ? 250 : 218) : Math.round(218 + 35 * y / 63);
      data.fill(level, (y * 44 + x) * 3, (y * 44 + x) * 3 + 3);
    }
    const tile = await sharp(data, { raw: { width: 44, height: 64, channels: 3 } }).png().toBuffer();
    const match = await classifyTile(tile, templates, { rejectBlank: true });
    assert.equal(match.tile, "P");
    assert.equal(match.confidence, 0);
  }
});
