import sharp from "sharp";
import { normalizeTile, suitRank, tileIndex, type GameTile } from "../game/tiles.js";
import type { PublicTileRegion, PublicTileRegionName, ScreenLayout } from "./layout.js";
import { classifyTile, loadTemplates } from "./templateMatcher.js";
import { detectConfiguredPublicRegions, type RegionCandidate, type RegionDetectionOptions } from "./regionDetector.js";
import type { VitTilePrediction } from "./vitRecognizer.js";

export interface RecognizedPublicTile extends RegionCandidate {
  tile: GameTile;
  confidence: number;
  runnerUpConfidence: number;
  ambiguityMargin: number;
  safe: boolean;
}

export interface PublicTileRecognitionRegion {
  backend: "template" | "vit" | "hybrid";
  candidateCount: number;
  recognized: RecognizedPublicTile[];
  classificationSafe: boolean;
  rotationToUpright: 0 | 90 | 180 | 270;
}

export interface PublicTileRecognitionOptions extends RegionDetectionOptions {
  minimumConfidence?: number;
  minimumMargin?: number;
}

export interface PublicTileObservation {
  doraIndicators: GameTile[];
  ownDiscards: GameTile[];
  ownRiichiDeclared?: boolean;
  ownMelds?: RecognizedMeld[];
  opponentDiscards: Array<{
    seat: "east" | "south" | "west" | "north";
    discards: GameTile[];
    riichiDeclared?: boolean;
    melds?: RecognizedMeld[];
  }>;
  ownMeldTiles: GameTile[];
  allMeldTiles?: GameTile[];
  otherVisibleTiles: GameTile[];
  acceptedTiles: number;
  detectedCandidates: number;
  complete: false;
}

export interface RecognizedMeld {
  type: "chi" | "pon" | "minkan";
  tiles: GameTile[];
  confidence: number;
}

function normalizedDimensions(tile: RecognizedPublicTile, rotation: 0 | 90 | 180 | 270): { width: number; height: number } {
  return rotation === 90 || rotation === 270
    ? { width: tile.height, height: tile.width }
    : { width: tile.width, height: tile.height };
}

/** A sideways river tile is the visible evidence of a riichi declaration. */
export function hasSidewaysRiichiTile(region?: PublicTileRecognitionRegion): boolean {
  if (!region) return false;
  return region.recognized.some((tile) => {
    if (!tile.safe) return false;
    if (tile.sideways !== undefined) return tile.sideways;
    const dimensions = normalizedDimensions(tile, region.rotationToUpright);
    return dimensions.width / Math.max(1, dimensions.height) >= 1.2;
  });
}

function inferMeld(tiles: RecognizedPublicTile[]): RecognizedMeld | undefined {
  if (tiles.length !== 3 && tiles.length !== 4) return undefined;
  if (!tiles.every((tile) => tile.safe)) return undefined;
  const normalized = tiles.map((tile) => normalizeTile(tile.tile));
  const unique = new Set(normalized);
  let type: RecognizedMeld["type"] | undefined;
  if (unique.size === 1) type = tiles.length === 4 ? "minkan" : "pon";
  if (tiles.length === 3) {
    const indexes = normalized.map(tileIndex).sort((a, b) => a - b);
    if (indexes[0]! < 27 && indexes[2]! < 27
      && Math.floor(indexes[0]! / 9) === Math.floor(indexes[2]! / 9)
      && suitRank(indexes[1]!) === suitRank(indexes[0]!) + 1
      && suitRank(indexes[2]!) === suitRank(indexes[1]!) + 1) type = "chi";
  }
  if (!type) return undefined;
  return {
    type,
    tiles: tiles.map((tile) => tile.tile),
    confidence: Math.min(...tiles.map((tile) => tile.confidence)),
  };
}

/**
 * Converts a calibrated meld region into typed, complete exposed melds. A
 * region with ambiguous leftovers yields no promoted meld for those tiles.
 */
export function recognizeExposedMelds(region?: PublicTileRecognitionRegion): RecognizedMeld[] {
  if (!region || !region.classificationSafe) return [];
  const ordered = [...region.recognized].sort((left, right) => {
    const rotation = region.rotationToUpright;
    if (rotation === 90) return left.y - right.y || left.x - right.x;
    if (rotation === 180) return right.x - left.x || right.y - left.y;
    if (rotation === 270) return right.y - left.y || right.x - left.x;
    return left.x - right.x || left.y - right.y;
  });
  if (ordered.length === 3 || ordered.length === 4) {
    const meld = inferMeld(ordered);
    return meld ? [meld] : [];
  }
  // Multiple exposed melds are spatially separated. Split only at a gap that
  // is materially larger than a tile along the region's major axis.
  const groups: RecognizedPublicTile[][] = [];
  for (const tile of ordered) {
    const previous = groups.at(-1)?.at(-1);
    if (!previous) {
      groups.push([tile]);
      continue;
    }
    const vertical = region.rotationToUpright === 90 || region.rotationToUpright === 270;
    const gap = vertical ? Math.abs(tile.y - previous.y) : Math.abs(tile.x - previous.x);
    const span = vertical ? Math.max(tile.height, previous.height) : Math.max(tile.width, previous.width);
    if (gap > span * 1.6) groups.push([tile]);
    else groups.at(-1)!.push(tile);
  }
  return groups.map(inferMeld).filter((meld): meld is RecognizedMeld => Boolean(meld));
}

export function toPublicTileObservation(
  recognition: Partial<Record<PublicTileRegionName, PublicTileRecognitionRegion>>,
  ownSeat: "east" | "south" | "west" | "north" = "east",
): PublicTileObservation {
  const safeTiles = (name: PublicTileRegionName) => {
    const region = recognition[name];
    if (!region?.classificationSafe) return [];
    return region.recognized.filter((tile) => tile.safe).map((tile) => tile.tile);
  };
  const ownDiscards = safeTiles("ownDiscards");
  const doraIndicators = safeTiles("doraIndicators");
  const seats = ["east", "south", "west", "north"] as const;
  const ownIndex = seats.indexOf(ownSeat);
  const opponentDiscards = [
    { seat: seats[(ownIndex + 1) % 4]!, discards: safeTiles("rightDiscards"), riichiDeclared: hasSidewaysRiichiTile(recognition.rightDiscards), melds: recognizeExposedMelds(recognition.rightMelds) },
    { seat: seats[(ownIndex + 2) % 4]!, discards: safeTiles("oppositeDiscards"), riichiDeclared: hasSidewaysRiichiTile(recognition.oppositeDiscards), melds: recognizeExposedMelds(recognition.oppositeMelds) },
    { seat: seats[(ownIndex + 3) % 4]!, discards: safeTiles("leftDiscards"), riichiDeclared: hasSidewaysRiichiTile(recognition.leftDiscards), melds: recognizeExposedMelds(recognition.leftMelds) },
  ];
  const ownMeldTiles = safeTiles("ownMelds");
  const ownMelds = recognizeExposedMelds(recognition.ownMelds);
  const opponentMeldTiles = opponentDiscards.flatMap((opponent) => opponent.melds.flatMap((meld) => meld.tiles));
  const otherVisibleTiles = [...opponentDiscards.flatMap((opponent) => opponent.discards), ...ownMeldTiles, ...opponentMeldTiles];
  return {
    doraIndicators,
    ownDiscards,
    ownRiichiDeclared: hasSidewaysRiichiTile(recognition.ownDiscards),
    ownMelds,
    opponentDiscards,
    ownMeldTiles,
    allMeldTiles: [...ownMeldTiles, ...opponentMeldTiles],
    otherVisibleTiles,
    acceptedTiles: ownDiscards.length + otherVisibleTiles.length,
    detectedCandidates: Object.values(recognition).reduce((sum, region) => sum + (region?.candidateCount ?? 0), 0),
    complete: false,
  };
}

function hasPrefix<T>(current: readonly T[], previous: readonly T[]): boolean {
  return previous.every((value, index) => current[index] === value);
}

/** Rejects frame-to-frame river regressions or reorderings before promotion. */
export function assertTemporalPublicObservation(
  previous: PublicTileObservation,
  current: PublicTileObservation,
): void {
  if (!hasPrefix(current.doraIndicators, previous.doraIndicators)) throw new Error("Dora indicators regressed or reordered");
  if (!hasPrefix(current.ownDiscards, previous.ownDiscards)) throw new Error("Own river regressed or reordered");
  for (const prior of previous.opponentDiscards) {
    const next = current.opponentDiscards.find((opponent) => opponent.seat === prior.seat);
    if (!next || !hasPrefix(next.discards, prior.discards)) throw new Error(`River regressed or reordered for ${prior.seat}`);
  }
  if (!hasPrefix(current.ownMeldTiles, previous.ownMeldTiles)) throw new Error("Own meld evidence regressed or reordered");
  if (previous.ownRiichiDeclared && !current.ownRiichiDeclared) throw new Error("Own riichi evidence regressed");
  for (const prior of previous.opponentDiscards) {
    const next = current.opponentDiscards.find((opponent) => opponent.seat === prior.seat);
    if (prior.riichiDeclared && !next?.riichiDeclared) throw new Error(`Riichi evidence regressed for ${prior.seat}`);
  }
}

async function normalizedCandidateImage(
  screenshot: string | Buffer,
  candidate: RegionCandidate,
  region: PublicTileRegion,
): Promise<Buffer> {
  return sharp(screenshot)
    .extract({ left: candidate.x, top: candidate.y, width: candidate.width, height: candidate.height })
    .rotate(region.rotationToUpright)
    .png()
    .toBuffer();
}

/**
 * Classifies candidates from calibrated public regions. Detection completeness
 * is intentionally not inferred from these results; callers must validate tile
 * counts and temporal consistency before assigning publicStateConfidence.
 */
export async function recognizeConfiguredPublicTiles(
  screenshot: string | Buffer,
  layout: ScreenLayout,
  templateDirectory: string,
  options: PublicTileRecognitionOptions = {},
): Promise<Partial<Record<PublicTileRegionName, PublicTileRecognitionRegion>>> {
  const minimumConfidence = options.minimumConfidence ?? layout.minimumTileConfidence;
  const minimumMargin = options.minimumMargin ?? 0.01;
  const [detections, templates] = await Promise.all([
    detectConfiguredPublicRegions(screenshot, layout, options),
    loadTemplates(templateDirectory),
  ]);
  const entries = Object.entries(detections) as Array<[PublicTileRegionName, NonNullable<(typeof detections)[PublicTileRegionName]>]>;
  const output = await Promise.all(entries.map(async ([name, detection]) => {
    const region = layout.publicTileRegions?.[name];
    if (!region) throw new Error(`Missing public tile region: ${name}`);
    const recognized = await Promise.all(detection.candidates.map(async (candidate): Promise<RecognizedPublicTile> => {
      const image = await normalizedCandidateImage(screenshot, candidate, region);
      const match = await classifyTile(image, templates);
      const ambiguityMargin = match.confidence - match.runnerUpConfidence;
      return {
        ...candidate,
        tile: match.tile,
        confidence: match.confidence,
        runnerUpConfidence: match.runnerUpConfidence,
        ambiguityMargin,
        safe: match.confidence >= minimumConfidence && ambiguityMargin >= minimumMargin,
      };
    }));
    return [name, {
      backend: "template" as const,
      candidateCount: detection.candidates.length,
      recognized,
      classificationSafe: recognized.length > 0 && detection.gridValid !== false && recognized.every((tile) => tile.safe),
      rotationToUpright: region.rotationToUpright,
    }] as const;
  }));
  return Object.fromEntries(output);
}

export interface PublicVitClassifier {
  readonly backend?: "vit" | "hybrid";
  classifyTileImages(images: Buffer[]): Promise<VitTilePrediction[]>;
}

/** Batch-classifies public tile candidates with the persistent ViT worker. */
export async function recognizeConfiguredPublicTilesWithVit(
  screenshot: string | Buffer,
  layout: ScreenLayout,
  classifier: PublicVitClassifier,
  options: PublicTileRecognitionOptions = {},
): Promise<Partial<Record<PublicTileRegionName, PublicTileRecognitionRegion>>> {
  const minimumConfidence = options.minimumConfidence ?? layout.minimumVitConfidence;
  const minimumMargin = options.minimumMargin ?? layout.minimumVitMargin;
  const detections = await detectConfiguredPublicRegions(screenshot, layout, {
    luminanceThreshold: options.luminanceThreshold ?? 190,
    ...options,
  });
  const entries = Object.entries(detections) as Array<[PublicTileRegionName, NonNullable<(typeof detections)[PublicTileRegionName]>]>;
  const jobs: Array<{ name: PublicTileRegionName; candidate: RegionCandidate; region: PublicTileRegion }> = [];
  for (const [name, detection] of entries) {
    const region = layout.publicTileRegions?.[name];
    if (!region) throw new Error(`Missing public tile region: ${name}`);
    for (const candidate of detection.candidates) jobs.push({ name, candidate, region });
  }
  const images = await Promise.all(jobs.map((job) => normalizedCandidateImage(screenshot, job.candidate, job.region)));
  const predictions = images.length > 0 ? await classifier.classifyTileImages(images) : [];
  if (predictions.length !== jobs.length) throw new Error("Model public classifier returned the wrong prediction count");

  const grouped = new Map<PublicTileRegionName, RecognizedPublicTile[]>();
  jobs.forEach((job, index) => {
    const prediction = predictions[index]!;
    const ambiguityMargin = prediction.confidence - prediction.runnerUpConfidence;
    const recognized: RecognizedPublicTile = {
      ...job.candidate,
      tile: prediction.tile,
      confidence: prediction.confidence,
      runnerUpConfidence: prediction.runnerUpConfidence,
      ambiguityMargin,
      safe: prediction.confidence >= minimumConfidence && ambiguityMargin >= minimumMargin,
    };
    grouped.set(job.name, [...(grouped.get(job.name) ?? []), recognized]);
  });

  return Object.fromEntries(entries.map(([name, detection]) => {
    const region = layout.publicTileRegions?.[name];
    if (!region) throw new Error(`Missing public tile region: ${name}`);
    const recognized = grouped.get(name) ?? [];
    return [name, {
      backend: classifier.backend ?? "vit",
      candidateCount: detection.candidates.length,
      recognized,
      classificationSafe: recognized.length > 0 && detection.gridValid !== false && recognized.every((tile) => tile.safe),
      rotationToUpright: region.rotationToUpright,
    }] as const;
  }));
}
