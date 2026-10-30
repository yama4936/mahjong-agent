import assert from "node:assert/strict";
import test from "node:test";
import { mkdir, mkdtemp, readFile, readdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import sharp from "sharp";
import { layoutSchema } from "../src/recognition/layout.js";
import { collectHandTemplates } from "../src/recognition/templateCollector.js";

async function setup() {
  const dir = await mkdtemp(path.join(tmpdir(), "collector-preflight-"));
  const screenshot = path.join(dir, "frame.png");
  await sharp({ create: { width: 1920, height: 1080, channels: 3, background: "white" } }).png().toFile(screenshot);
  const layout = layoutSchema.parse(JSON.parse(await readFile("config/layout-runtime.json", "utf8")));
  const output = path.join(dir, "output");
  return { screenshot, layout, output };
}

test("invalid later label does not leave earlier unmanifested training images", async () => {
  const { screenshot, layout, output } = await setup();
  const labels = Array(layout.handSlots.length).fill("1p");
  labels[labels.length - 1] = "invalid";
  await assert.rejects(collectHandTemplates(screenshot, layout, labels, output));
  await new Promise(resolve => setTimeout(resolve, 100));
  assert.deepEqual(await readdir(output).catch(() => []), []);
});

test("a later crop outside the frame does not leave earlier unmanifested images", async () => {
  const { screenshot, layout, output } = await setup();
  const badLayout = { ...layout, handSlots: layout.handSlots.map((slot, i) => i === layout.handSlots.length - 1 ? { ...slot, x: 1900 } : slot) };
  await assert.rejects(collectHandTemplates(screenshot, badLayout, Array(layout.handSlots.length).fill("1p"), output));
  await new Promise(resolve => setTimeout(resolve, 100));
  assert.deepEqual(await readdir(output).catch(() => []), []);
});

test("valid collection records every crop against the source image", async () => {
  const { screenshot, layout, output } = await setup();
  const labels = Array(layout.handSlots.length).fill("1p");
  const files = await collectHandTemplates(screenshot, layout, labels, output);
  assert.equal(files.length, labels.length);
  const records = (await readFile(path.join(output, "manifest.jsonl"), "utf8")).trim().split("\n").map(line => JSON.parse(line));
  assert.equal(records.length, labels.length);
  assert.deepEqual(records.map(row => row.slotIndex), labels.map((_, index) => index));
  assert.ok(records.every(row => row.label === "1p" && row.sourceScreenshot === screenshot && /^[a-f0-9]{64}$/.test(row.sourceSha256)));
  assert.deepEqual(records.map(row => path.join(output, row.crop)), files);
});

test("manifest publication failure removes newly written crops but preserves existing files", async () => {
  const { screenshot, layout, output } = await setup();
  await mkdir(output);
  await writeFile(path.join(output, "existing.png"), "unchanged");
  await mkdir(path.join(output, "manifest.jsonl"));
  await assert.rejects(collectHandTemplates(screenshot, layout, Array(layout.handSlots.length).fill("1p"), output));
  assert.deepEqual((await readdir(output)).sort(), ["existing.png", "manifest.jsonl"]);
  assert.equal(await readFile(path.join(output, "existing.png"), "utf8"), "unchanged");
});

test("unreadable image data does not publish any crops", async () => {
  const { screenshot, layout, output } = await setup();
  const image = await readFile(screenshot);
  // The PNG header retains its dimensions, but image data is truncated.
  await writeFile(screenshot, image.subarray(0, 40));
  await assert.rejects(collectHandTemplates(screenshot, layout, Array(layout.handSlots.length).fill("1p"), output));
  assert.deepEqual(await readdir(output).catch(() => []), []);
});
