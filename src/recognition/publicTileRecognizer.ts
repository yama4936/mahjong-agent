import sharp from "sharp";
import type { PublicGameState } from "../game/state.js";
import { normalizeTile, suitRank, tileIndex, type GameTile } from "../game/tiles.js";
import type { PublicTileRegion, PublicTileRegionName, ScreenLayout } from "./layout.js";
import { classifyTile, loadTemplates } from "./templateMatcher.js";
import { detectConfiguredPublicRegions, type RegionCandidate, type RegionDetectionOptions } from "./regionDetector.js";
import type { VitTilePrediction } from "./vitRecognizer.js";
import { isKnownSixSevenPinConfusion } from "./hybridTileRecognizer.js";
import { normalizeRedManNumeral, type RedManNumeralEvidence } from "./redManNumeral.js";

export interface RecognizedPublicTile extends RegionCandidate {
  tile: GameTile;
  confidence: number;
  runnerUpConfidence: number;
  ambiguityMargin: number;
  safe: boolean;
  redNumeralEvidence?: RedManNumeralEvidence;
  whitePonRotationEvidence?: {
    scope: "left_sideways_white_pon_only";
    additionalRotation: 180;
    originalConfidence: number;
    originalRunnerUpConfidence: number;
    originalAmbiguityMargin: number;
  };
}

export interface PublicTileRecognitionRegion {
  backend: "template" | "vit" | "hybrid";
  candidateCount: number;
  recognized: RecognizedPublicTile[];
  classificationSafe: boolean;
  rotationToUpright: 0 | 90 | 180 | 270;
}

export interface PublicTileRecognitionOptions extends RegionDetectionOptions {
  retryDiscardBoundaries?: boolean;
  retryRightRedMeld?: boolean;
  retryRightChiMeld?: boolean;
  retryLeftWhitePon?: boolean;
  minimumConfidence?: number;
  minimumMargin?: number;
}

export interface PublicTileObservation {
  doraIndicators: GameTile[];
  ownDiscards: GameTile[];
  ownDiscardsObserved?: boolean;
  ownRiichiDeclared?: boolean;
  ownMelds?: RecognizedMeld[];
  ownMeldsObserved?: boolean;
  opponentDiscards: Array<{
    seat: "east" | "south" | "west" | "north";
    discards: GameTile[];
    discardsObserved?: boolean;
    riichiDeclared?: boolean;
    melds?: RecognizedMeld[];
    meldsObserved?: boolean;
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
  if (!region?.classificationSafe) return false;
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

function inferAdjacentMelds(tiles: RecognizedPublicTile[]): RecognizedMeld[] {
  const partitions: RecognizedMeld[][] = [];
  function search(offset: number, groups: RecognizedMeld[]): void {
    if (partitions.length > 1) return;
    if (offset === tiles.length) { partitions.push(groups); return; }
    if (groups.length === 4) return;
    for (const size of [3, 4]) {
      const slice = tiles.slice(offset, offset + size);
      if (slice.length !== size) continue;
      const meld = inferMeld(slice);
      if (meld) search(offset + size, [...groups, meld]);
    }
  }
  search(0, []);
  return partitions.length === 1 ? partitions[0]! : [];
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
  return groups.flatMap(inferAdjacentMelds);
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
  const riverObserved = (name: PublicTileRegionName) => {
    const region = recognition[name];
    return Boolean(region?.classificationSafe && region.candidateCount === region.recognized.length
      && region.recognized.every(tile => tile.safe));
  };
  const meldEvidence = (name: PublicTileRegionName) => {
    const region = recognition[name];
    const melds = recognizeExposedMelds(region);
    return { melds, meldsObserved: Boolean(region && (
      region.candidateCount === 0
      || (region.classificationSafe
        && region.candidateCount === region.recognized.length
        && melds.reduce((count, meld) => count + meld.tiles.length, 0) === region.recognized.length)
    )) };
  };
  const opponentDiscards = [
    { seat: seats[(ownIndex + 1) % 4]!, discards: safeTiles("rightDiscards"), discardsObserved: riverObserved("rightDiscards"), riichiDeclared: hasSidewaysRiichiTile(recognition.rightDiscards), ...meldEvidence("rightMelds") },
    { seat: seats[(ownIndex + 2) % 4]!, discards: safeTiles("oppositeDiscards"), discardsObserved: riverObserved("oppositeDiscards"), riichiDeclared: hasSidewaysRiichiTile(recognition.oppositeDiscards), ...meldEvidence("oppositeMelds") },
    { seat: seats[(ownIndex + 3) % 4]!, discards: safeTiles("leftDiscards"), discardsObserved: riverObserved("leftDiscards"), riichiDeclared: hasSidewaysRiichiTile(recognition.leftDiscards), ...meldEvidence("leftMelds") },
  ];
  const ownMelds = recognizeExposedMelds(recognition.ownMelds);
  // Do not publish individually plausible crops as known tiles unless every
  // crop belongs to a complete legal meld.  In particular, text/buttons in a
  // miscalibrated region must not become a phantom honor kan in the cache.
  const ownMeldTiles = ownMelds.flatMap((meld) => meld.tiles);
  const ownMeldRegion = recognition.ownMelds;
  const ownMeldsObserved = Boolean(ownMeldRegion && (
    ownMeldRegion.candidateCount === 0
    || (ownMeldRegion.classificationSafe
      && ownMeldRegion.candidateCount === ownMeldRegion.recognized.length
      && ownMeldTiles.length === ownMeldRegion.recognized.length)
  ));
  const opponentMeldTiles = opponentDiscards.flatMap((opponent) => opponent.melds.flatMap((meld) => meld.tiles));
  const otherVisibleTiles = [...opponentDiscards.flatMap((opponent) => opponent.discards), ...ownMeldTiles, ...opponentMeldTiles];
  return {
    doraIndicators,
    ownDiscards,
    ownDiscardsObserved: riverObserved("ownDiscards"),
    ownRiichiDeclared: hasSidewaysRiichiTile(recognition.ownDiscards),
    ownMelds,
    ownMeldsObserved,
    opponentDiscards,
    ownMeldTiles,
    allMeldTiles: [...ownMeldTiles, ...opponentMeldTiles],
    otherVisibleTiles,
    acceptedTiles: doraIndicators.length + ownDiscards.length + otherVisibleTiles.length,
    detectedCandidates: Object.values(recognition).reduce((sum, region) => sum + (region?.candidateCount ?? 0), 0),
    complete: false,
  };
}

/** Counts remain lower bounds when meld regions are missing or only partially decoded. */
export function opponentStatesFromObservation(
  observation: PublicTileObservation,
  prior: PublicGameState["opponents"] = [],
): PublicGameState["opponents"] {
  return observation.opponentDiscards.map((opponent) => {
    const previous = prior.find((item) => item.seat === opponent.seat);
    const observedCount = opponent.melds?.length ?? 0;
    const previousCount = previous?.openMelds ?? 0;
    const confirmedEmpty = opponent.meldsObserved === true && observedCount === 0;
    const nonRegressingObservation = opponent.meldsObserved === true && observedCount >= previousCount;
    return {
      seat: opponent.seat, discards: opponent.discards,
      riichi: Boolean(opponent.riichiDeclared || previous?.riichi),
      ...((opponent.riichiDeclared || previous?.riichi) && previous?.postRiichiSafeTiles
        ? { postRiichiSafeTiles: previous.postRiichiSafeTiles } : {}),
      openMelds: confirmedEmpty ? 0 : Math.max(observedCount, previousCount),
      openMeldsObserved: confirmedEmpty || nonRegressingObservation,
      melds: confirmedEmpty ? []
        : observedCount >= (previous?.melds?.length ?? 0) ? opponent.melds : previous?.melds,
    };
  });
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
    .rotate((region.rotationToUpright + (candidate.sideways ? 90 : 0)) % 360)
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

  // A tight bright-component crop can cut off the edge of a newly discarded
  // tile. Two reviewed own-river frames classified East as North and 8m as
  // 6m at 0.53-0.56 confidence. Four pixels of surrounding table restored
  // both faces, while padding every crop degraded a correctly read red five.
  // A reviewed 2m river face also reads as 8m at 0.75, above the generic
  // padding trigger. Do not publish this measured confusion as safe without
  // a strong independent padded-face classification (2m or genuine 8m).
  const ambiguousOwnMan = new Set(jobs.flatMap((job, index) => (
    classifier.backend === "hybrid" && job.name === "ownDiscards"
    && job.region.rotationToUpright === 0 && !job.candidate.sideways
    && predictions[index]!.tile === "8m" && predictions[index]!.runnerUpTile === "2m"
    && predictions[index]!.confidence < 0.9 ? [index] : []
  )));
  const unconfirmedOwnMan = new Set(ambiguousOwnMan);
  const weakOwnRiver = jobs.flatMap((job, index) => (
    job.name === "ownDiscards" && (predictions[index]!.confidence < 0.7 || ambiguousOwnMan.has(index)) ? [index] : []
  ));
  if (weakOwnRiver.length > 0) {
    const { width, height } = await sharp(screenshot).metadata();
    if (!width || !height) throw new Error("Public screenshot has no dimensions");
    const paddedImages = await Promise.all(weakOwnRiver.map((index) => {
      const { candidate, region } = jobs[index]!;
      const left = Math.max(0, candidate.x - 4);
      const top = Math.max(0, candidate.y - 4);
      const right = Math.min(width, candidate.x + candidate.width + 4);
      const bottom = Math.min(height, candidate.y + candidate.height + 4);
      return sharp(screenshot).extract({ left, top, width: right - left, height: bottom - top })
        .rotate((region.rotationToUpright + (candidate.sideways ? 90 : 0)) % 360).png().toBuffer();
    }));
    const paddedPredictions = await classifier.classifyTileImages(paddedImages);
    if (paddedPredictions.length !== weakOwnRiver.length) throw new Error("Model public retry returned the wrong prediction count");
    weakOwnRiver.forEach((index, retryIndex) => {
      const original = predictions[index]!;
      const padded = paddedPredictions[retryIndex]!;
      if (ambiguousOwnMan.has(index)) {
        if ((padded.tile === "2m" || padded.tile === "8m") && padded.confidence >= Math.max(0.95, minimumConfidence)
          && padded.confidence - padded.runnerUpConfidence >= Math.max(0.9, minimumMargin)
          && padded.confidence - original.confidence >= 0.15) {
          predictions[index] = padded;
          unconfirmedOwnMan.delete(index);
        }
        return;
      }
      if (padded.confidence >= 0.8 && padded.confidence - original.confidence >= 0.15
        && padded.confidence - padded.runnerUpConfidence >= 0.5) predictions[index] = padded;
    });
  }

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
      // The Hybrid model's measured 6p/7p confusion applies to public tiles
      // too. A false 6p in an opponent river otherwise becomes genbutsu.
      safe: !unconfirmedOwnMan.has(index)
        && !(classifier.backend === "hybrid" && isKnownSixSevenPinConfusion(prediction))
        && prediction.confidence >= minimumConfidence && ambiguityMargin >= minimumMargin,
    };
    grouped.set(job.name, [...(grouped.get(job.name) ?? []), recognized]);
  });

  const result: Partial<Record<PublicTileRegionName, PublicTileRecognitionRegion>> = Object.fromEntries(entries.map(([name, detection]) => {
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
  // One reviewed sideways white face includes enough grey side/table to read
  // P at .482, while the same pixels rotated 180 degrees read P at .999.
  // White is 180-degree symmetric, but a blank patch also scores as P. Require
  // two separately strong upright white anchors and a unique complete pon
  // partition before this single-image retry. Never infer a fourth white/kan.
  const leftWhite = result.leftMelds;
  const leftWhiteRegion = layout.publicTileRegions?.leftMelds;
  if (options.retryLeftWhitePon !== false && classifier.backend === "hybrid"
    && leftWhite?.rotationToUpright === 270 && leftWhiteRegion?.rotationToUpright === 270
    && detections.leftMelds?.gridValid !== false
    && !leftWhite.classificationSafe && leftWhite.candidateCount === leftWhite.recognized.length) {
    const uncertain = leftWhite.recognized.filter(tile => !tile.safe);
    const target = uncertain.length === 1 ? uncertain[0] : undefined;
    const whites = leftWhite.recognized.filter(tile => tile.tile === "P");
    const ordered = [...leftWhite.recognized].sort((a, b) => b.y - a.y || b.x - a.x);
    const whitePositions = whites.map(tile => ordered.indexOf(tile)).sort((a, b) => a - b);
    const contiguousWhitePon = whites.length === 3 && whitePositions[2]! - whitePositions[0]! === 2;
    const anchored = target && whites.filter(tile => tile !== target && tile.safe && tile.sideways === false
      && tile.confidence >= 0.99 && tile.ambiguityMargin >= 0.99).length === 2;
    if (target && target.tile === "P" && target.sideways === true && target.width > target.height
      && target.height >= 20 && target.confidence >= 0.4 && target.confidence < 0.5
      && target.ambiguityMargin >= Math.max(0.05, minimumMargin) && contiguousWhitePon && anchored) {
      // This hypothetical partition is only an admission check. Its weak
      // target is never published without the subsequent image evidence.
      const provisional = { ...leftWhite, classificationSafe: true,
        recognized: leftWhite.recognized.map(tile => tile === target ? { ...tile, safe: true } : tile) };
      const partition = recognizeExposedMelds(provisional);
      if (partition.reduce((sum, meld) => sum + meld.tiles.length, 0) === leftWhite.candidateCount
        && partition.some(meld => meld.type === "pon" && meld.tiles.every(tile => tile === "P"))) {
        const original = await normalizedCandidateImage(screenshot, target, leftWhiteRegion);
        const retryImage = await sharp(original).rotate(180).png().toBuffer();
        const retried = await classifier.classifyTileImages([retryImage]);
        if (retried.length !== 1) throw new Error("Model left white pon retry returned the wrong prediction count");
        const retry = retried[0]!;
        const margin = retry.confidence - retry.runnerUpConfidence;
        if (retry.tile === "P" && retry.confidence >= Math.max(0.99, minimumConfidence)
          && retry.confidence <= 1 && retry.runnerUpConfidence >= 0
          && margin >= Math.max(0.99, minimumMargin) && retry.confidence - target.confidence >= 0.45) {
          const refined = { ...leftWhite, classificationSafe: true,
            recognized: leftWhite.recognized.map(tile => tile === target ? { ...tile,
              confidence: retry.confidence, runnerUpConfidence: retry.runnerUpConfidence,
              ambiguityMargin: margin, safe: true,
              whitePonRotationEvidence: { scope: "left_sideways_white_pon_only" as const,
                additionalRotation: 180 as const, originalConfidence: tile.confidence,
                originalRunnerUpConfidence: tile.runnerUpConfidence, originalAmbiguityMargin: tile.ambiguityMargin },
            } : tile) };
          const melds = recognizeExposedMelds(refined);
          if (melds.reduce((sum, meld) => sum + meld.tiles.length, 0) === leftWhite.candidateCount
            && melds.some(meld => meld.type === "pon" && meld.tiles.every(tile => tile === "P"))) result.leftMelds = refined;
        }
      }
    }
  }
  // Two reviewed upside-down chi frames lose the 7m as a weak 6m in a
  // tight face crop. Padding only the original top edge restores its glyph
  // without adding the grey 3D side below it. Do not force a legal meld from
  // the labels: require independent, substantially stronger image evidence.
  const opposite = result.oppositeMelds;
  const oppositeRegion = layout.publicTileRegions?.oppositeMelds;
  if (classifier.backend === "hybrid" && oppositeRegion?.rotationToUpright === 180
    && opposite?.classificationSafe && opposite.candidateCount === 3
    && opposite.recognized.length === 3 && recognizeExposedMelds(opposite).length === 0) {
    const retryIndexes = jobs.flatMap((job, index) => (
      job.name === "oppositeMelds" && !job.candidate.sideways
      && job.candidate.y - 4 >= oppositeRegion.y
      && predictions[index]!.tile === "6m" && predictions[index]!.runnerUpTile === "7m"
      && predictions[index]!.confidence < 0.9 ? [index] : []
    ));
    if (retryIndexes.length > 0) {
      const images = await Promise.all(retryIndexes.map((index) => {
        const { candidate } = jobs[index]!;
        return sharp(screenshot).extract({ left: candidate.x, top: candidate.y - 4,
          width: candidate.width, height: candidate.height + 4 }).rotate(180).png().toBuffer();
      }));
      const retried = await classifier.classifyTileImages(images);
      if (retried.length !== retryIndexes.length) throw new Error("Model meld retry returned the wrong prediction count");
      const replacements = new Map<RegionCandidate, RecognizedPublicTile>();
      retryIndexes.forEach((index, retryIndex) => {
        const original = predictions[index]!;
        const retry = retried[retryIndex]!;
        const margin = retry.confidence - retry.runnerUpConfidence;
        if (retry.tile === "7m" && retry.confidence >= Math.max(0.95, minimumConfidence)
          && margin >= Math.max(0.9, minimumMargin) && retry.confidence - original.confidence >= 0.15) {
          replacements.set(jobs[index]!.candidate, { ...jobs[index]!.candidate, tile: retry.tile,
            confidence: retry.confidence, runnerUpConfidence: retry.runnerUpConfidence,
            ambiguityMargin: margin, safe: true });
        }
      });
      const candidates = jobs.filter(job => job.name === "oppositeMelds").map(job => job.candidate);
      const refined = { ...opposite, recognized: opposite.recognized.map((tile, index) =>
        replacements.get(candidates[index]!) ?? tile) };
      if (replacements.size > 0 && recognizeExposedMelds(refined).length === 1) result.oppositeMelds = refined;
    }
  }
  // The grey 3D side of a right player's sideways 8m can dominate its
  // bright-component crop. Retry only a weak 6m beside two independently
  // strong 8m faces in an otherwise unreadable meld region. Removing the
  // left fifth restores the face; acceptance still requires strong model
  // evidence and a complete legal partition, without changing tile bounds.
  const right = result.rightMelds;
  if (classifier.backend === "hybrid" && right?.rotationToUpright === 90
    && right.classificationSafe && right.candidateCount === right.recognized.length
    && recognizeExposedMelds(right).length === 0) {
    const ordered = [...right.recognized].sort((a, b) => a.y - b.y);
    const retryIndexes = jobs.flatMap((job, index) => {
      const original = predictions[index]!;
      if (job.name !== "rightMelds" || !job.candidate.sideways
        || job.candidate.width <= job.candidate.height || job.candidate.height < 20
        || original.tile !== "6m" || original.runnerUpTile !== "8m" || original.confidence >= 0.9) return [];
      const position = ordered.findIndex(tile => tile.x === job.candidate.x && tile.y === job.candidate.y);
      const anchored = [position - 2, position - 1, position].some(start => {
        const group = ordered.slice(Math.max(0, start), start + 3);
        return start >= 0 && group.length === 3 && group.filter(tile => tile.tile === "8m"
          && !tile.sideways && tile.confidence >= 0.95 && tile.ambiguityMargin >= 0.9).length === 2;
      });
      return anchored ? [index] : [];
    });
    if (retryIndexes.length === 1) {
      const index = retryIndexes[0]!;
      const { candidate } = jobs[index]!;
      const trim = Math.round(candidate.width / 5);
      const image = await sharp(screenshot).extract({ left: candidate.x + trim, top: candidate.y,
        width: candidate.width - trim, height: candidate.height }).rotate(180).png().toBuffer();
      const retried = await classifier.classifyTileImages([image]);
      if (retried.length !== 1) throw new Error("Model right meld retry returned the wrong prediction count");
      const retry = retried[0]!;
      const margin = retry.confidence - retry.runnerUpConfidence;
      if (retry.tile === "8m" && retry.confidence >= Math.max(0.95, minimumConfidence)
        && margin >= Math.max(0.9, minimumMargin) && retry.confidence - predictions[index]!.confidence >= 0.15) {
        const regionIndex = jobs.filter(job => job.name === "rightMelds").findIndex(job => job.candidate === candidate);
        const refined = { ...right, recognized: right.recognized.map((tile, i) => i === regionIndex
          ? { ...tile, tile: retry.tile, confidence: retry.confidence, runnerUpConfidence: retry.runnerUpConfidence,
            ambiguityMargin: margin, safe: true } : tile) };
        const melds = recognizeExposedMelds(refined);
        if (melds.reduce((count, meld) => count + meld.tiles.length, 0) === right.candidateCount) result.rightMelds = refined;
      }
    }
  }
  // A reviewed right 678m chi reads its sideways 8m as 6m when the grey
  // side dominates the crop. Two different face trims must independently
  // agree on 8m, beside already accepted upright 6m/7m anchors. A legal chi
  // alone is never evidence to relabel a tile; retain original coordinates.
  const rightChi = result.rightMelds;
  if (options.retryRightChiMeld !== false && classifier.backend === "hybrid"
    && rightChi?.rotationToUpright === 90 && rightChi.classificationSafe
    && rightChi.candidateCount === rightChi.recognized.length
    && recognizeExposedMelds(rightChi).length === 0) {
    const ordered = [...rightChi.recognized].sort((a, b) => a.y - b.y);
    const targets = jobs.flatMap((job, index) => {
      const original = predictions[index]!;
      if (job.name !== "rightMelds" || !job.candidate.sideways
        || job.candidate.width <= job.candidate.height || job.candidate.height < 20
        || original.tile !== "6m" || original.runnerUpTile !== "8m" || original.confidence >= 0.9) return [];
      const position = ordered.findIndex(tile => tile.x === job.candidate.x && tile.y === job.candidate.y);
      const anchors = ordered.slice(Math.max(0, position - 2), position);
      return position >= 2 && anchors.length === 2 && anchors.every(tile => !tile.sideways && tile.safe
        && tile.confidence >= 0.85 && tile.ambiguityMargin >= 0.7)
        && anchors.some(tile => tile.confidence >= 0.95 && tile.ambiguityMargin >= 0.9)
        && anchors.map(tile => tile.tile).sort().join(",") === "6m,7m" ? [index] : [];
    });
    if (targets.length === 1) {
      const index = targets[0]!, candidate = jobs[index]!.candidate;
      const images = await Promise.all([[0.2, 0], [0.1, 0.1]].map(async ([leftFraction, bottomFraction]) => {
        const leftTrim = Math.round(candidate.width * leftFraction!);
        const bottomTrim = Math.round(candidate.height * bottomFraction!);
        return sharp(screenshot).extract({ left: candidate.x + leftTrim, top: candidate.y,
          width: candidate.width - leftTrim, height: candidate.height - bottomTrim }).rotate(180).png().toBuffer();
      }));
      const retried = await classifier.classifyTileImages(images);
      if (retried.length !== 2) throw new Error("Model right chi retry returned the wrong prediction count");
      if (retried.every(tile => tile.tile === "8m" && tile.confidence >= Math.max(0.95, minimumConfidence)
        && tile.confidence - tile.runnerUpConfidence >= Math.max(0.9, minimumMargin)
        && tile.confidence - predictions[index]!.confidence >= 0.15)) {
        const confidence = Math.min(...retried.map(tile => tile.confidence));
        const runnerUpConfidence = Math.max(...retried.map(tile => tile.runnerUpConfidence));
        const refined = { ...rightChi, recognized: rightChi.recognized.map(tile =>
          tile.x === candidate.x && tile.y === candidate.y ? { ...tile, tile: "8m" as const,
            confidence, runnerUpConfidence, ambiguityMargin: confidence - runnerUpConfidence, safe: true } : tile) };
        const melds = recognizeExposedMelds(refined);
        if (melds.reduce((count, meld) => count + meld.tiles.length, 0) === rightChi.candidateCount) result.rightMelds = refined;
      }
    }
  }
  // Reviewed right red-five faces lose confidence from side/background ink.
  // Confirm the red numeral separately, then classify the five family with
  // normalized ink. Any other weak face must independently recover as well.
  const rightRed = result.rightMelds;
  const rightJobs = jobs.filter(job => job.name === "rightMelds");
  if (options.retryRightRedMeld !== false && classifier.backend === "hybrid" && rightRed?.rotationToUpright === 90
    && !rightRed.classificationSafe && detections.rightMelds?.gridValid !== false
    && rightRed.candidateCount === 3 && rightRed.recognized.length === 3) {
    const fiveIndexes = rightRed.recognized.flatMap((tile, i) =>
      tile.tile === "5m" && !tile.sideways && tile.confidence < 0.7 ? [i] : []);
    const fiveIndex = fiveIndexes.length === 1 ? fiveIndexes[0]! : -1;
    const otherWeak = rightRed.recognized.flatMap((tile, i) => !tile.safe && i !== fiveIndex ? [i] : []);
    const fourIndex = otherWeak.length === 1 ? otherWeak[0]! : -1;
    const fourTile = fourIndex >= 0 ? rightRed.recognized[fourIndex] : undefined;
    const supportedWeakFaces = otherWeak.length === 0 || (otherWeak.length === 1 && fourTile?.tile === "4m"
      && fourTile.sideways && fourTile.confidence < 0.7);
    const strongAnchor = rightRed.recognized.some(tile => tile.safe && tile.confidence >= 0.95 && tile.ambiguityMargin >= 0.9);
    if (fiveIndex >= 0 && supportedWeakFaces && strongAnchor) {
      const five = rightJobs[fiveIndex]!.candidate;
      const four = fourIndex >= 0 ? rightJobs[fourIndex]!.candidate : undefined;
      const leftTrim = Math.max(1, Math.round(five.width * 0.03));
      const bottomTrim = Math.max(1, Math.round(five.height * 0.12));
      if (five.height >= 20 && five.width > five.height
        && (!four || (four.height >= 20 && four.width > four.height))) {
        const fiveImage = await sharp(screenshot).extract({ left: five.x + leftTrim, top: five.y,
          width: five.width - leftTrim, height: five.height - bottomTrim }).rotate(90).png().toBuffer();
        const normalized = await normalizeRedManNumeral(fiveImage);
        if (normalized) {
          const retryImages = [normalized.image];
          if (four) {
            const trim = Math.round(four.width / 5);
            retryImages.push(await sharp(screenshot).extract({ left: four.x + trim, top: four.y,
              width: four.width - trim, height: four.height }).rotate(180).png().toBuffer());
          }
          const retried = await classifier.classifyTileImages(retryImages);
          if (retried.length !== retryImages.length) throw new Error("Model right red meld retry returned the wrong prediction count");
          const accepted = retried.every((prediction, index) => prediction.tile === (index === 0 ? "5m" : "4m")
            && prediction.confidence >= Math.max(0.95, minimumConfidence)
            && prediction.confidence - prediction.runnerUpConfidence >= Math.max(0.9, minimumMargin)
            && prediction.confidence - rightRed.recognized[index === 0 ? fiveIndex : fourIndex]!.confidence >= 0.15);
          if (accepted) {
            const refined = { ...rightRed, classificationSafe: true, recognized: rightRed.recognized.map((tile, i) => {
              const prediction = i === fiveIndex ? retried[0] : i === fourIndex ? retried[1] : undefined;
              return prediction ? { ...tile, tile: i === fiveIndex ? "0m" as const : "4m" as const,
                confidence: prediction.confidence, runnerUpConfidence: prediction.runnerUpConfidence,
                ambiguityMargin: prediction.confidence - prediction.runnerUpConfidence, safe: true,
                ...(i === fiveIndex ? { redNumeralEvidence: normalized.evidence } : {}) } : tile;
            }) };
            if (recognizeExposedMelds(refined).length === 1) result.rightMelds = refined;
          }
        }
      }
    }
  }
  if (options.retryDiscardBoundaries !== false) {
    for (const [name, detection] of entries) {
      const region = layout.publicTileRegions?.[name];
      const original = result[name];
      if (!region || !original || region.detectionMode !== "discard_grid" || !name.endsWith("Discards")
        || original.classificationSafe || detection.gridValid !== true || original.recognized.length === 0) continue;
      const threshold = region.luminanceThreshold ?? options.luminanceThreshold ?? 190;
      if (threshold > 210) continue;
      const retry = await recognizeConfiguredPublicTilesWithVit(screenshot,
        { ...layout, publicTileRegions: { [name]: { ...region, luminanceThreshold: threshold + 10 } } },
        classifier, { ...options, retryDiscardBoundaries: false });
      const refined = retry[name];
      // Never remove candidates or contradict an already accepted tile.
      if (refined?.classificationSafe && refined.candidateCount === original.candidateCount
        && original.recognized.every((tile, index) => !tile.safe || tile.tile === refined.recognized[index]?.tile)) {
        result[name] = refined;
      }
    }
  }
  return result;
}
