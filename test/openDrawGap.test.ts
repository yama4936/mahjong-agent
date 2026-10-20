import assert from "node:assert/strict";
import test from "node:test";
import sharp from "sharp";
import { readFile } from "node:fs/promises";
import { layoutSchema } from "../src/recognition/layout.js";
import { calibratedOpenHandProposal, resolveOpenDrawGap } from "../src/recognition/handLayoutProposal.js";
import { recognizeTileSlots } from "../src/recognition/templateMatcher.js";

async function layout() {
  return layoutSchema.parse(JSON.parse(await readFile("config/layout-300-regression.json", "utf8")));
}

test("separated open draw recognizes six sou instead of one man with a matching click center", async () => {
  const base = await layout();
  const original = calibratedOpenHandProposal(base, 1);
  const frame = "test/fixtures/open-gapped-six-sou-20261020.jpg";
  const proposal = await resolveOpenDrawGap(frame, base, original);
  assert.equal(proposal.drawSlot.x, original.drawSlot.x + 30);
  assert.deepEqual(proposal.handSlots, original.handSlots);
  assert.deepEqual(proposal.clickPoints.slice(0, -1), original.clickPoints.slice(0, -1));
  assert.equal(proposal.clickPoints.at(-1)!.x, proposal.drawSlot.x + proposal.drawSlot.width / 2);
  const before = await recognizeTileSlots(frame, [original.drawSlot], base, "templates/bootstrap");
  const after = await recognizeTileSlots(frame, [proposal.drawSlot], base, "templates/bootstrap");
  assert.deepEqual(before.tiles, ["1m"]);
  assert.deepEqual(after.tiles, ["6s"]);
});

test("post-chi contiguous row keeps its original final tile and click point", async () => {
  const base = await layout();
  const original = calibratedOpenHandProposal(base, 1);
  const frame = "test/fixtures/open-post-chi-20261020.jpg";
  const proposal = await resolveOpenDrawGap(frame, base, original);
  assert.deepEqual(proposal, original);
  const result = await recognizeTileSlots(frame, [proposal.drawSlot], base, "templates/bootstrap");
  assert.deepEqual(result.tiles, ["C"]);
});

test("empty or unseparated compact draw areas never invent a shifted tile", async () => {
  const base = await layout();
  for (const openMelds of [1, 2, 3, 4]) {
    const original = calibratedOpenHandProposal(base, openMelds);
    for (const background of ["#102040", "#eeeeee"]) {
      const frame = await sharp({ create: { width: 1920, height: 1080, channels: 3, background } }).png().toBuffer();
      assert.deepEqual(await resolveOpenDrawGap(frame, base, original), original);
    }
  }
});
