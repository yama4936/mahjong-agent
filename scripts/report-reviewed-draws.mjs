import { readFile } from "node:fs/promises";
import { readDecisionDataset } from "../dist/src/logging/replay.js";
import { overlayReviewedDraws } from "../dist/src/logging/reviewedDraws.js";
import { summarizeDecisionMetrics } from "../dist/src/logging/metrics.js";

const [dataset, manifest] = process.argv.slice(2);
if (!dataset || !manifest) throw new Error("Usage: node scripts/report-reviewed-draws.mjs <replays> <review.json>");
const records = await readDecisionDataset(dataset);
const reviews = JSON.parse(await readFile(manifest, "utf8"));
const reviewed = await overlayReviewedDraws(records, reviews);
console.log(JSON.stringify({ scope: "reviewed_subset_not_full_match_or_ranked_benchmark",
  reviewedDraws: reviews.length, metrics: summarizeDecisionMetrics(reviewed) }, null, 2));
