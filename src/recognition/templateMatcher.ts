import { readdir } from "node:fs/promises";
import path from "node:path";
import sharp from "sharp";
import { parseGameTile, type GameTile } from "../game/tiles.js";
import type { Rect, ScreenLayout } from "./layout.js";
import { normalizeTileFace } from "./normalizeTileFace.js";

export interface MatcherOptions {
  normalizeFace?: boolean;
  allClasses?: boolean;
  rejectBlank?: boolean;
}

export interface TileMatch {
  tile: GameTile;
  confidence: number;
  runnerUpConfidence: number;
}

interface PreparedImage { data: Int16Array; width: number; height: number; foregroundFraction: number }

const templateCache = new Map<string, Promise<Map<GameTile, PreparedImage[]>>>();

async function prepare(input: string | Buffer, rect?: Rect, options: MatcherOptions = {}): Promise<PreparedImage> {
  let pipeline = sharp(input);
  if (rect) pipeline = pipeline.extract({ left: rect.x, top: rect.y, width: rect.width, height: rect.height });
  if (options.normalizeFace) pipeline = sharp(await normalizeTileFace(await pipeline.png().toBuffer()));
  const { data: rgb, info } = await pipeline
    .resize(44, 64, { fit: "fill" })
    .removeAlpha()
    .toColourspace("srgb")
    .raw()
    .toBuffer({ resolveWithObject: true });
  const cornerValues: Array<[number, number, number]> = [];
  for (let y = 5; y < info.height - 5; y += 1) {
    for (let x = 5; x < info.width - 5; x += 1) {
      if (!((x < 12 || x >= info.width - 12) && (y < 14 || y >= info.height - 14))) continue;
      const index = (y * info.width + x) * 3;
      cornerValues.push([rgb[index]!, rgb[index + 1]!, rgb[index + 2]!]);
    }
  }
  const median = (channel: number) => cornerValues.map((value) => value[channel]!).sort((a, b) => a - b)[Math.floor(cornerValues.length / 2)]!;
  const background = [median(0), median(1), median(2)];
  const data = new Int16Array(info.width * info.height * 3);
  let foreground = 0;
  for (let y = 0; y < info.height; y += 1) {
    for (let x = 0; x < info.width; x += 1) {
      const index = y * info.width + x;
      const rgbIndex = index * 3;
      const red = rgb[rgbIndex]! - background[0]!;
      const green = rgb[rgbIndex + 1]! - background[1]!;
      const blue = rgb[rgbIndex + 2]! - background[2]!;
      const distance = Math.sqrt(
        red ** 2 + green ** 2 + blue ** 2,
      ) / Math.sqrt(3);
      if (x < 3 || x >= info.width - 3 || y < 3 || y >= info.height - 3 || distance < 18) continue;
      const featureIndex = index * 3;
      data[featureIndex] = red;
      data[featureIndex + 1] = green;
      data[featureIndex + 2] = blue;
      foreground += 1;
    }
  }
  return { data, width: info.width, height: info.height, foregroundFraction: foreground / (info.width * info.height) };
}

function similarity(a: PreparedImage, b: PreparedImage): number {
  if (a.width !== b.width || a.height !== b.height) throw new Error("Template shape mismatch");
  let best = 0;
  for (let dy = -2; dy <= 2; dy += 1) {
    for (let dx = -2; dx <= 2; dx += 1) {
      const score = similarityAtOffset(a, b, dx, dy);
      if (score > best) best = score;
    }
  }
  return best;
}

function cosineSimilarity(a: PreparedImage, b: PreparedImage): number {
  let best = 0;
  for (let dy = -2; dy <= 2; dy += 1) {
    for (let dx = -2; dx <= 2; dx += 1) {
      const score = cosineSimilarityAtOffset(a, b, dx, dy);
      if (score > best) best = score;
    }
  }
  return best;
}

function cosineSimilarityAtOffset(a: PreparedImage, b: PreparedImage, dx: number, dy: number): number {
  let dot = 0;
  let normA = 0;
  let normB = 0;
  for (let y = 2; y < a.height - 2; y += 1) {
    const by = y + dy;
    if (by < 2 || by >= b.height - 2) continue;
    for (let x = 2; x < a.width - 2; x += 1) {
      const bx = x + dx;
      if (bx < 2 || bx >= b.width - 2) continue;
      const aIndex = (y * a.width + x) * 3;
      const bIndex = (by * b.width + bx) * 3;
      for (let channel = 0; channel < 3; channel += 1) {
        const av = a.data[aIndex + channel]!;
        const bv = b.data[bIndex + channel]!;
        dot += av * bv;
        normA += av * av;
        normB += bv * bv;
      }
    }
  }
  return normA > 0 && normB > 0 ? dot / Math.sqrt(normA * normB) : 0;
}

function similarityAtOffset(a: PreparedImage, b: PreparedImage, dx: number, dy: number): number {
  let dot = 0;
  let normA = 0;
  let normB = 0;
  let absoluteDifference = 0;
  let absoluteMagnitude = 0;
  for (let y = 2; y < a.height - 2; y += 1) {
    const by = y + dy;
    if (by < 2 || by >= b.height - 2) continue;
    for (let x = 2; x < a.width - 2; x += 1) {
      const bx = x + dx;
      if (bx < 2 || bx >= b.width - 2) continue;
      const aIndex = (y * a.width + x) * 3;
      const bIndex = (by * b.width + bx) * 3;
      for (let channel = 0; channel < 3; channel += 1) {
        const av = a.data[aIndex + channel]!;
        const bv = b.data[bIndex + channel]!;
        dot += av * bv;
        normA += av * av;
        normB += bv * bv;
        absoluteDifference += Math.abs(av - bv);
        absoluteMagnitude += Math.abs(av) + Math.abs(bv);
      }
    }
  }
  if (normA === 0 || normB === 0) return 0;
  const cosine = dot / Math.sqrt(normA * normB);
  // Cosine similarity alone makes tiles that differ by only one pip look
  // deceptively identical. The normalized L1 term preserves exact matches
  // while giving missing/extra strokes enough weight for a useful margin.
  const shape = absoluteMagnitude > 0 ? 1 - absoluteDifference / absoluteMagnitude : 0;
  return 0.55 * cosine + 0.45 * shape;
}

export async function loadTemplates(directory: string, includeFile: (file: string) => boolean = () => true, options: MatcherOptions = {}): Promise<Map<GameTile, PreparedImage[]>> {
  const templates = new Map<GameTile, PreparedImage[]>();
  for (const file of await readdir(directory)) {
    if (!/\.(png|jpe?g|webp)$/i.test(file) || !includeFile(file)) continue;
    const tile = parseGameTile(path.parse(file).name.split("__")[0]!);
    const variants = templates.get(tile) ?? [];
    variants.push(await prepare(path.join(directory, file), undefined, options));
    templates.set(tile, variants);
  }
  if (templates.size < 34) throw new Error(`Template set is incomplete: ${templates.size}/34 tile classes`);
  return templates;
}

export function clearTemplateCache(directory?: string): void {
  if (directory) {
    for (const key of templateCache.keys()) if (key.startsWith(`${path.resolve(directory)}:`)) templateCache.delete(key);
  }
  else templateCache.clear();
}

export async function measureSlotPresence(screenshot: string | Buffer, slots: Rect[], minimumLuminance = 120): Promise<number[]> {
  const { data: rgb, info } = await sharp(screenshot).removeAlpha().toColourspace("srgb").raw().toBuffer({ resolveWithObject: true });
  return slots.map((slot) => {
    if (slot.x + slot.width > info.width || slot.y + slot.height > info.height) return 0;
    let bright = 0;
    for (let y = slot.y; y < slot.y + slot.height; y += 1) {
      for (let x = slot.x; x < slot.x + slot.width; x += 1) {
        const index = (y * info.width + x) * 3;
        const luminance = 0.2126 * rgb[index]! + 0.7152 * rgb[index + 1]! + 0.0722 * rgb[index + 2]!;
        if (luminance > minimumLuminance) bright += 1;
      }
    }
    return bright / (slot.width * slot.height);
  });
}

async function loadRuntimeTemplates(directory: string, options: MatcherOptions = {}): Promise<Map<GameTile, PreparedImage[]>> {
  const key = `${path.resolve(directory)}:${Boolean(options.normalizeFace)}`;
  let pending = templateCache.get(key);
  if (!pending) {
    pending = loadTemplates(directory, file => !/(?:holdout|capture|test)/i.test(file), options);
    templateCache.set(key, pending);
    pending.catch(() => templateCache.delete(key));
  }
  return pending;
}

export async function warmTemplateCache(directory: string, options: MatcherOptions = {}): Promise<void> {
  await loadRuntimeTemplates(directory, options);
}

export async function matchTile(screenshot: string | Buffer, rect: Rect, templates: Map<GameTile, PreparedImage[]>, options: MatcherOptions = {}): Promise<TileMatch> {
  const sample = await prepare(screenshot, rect, options);
  return scorePrepared(sample, templates, options);
}

export async function classifyTile(image: string | Buffer, templates: Map<GameTile, PreparedImage[]>, options: MatcherOptions = {}): Promise<TileMatch> {
  return scorePrepared(await prepare(image, undefined, options), templates, options);
}

function scorePrepared(sample: PreparedImage, templates: Map<GameTile, PreparedImage[]>, options: MatcherOptions = {}): TileMatch {
  if (sample.foregroundFraction < 0.005 && templates.has("P")) {
    if (options.rejectBlank !== false) return { tile: "P", confidence: 0, runnerUpConfidence: 0 };
    return { tile: "P", confidence: 1, runnerUpConfidence: 0.5 };
  }
  const shortlist = [...templates.entries()].map(([tile, variants]) => ({
    tile,
    variants,
    coarse: Math.max(...variants.map((variant) => similarityAtOffset(sample, variant, 0, 0))),
  })).sort((a, b) => b.coarse - a.coarse).slice(0, options.allClasses ? templates.size : 4);
  const scores = shortlist.map(({ tile, variants }) => ({
    tile,
    discriminativeScore: Math.max(...variants.map((variant) => similarity(sample, variant))),
    confidence: Math.max(...variants.map((variant) => cosineSimilarity(sample, variant))),
  })).sort((a, b) => b.discriminativeScore - a.discriminativeScore);
  const winner = scores[0]!;
  const margin = winner.discriminativeScore - scores[1]!.discriminativeScore;
  return {
    tile: winner.tile,
    confidence: winner.confidence,
    runnerUpConfidence: Math.max(0, winner.confidence - margin),
  };
}

export async function recognizeHand(screenshot: string | Buffer, layout: ScreenLayout, templateDirectory: string) {
  const slots = layout.drawSlot ? [...layout.handSlots, layout.drawSlot] : layout.handSlots;
  const result = await recognizeTileSlots(screenshot, slots, layout, templateDirectory);
  const turnReady = result.matches.length === 14;
  return {
    ...result,
    turnReady,
    safe: result.safe && turnReady,
  };
}

export async function recognizeTileSlots(
  screenshot: string | Buffer,
  slots: Rect[],
  layout: ScreenLayout,
  templateDirectory: string,
) {
  const presenceFractions = await measureSlotPresence(screenshot, slots);
  if (presenceFractions.some((fraction) => fraction < layout.minimumTilePresence)) {
    return { tiles: [], matches: [], confidence: 0, ambiguityMargin: 0, presenceFractions, safe: false };
  }
  const options: MatcherOptions = { normalizeFace: layout.tileMatcher !== "raw", allClasses: layout.tileMatcher === "face_all", rejectBlank: true };
  const templates = await loadRuntimeTemplates(templateDirectory, options);
  const matches = await Promise.all(slots.map((slot) => matchTile(screenshot, slot, templates, options)));
  const confidence = Math.min(...matches.map((match) => match.confidence));
  const ambiguityMargin = Math.min(...matches.map((match) => match.confidence - match.runnerUpConfidence));
  return {
    tiles: matches.map((match) => match.tile),
    matches,
    confidence,
    ambiguityMargin,
    presenceFractions,
    safe: confidence >= layout.minimumTileConfidence && ambiguityMargin >= 0.01,
  };
}
