import { createHash } from "node:crypto";
import { appendFile, mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import sharp from "sharp";
import { parseGameTile } from "../src/game/tiles.js";

const [sourceArgument, labelsArgument, outputArgument = "templates/live-verified"] = process.argv.slice(2);
const splitArgument = process.argv.find((argument) => argument.startsWith("--split="))?.slice(8) ?? "train";

if (!sourceArgument || !labelsArgument) {
  throw new Error("Usage: import-labeled-row <image> <comma-separated tiles> [output] [--split=train|holdout]");
}
if (splitArgument !== "train" && splitArgument !== "holdout") {
  throw new Error(`Invalid template split: ${splitArgument}`);
}

const labels = labelsArgument.split(",").map((label) => parseGameTile(label.trim()));
if (labels.length !== 13 && labels.length !== 14) {
  throw new Error(`Expected 13 or 14 labels, got ${labels.length}`);
}

const source = path.resolve(sourceArgument);
const outputDirectory = path.resolve(outputArgument);
const sourceBytes = await readFile(source);
const sourceSha256 = createHash("sha256").update(sourceBytes).digest("hex");
const metadata = await sharp(sourceBytes).metadata();
if (!metadata.width || !metadata.height) throw new Error("Could not determine source image dimensions");

await mkdir(outputDirectory, { recursive: true });
const stamp = `${Date.now().toString(36)}_${sourceSha256.slice(0, 8)}`;
const manifestRows: string[] = [];
const outputs: string[] = [];

for (let index = 0; index < labels.length; index += 1) {
  // The input is a tightly cropped, uniformly spaced row. Rounding both edges
  // independently avoids accumulating fractional-width error across the row.
  const left = Math.round(index * metadata.width / labels.length);
  const right = Math.round((index + 1) * metadata.width / labels.length);
  const slot = { x: left, y: 0, width: right - left, height: metadata.height };
  const tile = labels[index]!;
  const crop = `${tile}__${splitArgument}_${stamp}_${String(index).padStart(2, "0")}.png`;
  const output = path.join(outputDirectory, crop);
  await sharp(sourceBytes).extract({ left: slot.x, top: slot.y, width: slot.width, height: slot.height }).png().toFile(output);
  outputs.push(output);
  manifestRows.push(JSON.stringify({
    schemaVersion: 1,
    crop,
    label: tile,
    split: splitArgument,
    sourceKind: "labeled-hand-row",
    sourceScreenshot: source,
    sourceSha256,
    slotIndex: index,
    slot,
    collectedAt: new Date().toISOString(),
  }));
}

await appendFile(path.join(outputDirectory, "manifest.jsonl"), `${manifestRows.join("\n")}\n`, "utf8");
console.log(JSON.stringify({ source, sourceSha256, split: splitArgument, labels, outputs }, null, 2));
