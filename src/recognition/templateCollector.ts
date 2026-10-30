import { appendFile, mkdir, open, readFile, unlink } from "node:fs/promises";
import { createHash, randomUUID } from "node:crypto";
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
  // Validate the entire request before launching any concurrent crop. An
  // invalid later label or rectangle used to reject Promise.all while earlier
  // crops kept writing unmanifested images into the active template bank.
  const tiles = labels.map(parseGameTile);
  const source = await readFile(screenshot);
  const metadata = await sharp(source).metadata();
  if (!metadata.width || !metadata.height) throw new Error("Could not determine source image dimensions");
  for (const [index, slot] of slots.entries()) {
    if (![slot.x, slot.y, slot.width, slot.height].every(Number.isInteger)
      || slot.x < 0 || slot.y < 0 || slot.width <= 0 || slot.height <= 0
      || slot.x + slot.width > metadata.width || slot.y + slot.height > metadata.height) {
      throw new Error(`Template slot ${index} is outside the source image`);
    }
  }
  // Encode all crops before publishing any file. This prevents a corrupt
  // source from leaving earlier crops in a live template directory.
  const crops = await Promise.all(slots.map(slot => sharp(source)
    .extract({ left: slot.x, top: slot.y, width: slot.width, height: slot.height })
    .png().toBuffer()));
  await mkdir(outputDirectory, { recursive: true });
  const stamp = `${Date.now().toString(36)}_${randomUUID()}`;
  const sourceHash = createHash("sha256").update(source).digest("hex");
  const outputs = slots.map((slot, index) => {
    const tile = tiles[index]!;
    const output = path.join(outputDirectory, `${tile}__${split}_${stamp}_${String(index).padStart(2, "0")}.png`);
    return { output, tile, slot, index };
  });
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
  const published: string[] = [];
  try {
    for (const { output, index } of outputs) {
      const file = await open(output, "wx");
      published.push(output);
      try { await file.writeFile(crops[index]!); } finally { await file.close(); }
    }
    await appendFile(path.join(outputDirectory, "manifest.jsonl"), manifest, "utf8");
  } catch (error) {
    // Never remove pre-existing files. If cleanup fails, surface that failure
    // explicitly rather than implying the directory is clean.
    const cleanup = await Promise.allSettled(published.map(output => unlink(output)));
    const failures = cleanup.filter(result => result.status === "rejected");
    if (failures.length) throw new AggregateError([error, ...failures.map(result => (result as PromiseRejectedResult).reason)], "Template publication and cleanup failed");
    throw error;
  }
  return outputs.map(({ output }) => output);
}
