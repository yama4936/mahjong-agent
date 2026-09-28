import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { z } from "zod";
import type { DecisionRecord } from "./replay.js";

const reviewSchema = z.array(z.object({
  observedAt: z.string().datetime({ offset: true }),
  screenshotSha256: z.string().regex(/^[a-f0-9]{64}$/),
  note: z.string().min(1).max(2000),
  outcome: z.literal("exhaustive_draw"),
}));

/** Read-only overlay of human-reviewed draws; never guesses labels or edits logs. */
export async function overlayReviewedDraws(records: readonly DecisionRecord[], input: unknown): Promise<DecisionRecord[]> {
  const reviews = reviewSchema.parse(input);
  const indexed = new Map(reviews.map((review) => [Date.parse(review.observedAt), review]));
  if (indexed.size !== reviews.length) throw new Error("Duplicate reviewed round");
  const matched = new Set<number>();
  const digests = new Map<string, string>();
  const output: DecisionRecord[] = [];
  for (const record of records) {
    const evidence = record.actualResult?.round;
    const key = evidence ? Date.parse(evidence.observedAt) : NaN;
    const review = indexed.get(key);
    if (!review) { output.push(record); continue; }
    if (!evidence || evidence.screenState !== "round_result") throw new Error("Missing round image evidence");
    let digest = digests.get(evidence.screenshot);
    if (!digest) {
      digest = createHash("sha256").update(await readFile(evidence.screenshot)).digest("hex");
      digests.set(evidence.screenshot, digest);
    }
    if (digest !== review.screenshotSha256) throw new Error("Reviewed image digest mismatch");
    if (record.actualResult?.won === true || record.actualResult?.dealIn === true)
      throw new Error("Reviewed draw conflicts with existing result");
    matched.add(key);
    output.push({ ...record, actualResult: { ...record.actualResult, won: false, dealIn: false,
      reviewedDraw: review } });
  }
  if (matched.size !== reviews.length) throw new Error("Reviewed round has no attached replay evidence");
  return output;
}
