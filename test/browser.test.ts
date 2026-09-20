import assert from "node:assert/strict";
import test from "node:test";
import { captureViewport, guardedDiscard, guardedUiAction } from "../src/jantama/browser.js";
import sharp from "sharp";
import { layoutSchema } from "../src/recognition/layout.js";

const layout = layoutSchema.parse({
  viewport: { width: 1920, height: 1080 },
  handSlots: Array.from({ length: 13 }, (_, index) => ({ x: 100 + index * 45, y: 759, width: 45, height: 84 })),
  drawSlot: { x: 685, y: 759, width: 45, height: 84 },
  clickPoints: Array.from({ length: 14 }, (_, index) => ({ x: 122.5 + index * 45, y: 801 })),
  publicTileRegions: { ownDiscards: { x: 700, y: 500, width: 220, height: 120 } },
  minimumTileConfidence: 0.98,
  autoOperation: { enabled: true, recognizer: "template", matcherVersion: "2", tileMatcher: "raw", samples: 185, accuracy: 1, automationSafeRate: 1, validatedAt: "2026-09-19T00:00:00.000Z", templateSetFingerprint: "a".repeat(64) },
});

const uncalibratedLayout = layoutSchema.parse({
  viewport: { width: 1920, height: 1080 },
  handSlots: Array.from({ length: 13 }, (_, index) => ({ x: 100 + index * 45, y: 759, width: 45, height: 84 })),
  drawSlot: { x: 685, y: 759, width: 45, height: 84 },
  clickPoints: Array.from({ length: 14 }, (_, index) => ({ x: 122.5 + index * 45, y: 801 })),
  minimumTileConfidence: 0.98,
});

test("guarded discard clicks only after a stable frame", async () => {
  const clicks: Array<[number, number]> = [];
  const screenshotOptions: any[] = [];
  let clicked = false;
  const page = {
    screenshot: async (options: any) => {
      screenshotOptions.push(options);
      const isRiver = options.clip.x === 700;
      return Buffer.from(clicked ? (isRiver ? "river-after" : "hand-after") : (isRiver ? "river-before" : "hand-before"));
    },
    waitForTimeout: async () => undefined,
    mouse: { click: async (x: number, y: number) => { clicks.push([x, y]); clicked = true; } },
  } as any;
  const receipt = await guardedDiscard(page, layout, 3, { allowed: true, recognitionConfidence: 0.99, decisionConfidence: 0.8 });
  assert.deepEqual(clicks, [[257.5, 801]]);
  assert.deepEqual(screenshotOptions[0].clip, { x: 100, y: 759, width: 630, height: 84 });
  assert.equal(receipt.confirmation, "hand_and_own_river_changed");
});

test("guarded discard refuses a changing frame", async () => {
  let frame = 0;
  const page = {
    screenshot: async () => Buffer.from(`frame-${frame++}`),
    waitForTimeout: async () => undefined,
    mouse: { click: async () => assert.fail("must not click") },
  } as any;
  await assert.rejects(
    guardedDiscard(page, layout, 3, { allowed: true, recognitionConfidence: 0.99, decisionConfidence: 0.8 }),
    /Hand changed/,
  );
});

test("guarded discard refuses low confidence", async () => {
  const page = { mouse: { click: async () => assert.fail("must not click") } } as any;
  await assert.rejects(
    guardedDiscard(page, layout, 0, { allowed: true, recognitionConfidence: 0.9, decisionConfidence: 0.8 }),
    /Recognition confidence/,
  );
});

test("guarded discard refuses templates without passing calibration evidence", async () => {
  const page = { mouse: { click: async () => assert.fail("must not click") } } as any;
  await assert.rejects(
    guardedDiscard(page, uncalibratedLayout, 0, { allowed: true, recognitionConfidence: 0.99, decisionConfidence: 0.8 }),
    /passing template calibration/,
  );
});

test("guarded discard requires an own-river region for outcome verification", async () => {
  const page = { mouse: { click: async () => assert.fail("must not click") } } as any;
  await assert.rejects(
    guardedDiscard(page, { ...layout, publicTileRegions: undefined }, 0, { allowed: true, recognitionConfidence: 0.99, decisionConfidence: 0.8 }),
    /Own discard region/,
  );
});

test("viewport validation uses actual screenshot dimensions for CDP pages", async () => {
  const image = await sharp({ create: { width: 1920, height: 1080, channels: 3, background: "black" } }).png().toBuffer();
  const page = { screenshot: async () => image, viewportSize: () => null } as any;
  assert.equal((await captureViewport(page, layout)).length, image.length);
});

test("non-discard clicks stay forbidden without an action-specific certificate", async () => {
  const page = { mouse: { click: async () => assert.fail("must not click") } } as any;
  const actionLayout = layoutSchema.parse({
    ...uncalibratedLayout,
    actionButtonRegions: { ron: { x: 1400, y: 800, width: 180, height: 70 } },
  });
  await assert.rejects(
    guardedUiAction(page, actionLayout, "ron", {
      allowed: true,
      buttonConfidence: 1,
      decisionConfidence: 1,
      templateSetFingerprint: "a".repeat(64),
    }),
    /forbidden without an action-specific calibration certificate/,
  );
});

test("a certified call requires button, hand, and own-meld changes", async () => {
  let clicked = false;
  const fingerprint = "b".repeat(64);
  const actionLayout = layoutSchema.parse({
    ...layout,
    publicTileRegions: {
      ...layout.publicTileRegions,
      ownMelds: { x: 1500, y: 850, width: 250, height: 100 },
    },
    actionButtonRegions: { pon: { x: 1400, y: 800, width: 180, height: 70 } },
    actionOperation: {
      pon: { enabled: true, samples: 20, accuracy: 1, falsePositiveRate: 0, validatedAt: "2026-09-19T00:00:00.000Z", templateSetFingerprint: fingerprint },
    },
  });
  const page = {
    screenshot: async (options: any) => {
      const name = options.clip.x === 1400 ? "button" : options.clip.x === 1500 ? "meld" : "hand";
      return Buffer.from(`${name}-${clicked ? "after" : "before"}`);
    },
    waitForTimeout: async () => undefined,
    mouse: { click: async () => { clicked = true; } },
  } as any;
  const receipt = await guardedUiAction(page, actionLayout, "pon", {
    allowed: true,
    buttonConfidence: 1,
    decisionConfidence: 1,
    templateSetFingerprint: fingerprint,
  });
  assert.equal(receipt.confirmation, "action_button_hand_and_meld_changed");
});
