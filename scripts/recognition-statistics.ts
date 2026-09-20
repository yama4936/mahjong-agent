import { readFile, writeFile } from "node:fs/promises";

const directory = "artifacts/recognition-ablation";
const publicReport = JSON.parse(await readFile(`${directory}/report.json`, "utf8"));
const liveReport = JSON.parse(await readFile(`${directory}/live-report.json`, "utf8"));
const cnn = JSON.parse(await readFile(`${directory}/cnn37-report.json`, "utf8"));

function wilson(successes: number, n: number) {
  if (!n) return null;
  const z = 1.959963984540054, p = successes / n, denominator = 1 + z * z / n;
  const center = (p + z * z / (2 * n)) / denominator;
  const half = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator;
  return [Math.max(0, center - half), Math.min(1, center + half)];
}
function summary(rows: any[]) {
  const isCorrect = (r: any) => r.predicted === (r.label ?? r.expected);
  const correct = rows.filter(isCorrect).length;
  const accepted = rows.filter(r => r.accepted);
  const acceptedCorrect = accepted.filter(isCorrect).length;
  return { total: rows.length, correct, accuracy: rows.length ? correct / rows.length : null,
    accepted: accepted.length, coverage: rows.length ? accepted.length / rows.length : null,
    acceptedErrors: accepted.length - acceptedCorrect,
    acceptedAccuracy: accepted.length ? acceptedCorrect / accepted.length : null,
    iidOnlyWilson95: wilson(correct, rows.length),
    acceptedIidOnlyWilson95: wilson(acceptedCorrect, accepted.length),
    scoreBins: [[0,.5],[.5,.8],[.8,.9],[.9,.95],[.95,.98],[.98,1.000001]].map(([low, high]) => {
      const bin = rows.filter(r => r.score >= low! && r.score < high!);
      return { low, high: Math.min(1, high!), count: bin.length,
        accuracy: bin.length ? bin.filter(isCorrect).length / bin.length : null,
        meanScore: bin.length ? bin.reduce((sum, r) => sum + r.score, 0) / bin.length : null };
    }) };
}
function variants(source: any) {
  return Object.fromEntries(Object.entries<any>(source).filter(([, value]) => value.rows).map(([name, value]) => {
    // Agreement is an abstaining classifier, not the raw model's accuracy.
    const rows = value.rows.map((r: any) => name === "agreement" && !r.accepted ? { ...r, predicted: null } : r);
    return [name, summary(rows)];
  }));
}
const report = {
  scoreIsCalibratedProbability: false,
  caveats: [
    "Wilson intervals below assume independent samples; these correlated crops do NOT meet that assumption. Intervals are illustrative, not deployment guarantees.",
    "Public ViT test data may overlap its original training set.",
    "Live leave-one-frame-out uses six frames from one session, not independent matches.",
    "CNN uses a different training split; do not rank it against the 83-crop template cross-validation.",
    "No test-set threshold tuning or auto certification performed. No game win-rate measurement performed.",
  ],
  public: variants(publicReport.results), live: variants(liveReport.summaries), cnn: summary(cnn.rows),
  liveLabeledClasses: [...new Set(liveReport.summaries.normalized.rows.map((r: any) => r.label))].sort(),
  missingCnnTrainingClasses: cnn.missingTrainingClasses,
  independentMatchesTested: 0,
};
await writeFile(`${directory}/statistics.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, (key, value) => key === "scoreBins" ? undefined : value, 2));
