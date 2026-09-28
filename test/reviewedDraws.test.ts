import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { overlayReviewedDraws } from "../src/logging/reviewedDraws.js";
import type { DecisionRecord } from "../src/logging/replay.js";

test("reviewed draw overlay requires exact attached image and preserves original records", async () => {
  const screenshot = "artifacts/live/reviewed-exhaustive-draw-20260928.png";
  const observedAt = "2026-09-28T05:06:14.920146+00:00";
  const digest = createHash("sha256").update(await readFile(screenshot)).digest("hex");
  const review = { observedAt, screenshotSha256: digest, outcome: "exhaustive_draw", note: "Verified result screenshot" };
  const record = { id: "a", actualResult: { round: { observedAt, screenshot, screenState: "round_result" } } } as DecisionRecord;
  const unknown = { id: "b" } as DecisionRecord;
  const labeled = await overlayReviewedDraws([record, unknown], [review]);
  assert.equal(labeled[0]?.actualResult?.won, false);
  assert.equal(labeled[0]?.actualResult?.dealIn, false);
  assert.equal(record.actualResult?.won, undefined);
  assert.equal(labeled[1], unknown);
  await assert.rejects(overlayReviewedDraws([record], [review, review]), /Duplicate/);
  await assert.rejects(overlayReviewedDraws([record], [{ ...review, screenshotSha256: "0".repeat(64) }]), /digest mismatch/);
  await assert.rejects(overlayReviewedDraws([unknown], [review]), /no attached/);
  await assert.rejects(overlayReviewedDraws([{ ...record, actualResult: { ...record.actualResult, won: true } }], [review]), /conflicts/);
});
