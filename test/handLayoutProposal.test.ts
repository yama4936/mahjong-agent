import assert from "node:assert/strict";
import test from "node:test";
import sharp from "sharp";
import { layoutFromHandProposal, proposeHandLayout } from "../src/recognition/handLayoutProposal.js";

async function syntheticHand(drawGap: number, tileCount = 14): Promise<Buffer> {
  const width = 800;
  const height = 450;
  const tileWidth = 30;
  const tileHeight = 70;
  const ordinaryGap = 3;
  const left = 100;
  const handCount = tileCount - 1;
  const composites = Array.from({ length: tileCount }, (_, index) => {
    const x = index < handCount
      ? left + index * (tileWidth + ordinaryGap)
      : left + handCount * tileWidth + (handCount - 1) * ordinaryGap + drawGap;
    return {
      input: { create: { width: tileWidth, height: tileHeight, channels: 3 as const, background: "#f2eedb" } },
      left: x,
      top: 350,
    };
  });
  return sharp({ create: { width, height, channels: 3, background: "#101820" } }).composite(composites).png().toBuffer();
}

async function syntheticHandWithConnectedOverlay(): Promise<Buffer> {
  const image = await syntheticHand(14);
  // A medium-luminance annotation line joins every tile at permissive
  // thresholds, like detector overlays found in captured training images.
  return sharp(image).composite([{
    input: { create: { width: 471, height: 4, channels: 3, background: "#00cc55" } },
    left: 98,
    top: 350,
  }]).png().toBuffer();
}

async function syntheticPostCallHand(): Promise<Buffer> {
  const hand = await syntheticHand(3, 11);
  const melds = Array.from({ length: 3 }, (_, index) => ({
    input: { create: { width: 30, height: 70, channels: 3 as const, background: "#f2eedb" } },
    left: 600 + index * 33,
    top: 350,
  }));
  return sharp(hand).composite(melds).png().toBuffer();
}

test("proposes thirteen hand slots plus a separated draw slot", async () => {
  const proposal = await proposeHandLayout(await syntheticHand(14));
  assert.equal(proposal.handSlots.length, 13);
  assert.equal(proposal.drawSlot.x, 540);
  assert.equal(proposal.clickPoints.length, 14);
  assert.equal(proposal.evidence.medianGap, 3);
  assert.equal(proposal.evidence.drawGap, 14);
  assert.equal(proposal.requiresHoldoutValidation, true);
  assert.ok(proposal.confidence > 0.8);
});

test("proposes a compact hand plus draw slot after a kan", async () => {
  const proposal = await proposeHandLayout(await syntheticHand(14, 11), [11, 8, 5, 2]);
  assert.equal(proposal.handSlots.length, 10);
  assert.equal(proposal.clickPoints.length, 11);
  assert.equal(proposal.evidence.detectedTiles, 11);
  assert.equal(proposal.evidence.drawGap, 14);
});

test("isolates an unseparated compact hand from a same-height exposed meld", async () => {
  const proposal = await proposeHandLayout(await syntheticPostCallHand(), [11, 8, 5, 2]);
  assert.equal(proposal.handSlots.length, 10);
  assert.equal(proposal.clickPoints.length, 11);
  assert.equal(proposal.evidence.detectedTiles, 11);
  assert.equal(proposal.evidence.medianGap, 3);
  assert.equal(proposal.evidence.drawGap, 3);
  assert.equal(proposal.drawSlot.x, 430);
});

test("rejects a row whose draw tile cannot be distinguished", async () => {
  await assert.rejects(proposeHandLayout(await syntheticHand(3)), /not separated enough/);
});

test("uses a stricter threshold when an annotation overlay connects the hand", async () => {
  const proposal = await proposeHandLayout(await syntheticHandWithConnectedOverlay());
  assert.equal(proposal.handSlots.length, 13);
  assert.equal(proposal.drawSlot.x, 540);
  assert.ok(proposal.evidence.luminanceThreshold >= 190);
});

test("converts a proposal to an Advisor-only layout", () => {
  const proposal = {
    viewport: { width: 1280, height: 720 },
    handSlots: Array.from({ length: 13 }, (_, index) => ({ x: 100 + index * 40, y: 600, width: 38, height: 70 })),
    drawSlot: { x: 640, y: 600, width: 38, height: 70 },
    clickPoints: Array.from({ length: 14 }, (_, index) => ({ x: 119 + index * 40, y: 635 })),
    evidence: { detectedTiles: 14, luminanceThreshold: 190, medianWidth: 38, medianHeight: 70, medianGap: 2, drawGap: 22, rowBottomSpread: 0 },
    confidence: 0.99,
    requiresHoldoutValidation: true as const,
  };
  const layout = layoutFromHandProposal(proposal);
  assert.equal(layout.handSlots.length, 13);
  assert.deepEqual(layout.drawSlot, proposal.drawSlot);
  assert.equal(layout.autoOperation, undefined);
  assert.equal(layout.minimumVitConfidence, 0.5);
  assert.deepEqual(layout.publicTileRegions?.ownDiscards, {
    x: 513,
    y: 357,
    width: 260,
    height: 150,
    rotationToUpright: 0,
    detectionMode: "discard_grid",
  });
});
