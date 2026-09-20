import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import sharp from "sharp";
import { layoutSchema } from "../src/recognition/layout.js";
import { recognizeHand } from "../src/recognition/templateMatcher.js";
import { parseGameState } from "../src/game/state.js";
import { decide } from "../src/agent/decision.js";

test("screenshot recognition reaches a deterministic discard decision", { timeout: 60_000 }, async () => {
  const workspace = path.resolve(import.meta.dirname, "..");
  // This synthetic resized fixture was calibrated for raw matching. Face
  // normalization is checked separately below without relaxing its threshold.
  const layout = layoutSchema.parse({ ...JSON.parse(await readFile(path.join(workspace, "config/layout.example.json"), "utf8")), tileMatcher: "raw" });
  const tiles = ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E", "6p"];
  const slots = [...layout.handSlots, layout.drawSlot!];
  const composites = await Promise.all(tiles.map(async (tile, index) => {
    const slot = slots[index]!;
    const input = await sharp(path.join(workspace, "templates/bootstrap", `${tile}__hf_base.png`))
      .resize(slot.width, slot.height, { fit: "fill" })
      .png()
      .toBuffer();
    return { input, left: slot.x, top: slot.y };
  }));
  const directory = await mkdtemp(path.join(tmpdir(), "jantama-pipeline-"));
  const screenshot = path.join(directory, "frame.png");
  await sharp({
    create: { width: layout.viewport.width, height: layout.viewport.height, channels: 3, background: "#10151b" },
  }).composite(composites).png().toFile(screenshot);

  const recognition = await recognizeHand(screenshot, layout, path.join(workspace, "templates/bootstrap"));
  assert.deepEqual(recognition.tiles, tiles);
  assert.equal(recognition.turnReady, true);
  assert.equal(recognition.safe, true);
  const state = parseGameState({ hand: recognition.tiles.slice(0, 13), draw: recognition.tiles[13], recognitionConfidence: recognition.confidence });
  const decision = await decide(state, { mode: "advisor" });
  assert.equal(decision.tile, "E");
  assert.equal(decision.executable, false);
  const normalized = await recognizeHand(screenshot, { ...layout, tileMatcher: "face" }, path.join(workspace, "templates/bootstrap"));
  assert.deepEqual(normalized.tiles, tiles);
  assert.equal(normalized.safe, false);
  assert.ok(normalized.confidence < layout.minimumTileConfidence);
});

test("blank hand slots are rejected by the cheap presence gate", async () => {
  const workspace = path.resolve(import.meta.dirname, "..");
  const layout = layoutSchema.parse(JSON.parse(await readFile(path.join(workspace, "config/layout.example.json"), "utf8")));
  const blank = await sharp({ create: { width: 1920, height: 1080, channels: 3, background: "#050505" } }).png().toBuffer();
  const recognition = await recognizeHand(blank, layout, path.join(workspace, "templates/bootstrap"));
  assert.equal(recognition.safe, false);
  assert.equal(recognition.matches.length, 0);
  assert.equal(recognition.confidence, 0);
  assert.equal(recognition.turnReady, false);
});

test("a recognized 13-tile non-turn frame is not automation-safe", { timeout: 30_000 }, async () => {
  const workspace = path.resolve(import.meta.dirname, "..");
  const baseLayout = layoutSchema.parse(JSON.parse(await readFile(path.join(workspace, "config/layout.example.json"), "utf8")));
  const layout = layoutSchema.parse({ ...baseLayout, drawSlot: undefined });
  const tiles = ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"];
  const composites = await Promise.all(tiles.map(async (tile, index) => {
    const slot = layout.handSlots[index]!;
    return {
      input: await sharp(path.join(workspace, "templates/bootstrap", `${tile}__hf_base.png`)).resize(slot.width, slot.height, { fit: "fill" }).png().toBuffer(),
      left: slot.x,
      top: slot.y,
    };
  }));
  const screenshot = await sharp({
    create: { width: layout.viewport.width, height: layout.viewport.height, channels: 3, background: "#10151b" },
  }).composite(composites).png().toBuffer();
  const recognition = await recognizeHand(screenshot, layout, path.join(workspace, "templates/bootstrap"));
  assert.equal(recognition.tiles.length, 13);
  assert.equal(recognition.turnReady, false);
  assert.equal(recognition.safe, false);
});
