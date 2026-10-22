import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { layoutSchema } from "../src/recognition/layout.js";
import { recognizeTileSlots } from "../src/recognition/templateMatcher.js";
import { confirmWeakOpenDraw, createOpenDrawVerifier, selectedTileRecognition } from "../src/recognition/openDrawEvidence.js";

test("selected evidence uses the physical tile rather than the weakest unrelated face", () => {
  const weak = { tile: "P" as const, confidence: 0, runnerUpConfidence: 0 };
  const west = { tile: "W" as const, confidence: 0.94569, runnerUpConfidence: 0.58348 };
  assert.deepEqual(selectedTileRecognition({ tiles: ["P", "W"], matches: [weak, west] }, 1), { ...west, index: 1 });
  assert.deepEqual(selectedTileRecognition({ tiles: ["P", "W"], matches: [west] }, 1), { ...west, index: 1 });
  assert.equal(selectedTileRecognition({ tiles: ["P", "W"], matches: [west] }, 0), undefined);
  assert.equal(selectedTileRecognition({ tiles: ["P", "E"], matches: [weak, west] }, 1), undefined);
});

test("weak distinct faces require strong same-identity normalized consensus", async () => {
  const nine = { index: 10, tile: "9p" as const, confidence: 0.7313, runnerUpConfidence: 0.3954 };
  const strong = { tile: "9p" as const, confidence: 0.9598, runnerUpConfidence: 0.3867 };
  assert.deepEqual((await confirmWeakOpenDraw(nine, async () => strong)).normalizedConsensus, strong);
  for (const rejected of [
    { ...strong, tile: "8p" as const }, { ...strong, confidence: 0.949 },
    { ...strong, runnerUpConfidence: 0.82 },
  ]) assert.equal((await confirmWeakOpenDraw(nine, async () => rejected)).normalizedConsensus, undefined);
  for (const raw of [
    { ...nine, confidence: 0.6036, runnerUpConfidence: 0.6008 },
    { ...nine, runnerUpConfidence: 0.65 }, { ...nine, confidence: 0.91 },
  ]) {
    let calls = 0;
    await confirmWeakOpenDraw(raw, async () => { calls++; return strong; });
    assert.equal(calls, 0);
  }
});

test("native compact W and separated9p retain tenpai choices; original bad8p crop stays guarded", { timeout: 60_000 }, async () => {
  const layout = layoutSchema.parse(JSON.parse(await readFile("config/layout-300-regression.json", "utf8")));
  const verify = await createOpenDrawVerifier("templates/bootstrap");
  assert.ok(verify);
  const provenance = JSON.parse(await readFile("test/fixtures/open-draw-20261022/provenance.json", "utf8"));
  for (const c of provenance.cases) {
    const file = `test/fixtures/open-draw-20261022/${c.name}.png`;
    const rect = { x: 0, y: 0, width: c.rect.width, height: c.rect.height };
    const raw = await recognizeTileSlots(file, [rect], layout, "templates/bootstrap");
    const selected = selectedTileRecognition(raw, 0)!;
    if (c.originalMisread) {
      assert.equal(selected.tile, c.originalMisread);
      assert.ok(selected.confidence < 0.7);
      let calls = 0;
      const evidence = await confirmWeakOpenDraw(selected, async () => { calls++; return verify(file, rect); });
      assert.equal(calls, 0);
      assert.equal(evidence.normalizedConsensus, undefined);
    } else {
      assert.equal(selected.tile, c.tile);
      const evidence = await confirmWeakOpenDraw(selected, () => verify(file, rect));
      if (c.tile === "9p") {
        assert.ok(selected.confidence < 0.8);
        assert.equal(evidence.normalizedConsensus?.tile, "9p");
        assert.ok(evidence.normalizedConsensus!.confidence >= 0.95);
      } else assert.ok(selected.confidence >= 0.8);
    }
  }
});
