import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import sharp from "sharp";
import { availableUiActions, recognizeActionButtons } from "../src/recognition/actionButtonRecognizer.js";
import { layoutSchema } from "../src/recognition/layout.js";

test("action buttons are exposed only by calibrated regions and matching templates", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "jantama-actions-"));
  const button = await sharp({ create: { width: 120, height: 50, channels: 3, background: "#d19b42" } })
    .composite([{ input: Buffer.from('<svg width="120" height="50"><text x="30" y="34" font-size="25">RON</text></svg>'), left: 0, top: 0 }])
    .png().toBuffer();
  await writeFile(path.join(directory, "ron.png"), button);
  const screenshot = await sharp({ create: { width: 400, height: 200, channels: 3, background: "#102030" } })
    .composite([{ input: button, left: 240, top: 120 }]).png().toBuffer();
  const layout = layoutSchema.parse({
    viewport: { width: 400, height: 200 },
    handSlots: Array.from({ length: 13 }, (_, index) => ({ x: index, y: 0, width: 1, height: 1 })),
    clickPoints: Array.from({ length: 13 }, (_, index) => ({ x: index, y: 0 })),
    actionButtonRegions: {
      ron: { x: 240, y: 120, width: 120, height: 50 },
      pon: { x: 100, y: 120, width: 120, height: 50 },
    },
  });
  const matches = await recognizeActionButtons(screenshot, layout, directory);
  assert.deepEqual(availableUiActions(matches), ["ron"]);
  assert.equal(matches[0]?.confidence, 1);
  assert.deepEqual(matches[0]?.center, { x: 300, y: 145 });
});
