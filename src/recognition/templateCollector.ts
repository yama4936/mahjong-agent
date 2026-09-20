import { appendFile, mkdir, readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";
import sharp from "sharp";
import type { ScreenLayout } from "./layout.js";
import { parseGameTile } from "../game/tiles.js";

export async function collectHandTemplates(
  screenshot: string,
  layout: ScreenLayout,
  labels: readonly string[],
  outputDirectory: string,
  split: "train" | "holdout" = "train",
): Promise<string[]> {
  const turnSlots = layout.drawSlot ? [...layout.handSlots, layout.drawSlot] : layout.handSlots;
  const slots = labels.length === layout.handSlots.length ? layout.handSlots : turnSlots;
  if (labels.length !== slots.length) {
    throw new Error(`Expected ${layout.handSlots.length} post-action labels or ${turnSlots.length} turn labels, got ${labels.length}`);
  }
  await mkdir(outputDirectory, { recursive: true });
  const stamp = Date.now().toString(36);
  const sourceHash = createHash("sha256").update(await readFile(screenshot)).digest("hex");
  const outputs = await Promise.all(slots.map(async (slot, index) => {
    const tile = parseGameTile(labels[index]!);
    const output = path.join(outputDirectory, `${tile}__${split}_${stamp}_${String(index).padStart(2, "0")}.png`);
    await sharp(screenshot)
      .extract({ left: slot.x, top: slot.y, width: slot.width, height: slot.height })
      .png()
      .toFile(output);
    return { output, tile, slot, index };
  }));
  const manifest = outputs.map(({ output, tile, slot, index }) => JSON.stringify({
    schemaVersion: 1,
    crop: path.basename(output),
    label: tile,
    split,
    sourceScreenshot: path.resolve(screenshot),
    sourceSha256: sourceHash,
    layoutViewport: layout.viewport,
    slotIndex: index,
    slot,
    collectedAt: new Date().toISOString(),
  })).join("\n") + "\n";
  await appendFile(path.join(outputDirectory, "manifest.jsonl"), manifest, "utf8");
  return outputs.map(({ output }) => output);
}
