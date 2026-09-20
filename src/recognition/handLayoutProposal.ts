import sharp from "sharp";
import { layoutSchema, type Rect, type ScreenLayout } from "./layout.js";
import { detectBrightTileCandidates, type RegionCandidate } from "./regionDetector.js";

export interface HandLayoutProposal {
  viewport: { width: number; height: number };
  handSlots: Rect[];
  drawSlot: Rect;
  clickPoints: Array<{ x: number; y: number }>;
  evidence: {
    detectedTiles: number;
    luminanceThreshold: number;
    medianWidth: number;
    medianHeight: number;
    medianGap: number;
    drawGap: number;
    rowBottomSpread: number;
  };
  confidence: number;
  requiresHoldoutValidation: true;
}

/**
 * Turns a detected hand row into an Advisor-safe runtime layout. This never
 * carries an Auto certificate: live detection is only the first calibration
 * step and still needs independent holdout evidence before clicks are allowed.
 */
export function layoutFromHandProposal(
  proposal: HandLayoutProposal,
  thresholds: Partial<Pick<ScreenLayout,
    "minimumTileConfidence" | "minimumTilePresence" | "minimumVitConfidence" | "minimumVitMargin"
  >> = {},
): ScreenLayout {
  const scaleX = proposal.viewport.width / 1920;
  const scaleY = proposal.viewport.height / 1080;
  const scaledRegion = (x: number, y: number, width: number, height: number, rotationToUpright: 0 | 90 | 180 | 270, detectionMode?: "discard_grid") => ({
    x: Math.round(x * scaleX),
    y: Math.round(y * scaleY),
    width: Math.round(width * scaleX),
    height: Math.round(height * scaleY),
    rotationToUpright,
    ...(detectionMode ? { detectionMode } : {}),
  });
  return layoutSchema.parse({
    viewport: proposal.viewport,
    handSlots: proposal.handSlots,
    drawSlot: proposal.drawSlot,
    clickPoints: proposal.clickPoints,
    minimumTileConfidence: thresholds.minimumTileConfidence ?? 0.98,
    minimumTilePresence: thresholds.minimumTilePresence ?? 0.12,
    minimumVitConfidence: thresholds.minimumVitConfidence ?? 0.5,
    minimumVitMargin: thresholds.minimumVitMargin ?? 0.05,
    publicTileRegions: {
      ownDiscards: scaledRegion(770, 535, 390, 225, 0, "discard_grid"),
      rightDiscards: scaledRegion(1115, 285, 305, 250, 90, "discard_grid"),
      oppositeDiscards: scaledRegion(770, 150, 390, 190, 180, "discard_grid"),
      leftDiscards: scaledRegion(500, 285, 305, 250, 270, "discard_grid"),
      ownMelds: scaledRegion(732, 759, 200, 84, 0),
    },
  });
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle]! : (sorted[middle - 1]! + sorted[middle]!) / 2;
}

function tileLike(candidate: RegionCandidate): boolean {
  const aspect = candidate.width / candidate.height;
  return aspect >= 0.3 && aspect <= 0.9 && candidate.fillRatio >= 0.45;
}

function rowCandidates(candidates: RegionCandidate[]): RegionCandidate[][] {
  const rows: RegionCandidate[][] = [];
  for (const seed of candidates) {
    const seedBottom = seed.y + seed.height;
    const row = candidates.filter((candidate) => {
      const bottom = candidate.y + candidate.height;
      const heightRatio = candidate.height / seed.height;
      return Math.abs(bottom - seedBottom) <= Math.max(8, seed.height * 0.18) && heightRatio >= 0.72 && heightRatio <= 1.28;
    }).sort((a, b) => a.x - b.x);
    if (!rows.some((existing) => existing.length === row.length && existing.every((item, index) => item === row[index]))) rows.push(row);
  }
  return rows;
}

function scoreRow(row: RegionCandidate[], viewportHeight: number, tileCounts: readonly number[]): number {
  if (!tileCounts.includes(row.length)) return Number.NEGATIVE_INFINITY;
  const heights = row.map((tile) => tile.height);
  const widths = row.map((tile) => tile.width);
  const heightVariation = (Math.max(...heights) - Math.min(...heights)) / median(heights);
  const widthVariation = (Math.max(...widths) - Math.min(...widths)) / median(widths);
  const bottom = median(row.map((tile) => tile.y + tile.height));
  return bottom / viewportHeight * 5 - heightVariation - widthVariation;
}

/** Proposes a 13+draw hand layout from a screenshot; it never certifies Auto. */
export async function proposeHandLayout(screenshot: string | Buffer, tileCounts: readonly number[] = [14]): Promise<HandLayoutProposal> {
  if (tileCounts.some((count) => !Number.isInteger(count) || count < 2 || count > 14)) throw new Error("tileCounts must contain integers from 2 through 14");
  const metadata = await sharp(screenshot).metadata();
  if (!metadata.width || !metadata.height) throw new Error("Screenshot dimensions are unavailable");
  const lowerY = Math.floor(metadata.height * 0.52);
  const thresholds = [210, 190, 170, 150, 130, 120];
  const detections = await Promise.all(thresholds.map(async (luminanceThreshold) => ({
    luminanceThreshold,
    detection: await detectBrightTileCandidates(
      screenshot,
      { x: 0, y: lowerY, width: metadata.width, height: metadata.height - lowerY },
      {
        luminanceThreshold,
        minimumArea: Math.max(180, Math.floor(metadata.width * metadata.height * 0.00018)),
        minimumWidth: Math.max(12, Math.floor(metadata.width * 0.012)),
        minimumHeight: Math.max(30, Math.floor(metadata.height * 0.045)),
        maximumWidth: Math.max(110, Math.floor(metadata.width * 0.08)),
        maximumHeight: Math.max(140, Math.floor(metadata.height * 0.16)),
        maximumAreaFraction: 0.08,
      },
    ),
  })));
  const attempts = detections.map(({ luminanceThreshold, detection }) => {
    const candidates = detection.candidates.filter(tileLike);
    const row = rowCandidates(candidates).sort((a, b) => scoreRow(b, metadata.height!, tileCounts) - scoreRow(a, metadata.height!, tileCounts))[0];
    return { luminanceThreshold, candidates, row, score: row ? scoreRow(row, metadata.height!, tileCounts) : Number.NEGATIVE_INFINITY };
  });
  const selected = attempts.sort((a, b) => b.score - a.score)[0]!;
  const row = selected.row;
  if (!row || !tileCounts.includes(row.length)) {
    const counts = attempts.map((attempt) => `${attempt.luminanceThreshold}:${attempt.candidates.length}`).join(", ");
    throw new Error(`Could not isolate a ${tileCounts.join("/")}-tile hand row (tile-like components by threshold: ${counts})`);
  }

  const gaps = row.slice(1).map((tile, index) => tile.x - (row[index]!.x + row[index]!.width));
  const ordinaryGaps = gaps.slice(0, -1);
  const medianGap = median(ordinaryGaps);
  const drawGap = gaps.at(-1)!;
  if (drawGap < Math.max(medianGap + 2, medianGap * 1.25)) {
    throw new Error(`The 14th tile is not separated enough to identify the draw slot (gap ${drawGap}, baseline ${medianGap})`);
  }
  const bottoms = row.map((tile) => tile.y + tile.height);
  const rowBottomSpread = Math.max(...bottoms) - Math.min(...bottoms);
  const medianHeight = median(row.map((tile) => tile.height));
  const alignmentScore = Math.max(0, 1 - rowBottomSpread / Math.max(1, medianHeight * 0.2));
  const gapScore = Math.min(1, Math.max(0, (drawGap - medianGap) / Math.max(4, median(row.map((tile) => tile.width)) * 0.25)));
  const confidence = Math.min(0.99, 0.55 + alignmentScore * 0.25 + gapScore * 0.19);
  const rects = row.map(({ x, y, width, height }) => ({ x, y, width, height }));
  return {
    viewport: { width: metadata.width, height: metadata.height },
    handSlots: rects.slice(0, -1),
    drawSlot: rects.at(-1)!,
    clickPoints: rects.map((rect) => ({ x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 })),
    evidence: {
      detectedTiles: row.length,
      luminanceThreshold: selected.luminanceThreshold,
      medianWidth: median(row.map((tile) => tile.width)),
      medianHeight,
      medianGap,
      drawGap,
      rowBottomSpread,
    },
    confidence,
    requiresHoldoutValidation: true,
  };
}
