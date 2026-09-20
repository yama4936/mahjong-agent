import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { classifyTile, loadTemplates, type MatcherOptions } from "../src/recognition/templateMatcher.js";
import { VitTileRecognizer } from "../src/recognition/vitRecognizer.js";

const root = path.resolve("templates/bootstrap");
const output = path.resolve(process.argv[2] ?? "artifacts/recognition-ablation");
await mkdir(output, { recursive: true });
const files = (await readdir(root)).filter(f => f.endsWith(".png")).sort();
const train = files.filter(f => /__hf_(base|real_)/.test(f));
const test = files.filter(f => /__hf_holdout_/.test(f));
const digest = async (file: string) => createHash("sha256").update(await readFile(path.join(root, file))).digest("hex");
const hashes = new Set(await Promise.all(train.map(digest)));
const testRows = await Promise.all(test.map(async file => ({ file, label: file.split("__")[0]!, sha256: await digest(file) })));
const clean = testRows.filter(row => !hashes.has(row.sha256));
const variants: Record<string, MatcherOptions> = {
  baseline: { rejectBlank: false },
  all_classes: { allClasses: true, rejectBlank: true },
  normalized: { normalizeFace: true, rejectBlank: true },
  normalized_all: { normalizeFace: true, allClasses: true, rejectBlank: true },
};
const results: Record<string, any> = {};
function summarize(rows: any[], elapsedMs: number) {
  const accepted = rows.filter(r => r.accepted);
  const correct = rows.filter(r => r.predicted === r.label).length;
  return {
    total: rows.length, correct, accuracy: correct / rows.length,
    accepted: accepted.length, coverage: accepted.length / rows.length,
    acceptedErrors: accepted.filter(r => r.predicted !== r.label).length,
    acceptedAccuracy: accepted.length ? accepted.filter(r => r.predicted === r.label).length / accepted.length : null,
    meanMs: elapsedMs / rows.length, rows,
  };
}
async function save() {
  await writeFile(path.join(output, "report.json"), JSON.stringify({
    evaluatedAt: new Date().toISOString(), trainingImages: train.length,
    excludedExactTrainTestDuplicates: testRows.length - clean.length,
    notes: ["Fixed public dataset test split, not independent live matches.", "ViT training overlap with this public dataset is unknown; its results are diagnostic, not independent validation.", "Thresholds fixed at 0.98 and margin 0.01; scores are not calibrated probabilities.", "No red-five holdouts. No Auto certificate is issued."], results,
  }, null, 2));
}
for (const [name, options] of Object.entries(variants)) {
  const templates = await loadTemplates(root, f => train.includes(f), options);
  const started = performance.now();
  const rows = [];
  for (const [index, row] of clean.entries()) {
    const match = await classifyTile(path.join(root, row.file), templates, options);
    rows.push({ ...row, predicted: match.tile, score: match.confidence, margin: match.confidence - match.runnerUpConfidence,
      accepted: match.confidence >= 0.98 && match.confidence - match.runnerUpConfidence >= 0.01 });
    if (index % 20 === 0) console.log(`${name}: ${index}/${clean.length}`);
  }
  results[name] = summarize(rows, performance.now() - started);
  await save();
  console.log(JSON.stringify({ name, ...results[name], rows: undefined }));
}
const vit = new VitTileRecognizer();
try {
  const started = performance.now();
  const predictions = await vit.classifyTileImages(await Promise.all(clean.map(row => readFile(path.join(root, row.file)))));
  const rows = clean.map((row, i) => {
    const p = predictions[i]!;
    return { ...row, predicted: p.tile, score: p.confidence, accepted: p.confidence >= 0.98 && p.confidence - p.runnerUpConfidence >= 0.01 };
  });
  results.vit = summarize(rows, performance.now() - started);
  const paired = rows.map((row, i) => {
    const accepted = row.accepted && results.normalized_all.rows[i].accepted && row.predicted === results.normalized_all.rows[i].predicted;
    return { ...row, predicted: accepted ? row.predicted : null, accepted };
  });
  results.agreement = summarize(paired, performance.now() - started);
  await save();
  console.log(JSON.stringify({ name: "vit", ...results.vit, rows: undefined }));
  console.log(JSON.stringify({ name: "agreement", ...results.agreement, rows: undefined }));
} catch (error) {
  results.vitError = String(error); await save();
} finally { await vit.close(); }
