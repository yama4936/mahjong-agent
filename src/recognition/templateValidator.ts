import { readdir } from "node:fs/promises";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import sharp from "sharp";
import { parseGameTile, type GameTile } from "../game/tiles.js";
import { classifyTile, loadTemplates } from "./templateMatcher.js";

export interface TemplateValidationOptions {
  holdoutPattern?: RegExp;
  maxPerClass?: number;
  minimumConfidence?: number;
  minimumMargin?: number;
  orientation?: "any" | "upright";
  tileMatcher?: "raw" | "face" | "face_all";
}

export const AUTO_MINIMUM_CLASSES = 37;
export const AUTO_MINIMUM_HOLDOUTS_PER_CLASS = 5;
export const AUTO_MINIMUM_HOLDOUTS = AUTO_MINIMUM_CLASSES * AUTO_MINIMUM_HOLDOUTS_PER_CLASS;

interface ValidationRow {
  file: string;
  expected: GameTile;
  predicted: GameTile;
  confidence: number;
  margin: number;
  correct: boolean;
  automationSafe: boolean;
}

export async function fingerprintTemplateDirectory(directory: string): Promise<string> {
  const files = (await readdir(directory)).filter((file) => /\.(png|jpe?g|webp)$/i.test(file)).sort();
  const hash = createHash("sha256");
  for (const file of files) {
    hash.update(file);
    hash.update("\0");
    hash.update(await readFile(path.join(directory, file)));
    hash.update("\0");
  }
  return hash.digest("hex");
}

export async function validateTemplateDirectory(directory: string, options: TemplateValidationOptions = {}) {
  const holdoutPattern = options.holdoutPattern ?? /(?:capture|holdout|test)/i;
  const minimumConfidence = options.minimumConfidence ?? 0.98;
  const minimumMargin = options.minimumMargin ?? 0.01;
  const maxPerClass = options.maxPerClass ?? Number.POSITIVE_INFINITY;
  const imageFiles = (await readdir(directory)).filter((file) => /\.(png|jpe?g|webp)$/i.test(file));
  const contentLabels = new Map<string, Map<GameTile, string[]>>();
  for (const file of imageFiles) {
    const label = parseGameTile(path.parse(file).name.split("__")[0]!);
    const digest = createHash("sha256").update(await readFile(path.join(directory, file))).digest("hex");
    const labels = contentLabels.get(digest) ?? new Map<GameTile, string[]>();
    labels.set(label, [...(labels.get(label) ?? []), file]);
    contentLabels.set(digest, labels);
  }
  const crossLabelCollisions = [...contentLabels.entries()].flatMap(([sha256, labels]) => (
    labels.size > 1 ? [{ sha256, labels: Object.fromEntries(labels) }] : []
  ));
  const trainHoldoutCollisions = [...contentLabels.entries()].flatMap(([sha256, labels]) => {
    const files = [...labels.values()].flat();
    return files.some(file => holdoutPattern.test(file)) && files.some(file => !holdoutPattern.test(file))
      ? [{ sha256, files }] : [];
  });
  let holdouts = imageFiles.filter((file) => holdoutPattern.test(file));
  if ((options.orientation ?? "any") === "upright") {
    const checks = await Promise.all(holdouts.map(async (file) => {
      const metadata = await sharp(path.join(directory, file)).metadata();
      return { file, upright: Boolean(metadata.width && metadata.height && metadata.height >= metadata.width * 1.15) };
    }));
    holdouts = checks.filter((check) => check.upright).map((check) => check.file);
  }
  if (holdouts.length === 0) throw new Error(`No holdout templates match ${holdoutPattern}`);

  const selected: string[] = [];
  const counts = new Map<GameTile, number>();
  for (const file of holdouts.sort()) {
    const expected = parseGameTile(path.parse(file).name.split("__")[0]!);
    const count = counts.get(expected) ?? 0;
    if (count >= maxPerClass) continue;
    counts.set(expected, count + 1);
    selected.push(file);
  }

  const tileMatcher = options.tileMatcher ?? "raw";
  const matcherOptions = { normalizeFace: tileMatcher !== "raw", allClasses: tileMatcher === "face_all", rejectBlank: true };
  const templates = await loadTemplates(directory, (file) => !holdoutPattern.test(file), matcherOptions);
  const rows: ValidationRow[] = [];
  for (const file of selected) {
    const expected = parseGameTile(path.parse(file).name.split("__")[0]!);
    const match = await classifyTile(path.join(directory, file), templates, matcherOptions);
    const margin = match.confidence - match.runnerUpConfidence;
    rows.push({
      file,
      expected,
      predicted: match.tile,
      confidence: match.confidence,
      margin,
      correct: match.tile === expected,
      automationSafe: match.tile === expected && match.confidence >= minimumConfidence && margin >= minimumMargin,
    });
  }

  const perClass = Object.fromEntries([...new Set(rows.map((row) => row.expected))].sort().map((tile) => {
    const classRows = rows.filter((row) => row.expected === tile);
    return [tile, {
      total: classRows.length,
      correct: classRows.filter((row) => row.correct).length,
      safe: classRows.filter((row) => row.automationSafe).length,
      accuracy: classRows.filter((row) => row.correct).length / classRows.length,
    }];
  }));
  const correct = rows.filter((row) => row.correct).length;
  const safe = rows.filter((row) => row.automationSafe).length;
  const everyClassHasEnoughHoldouts = Object.values(perClass).every(
    (metrics) => metrics.total >= AUTO_MINIMUM_HOLDOUTS_PER_CLASS,
  );
  const minimumObservedConfidence = Math.min(...rows.map((row) => row.confidence));
  const minimumObservedMargin = Math.min(...rows.map((row) => row.margin));
  return {
    matcherVersion: "2",
    tileMatcher,
    templateSetFingerprint: await fingerprintTemplateDirectory(directory),
    total: rows.length,
    correct,
    safe,
    accuracy: correct / rows.length,
    automationSafeRate: safe / rows.length,
    minimumObservedConfidence,
    minimumObservedMargin,
    passesAutoCalibration: crossLabelCollisions.length === 0
      && trainHoldoutCollisions.length === 0
      && rows.length >= AUTO_MINIMUM_HOLDOUTS
      && Object.keys(perClass).length >= AUTO_MINIMUM_CLASSES
      && everyClassHasEnoughHoldouts
      && templates.size >= AUTO_MINIMUM_CLASSES
      && correct === rows.length
      && safe === rows.length,
    thresholds: {
      minimumConfidence,
      minimumMargin,
      minimumSamples: AUTO_MINIMUM_HOLDOUTS,
      minimumClasses: AUTO_MINIMUM_CLASSES,
      minimumSamplesPerClass: AUTO_MINIMUM_HOLDOUTS_PER_CLASS,
      orientation: options.orientation ?? "any",
    },
    perClass,
    crossLabelCollisions,
    trainHoldoutCollisions,
    failures: rows.filter((row) => !row.automationSafe),
  };
}
