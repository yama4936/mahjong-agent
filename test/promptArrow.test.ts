import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { countPromptArrowOutsideFaces } from "../src/recognition/promptArrow.js";
import { detectConfiguredPublicRegions } from "../src/recognition/regionDetector.js";
import { layoutSchema } from "../src/recognition/layout.js";

test("real right dragon arrow survives while neighboring bamboo glyphs are excluded", async () => {
  const frame = "artifacts/live/right-green-dragon-pon-rejected-fixed-e66ef28-20260928.png";
  const layout = layoutSchema.parse(JSON.parse(await readFile("config/layout-300-regression.json", "utf8")));
  const regions = await detectConfiguredPublicRegions(frame, layout, { luminanceThreshold: 190 });
  const river = regions.rightDiscards!;
  assert.equal(river.gridValid, true);
  assert.equal(river.candidates.length, 12);
  const faces = Object.entries(regions).filter(([name]) => name.endsWith("Discards"))
    .flatMap(([, region]) => region!.candidates);
  assert.equal(await countPromptArrowOutsideFaces(frame, river.candidates[8]!, []), 164);
  assert.equal(await countPromptArrowOutsideFaces(frame, river.candidates[8]!, faces), 0);
  assert.equal(await countPromptArrowOutsideFaces(frame, river.candidates[11]!, faces), 208);
});

test("arrow evidence outside screenshot bounds is absent", async () => {
  assert.equal(await countPromptArrowOutsideFaces(
    "artifacts/live/right-green-dragon-pon-rejected-fixed-e66ef28-20260928.png",
    { x: 0, y: 0, width: 10, height: 10 }, []), 0);
});

test("face masking preserves the older right-spill triangle and does not invent an absent left arrow", async () => {
  const layout = layoutSchema.parse(JSON.parse(await readFile("config/layout-300-regression.json", "utf8")));
  for (const [file, threshold, name, expectedLast] of [
    ["right-pon-highlight-spill-20260928.png", 190, "rightDiscards", 302],
    ["green-dragon-pon-missed-after-called-river-removal-20260928.png", 200, "leftDiscards", 0],
  ] as const) {
    const frame = `artifacts/live/${file}`;
    const regions = await detectConfiguredPublicRegions(frame, layout, { luminanceThreshold: threshold });
    const faces = Object.entries(regions).filter(([key]) => key.endsWith("Discards"))
      .flatMap(([, region]) => region!.candidates);
    const counts = await Promise.all(regions[name]!.candidates.map(tile =>
      countPromptArrowOutsideFaces(frame, tile, faces)));
    assert.equal(counts.at(-1), expectedLast);
    assert.ok(counts.slice(0, -1).every(count => count === 0));
    // Zero arrow evidence must leave border fallback to the caller; it does
    // not imply a highlighted-discard decision is forbidden or authorized.
  }
});
