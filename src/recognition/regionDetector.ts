import sharp from "sharp";
import type { PublicTileRegion, PublicTileRegionName, Rect, ScreenLayout } from "./layout.js";

export interface RegionCandidate extends Rect {
  area: number;
  fillRatio: number;
  gridIndex?: number;
  sideways?: boolean;
}

export interface RegionDetection {
  region: Rect;
  candidates: RegionCandidate[];
  gridValid?: boolean;
  gridRows?: number[];
}

export interface RegionDetectionOptions {
  luminanceThreshold?: number;
  minimumArea?: number;
  minimumWidth?: number;
  minimumHeight?: number;
  maximumWidth?: number;
  maximumHeight?: number;
  maximumAreaFraction?: number;
}

/**
 * Finds bright connected components inside a calibrated Mahjong Soul region.
 * This deliberately performs detection only: a component is never promoted to
 * a game tile until a separately calibrated classifier accepts it.
 */
export async function detectBrightTileCandidates(
  screenshot: string | Buffer,
  region: Rect,
  options: RegionDetectionOptions = {},
): Promise<RegionDetection> {
  const luminanceThreshold = options.luminanceThreshold ?? 120;
  const minimumArea = options.minimumArea ?? 200;
  const minimumWidth = options.minimumWidth ?? 8;
  const minimumHeight = options.minimumHeight ?? 12;
  const maximumWidth = options.maximumWidth ?? 110;
  const maximumHeight = options.maximumHeight ?? 110;
  const maximumArea = region.width * region.height * (options.maximumAreaFraction ?? 0.3);
  const { data, info } = await sharp(screenshot)
    .extract({ left: region.x, top: region.y, width: region.width, height: region.height })
    .greyscale()
    .raw()
    .toBuffer({ resolveWithObject: true });
  const size = info.width * info.height;
  const foreground = new Uint8Array(size);
  const visited = new Uint8Array(size);
  for (let index = 0; index < size; index += 1) foreground[index] = data[index]! >= luminanceThreshold ? 1 : 0;

  const candidates: RegionCandidate[] = [];
  const queue = new Int32Array(size);
  for (let start = 0; start < size; start += 1) {
    if (!foreground[start] || visited[start]) continue;
    let head = 0;
    let tail = 1;
    queue[0] = start;
    visited[start] = 1;
    let area = 0;
    let minX = info.width;
    let minY = info.height;
    let maxX = 0;
    let maxY = 0;
    while (head < tail) {
      const index = queue[head++]!;
      const x = index % info.width;
      const y = Math.floor(index / info.width);
      area += 1;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
      const neighbors = [
        x > 0 ? index - 1 : -1,
        x + 1 < info.width ? index + 1 : -1,
        y > 0 ? index - info.width : -1,
        y + 1 < info.height ? index + info.width : -1,
      ];
      for (const neighbor of neighbors) {
        if (neighbor >= 0 && foreground[neighbor] && !visited[neighbor]) {
          visited[neighbor] = 1;
          queue[tail++] = neighbor;
        }
      }
    }
    const width = maxX - minX + 1;
    const height = maxY - minY + 1;
    if (
      area < minimumArea
      || area > maximumArea
      || width < minimumWidth
      || height < minimumHeight
      || width > maximumWidth
      || height > maximumHeight
    ) continue;
    candidates.push({
      x: region.x + minX,
      y: region.y + minY,
      width,
      height,
      area,
      fillRatio: area / (width * height),
    });
  }
  candidates.sort((a, b) => a.y - b.y || a.x - b.x);
  return { region, candidates };
}

export async function detectConfiguredPublicRegions(
  screenshot: string | Buffer,
  layout: ScreenLayout,
  options: RegionDetectionOptions = {},
): Promise<Partial<Record<PublicTileRegionName, RegionDetection>>> {
  const entries = Object.entries(layout.publicTileRegions ?? {}) as Array<[PublicTileRegionName, PublicTileRegion]>;
  const detections = await Promise.all(entries.map(async ([name, region]) => {
    const detection = await detectBrightTileCandidates(screenshot, region, options);
    if (region.detectionMode !== "discard_grid" || !name.endsWith("Discards")) return [name, detection] as const;
    const widths = detection.candidates.map((candidate) => candidate.width);
    const heights = detection.candidates.map((candidate) => candidate.height);
    const medianWidth = median(widths);
    const medianHeight = median(heights);
    const tileSized = detection.candidates.filter((candidate) => (
      candidate.width >= medianWidth * 0.55 && candidate.width <= medianWidth * 1.55
      && candidate.height >= medianHeight * 0.55 && candidate.height <= medianHeight * 1.55
    ));
    let grid = orderDiscardGridCandidates(tileSized, region);
    if (grid.gridValid && grid.gridRows?.length === 2 && grid.gridRows.every((count) => count === 6)) {
      const inferred = await inferThirdDiscardRow(screenshot, grid.candidates, region, options.luminanceThreshold ?? 190);
      if (inferred.length > 0) grid = orderDiscardGridCandidates([...grid.candidates, ...inferred], region);
    }
    return [name, { ...detection, ...grid }] as const;
  }));
  return Object.fromEntries(detections);
}

function normalizedCenter(candidate: RegionCandidate, region: PublicTileRegion): { x: number; y: number; width: number; height: number } {
  const localX = candidate.x - region.x;
  const localY = candidate.y - region.y;
  const centerX = localX + candidate.width / 2;
  const centerY = localY + candidate.height / 2;
  if (region.rotationToUpright === 90) return { x: region.height - centerY, y: centerX, width: candidate.height, height: candidate.width };
  if (region.rotationToUpright === 180) return { x: region.width - centerX, y: region.height - centerY, width: candidate.width, height: candidate.height };
  if (region.rotationToUpright === 270) return { x: centerY, y: region.width - centerX, width: candidate.height, height: candidate.width };
  return { x: centerX, y: centerY, width: candidate.width, height: candidate.height };
}

function median(values: number[]): number {
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle]! : ((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2;
}

function originalCandidateFromNormalized(
  centerX: number,
  centerY: number,
  width: number,
  height: number,
  region: PublicTileRegion,
): RegionCandidate {
  let originalCenterX = centerX;
  let originalCenterY = centerY;
  let originalWidth = width;
  let originalHeight = height;
  if (region.rotationToUpright === 90) {
    originalCenterX = centerY;
    originalCenterY = region.height - centerX;
    originalWidth = height;
    originalHeight = width;
  } else if (region.rotationToUpright === 180) {
    originalCenterX = region.width - centerX;
    originalCenterY = region.height - centerY;
  } else if (region.rotationToUpright === 270) {
    originalCenterX = region.width - centerY;
    originalCenterY = centerX;
    originalWidth = height;
    originalHeight = width;
  }
  const x = Math.max(region.x, Math.round(region.x + originalCenterX - originalWidth / 2));
  const y = Math.max(region.y, Math.round(region.y + originalCenterY - originalHeight / 2));
  const right = Math.min(region.x + region.width, Math.round(region.x + originalCenterX + originalWidth / 2));
  const bottom = Math.min(region.y + region.height, Math.round(region.y + originalCenterY + originalHeight / 2));
  return { x, y, width: Math.max(1, right - x), height: Math.max(1, bottom - y), area: 0, fillRatio: 0 };
}

async function brightFraction(screenshot: string | Buffer, candidate: RegionCandidate, threshold: number): Promise<number> {
  const { data } = await sharp(screenshot)
    .extract({ left: candidate.x, top: candidate.y, width: candidate.width, height: candidate.height })
    .greyscale()
    .raw()
    .toBuffer({ resolveWithObject: true });
  let bright = 0;
  for (const value of data) if (value >= threshold) bright += 1;
  return bright / Math.max(1, data.length);
}

/** Infer the partially filled 13th–18th cells when overlapping perspective faces merge. */
async function inferThirdDiscardRow(
  screenshot: string | Buffer,
  candidates: RegionCandidate[],
  region: PublicTileRegion,
  luminanceThreshold: number,
): Promise<RegionCandidate[]> {
  if (candidates.length !== 12) return [];
  const points = candidates.map((candidate) => ({ candidate, point: normalizedCenter(candidate, region) }));
  const first = points.slice(0, 6);
  const second = points.slice(6, 12);
  const firstY = median(first.map(({ point }) => point.y));
  const secondY = median(second.map(({ point }) => point.y));
  const rowStep = secondY - firstY;
  if (rowStep <= 2) return [];
  const width = median(points.map(({ point }) => point.width));
  const height = median(points.map(({ point }) => point.height));
  const centers = first.map(({ point }, index) => (point.x + second[index]!.point.x) / 2);
  const expected = centers.map((centerX) => originalCandidateFromNormalized(centerX, secondY + rowStep, width, height, region));
  const fractions = await Promise.all(expected.map((candidate) => brightFraction(screenshot, candidate, luminanceThreshold)));
  const inferred: RegionCandidate[] = [];
  for (let index = 0; index < expected.length; index += 1) {
    const fraction = fractions[index]!;
    if (fraction < 0.32) break;
    inferred.push({ ...expected[index]!, area: Math.round(fraction * expected[index]!.width * expected[index]!.height), fillRatio: fraction });
  }
  return inferred;
}

/**
 * Orders a calibrated river as the player's upright 6-column x 3-row grid.
 * Small perspective offsets therefore cannot reorder tiles within a row.
 */
export function orderDiscardGridCandidates(
  candidates: RegionCandidate[],
  region: PublicTileRegion,
): Pick<RegionDetection, "candidates" | "gridValid" | "gridRows"> {
  if (candidates.length === 0) return { candidates: [], gridValid: true, gridRows: [] };
  const normalized = candidates.map((candidate) => ({ candidate, point: normalizedCenter(candidate, region) }));
  const ordinaryHeight = median(normalized.map(({ point }) => point.height));
  const rowTolerance = Math.max(4, ordinaryHeight * 0.58);
  const rows: Array<{ center: number; items: typeof normalized }> = [];
  for (const item of [...normalized].sort((left, right) => left.point.y - right.point.y)) {
    const closest = rows
      .map((row, index) => ({ index, distance: Math.abs(row.center - item.point.y) }))
      .sort((left, right) => left.distance - right.distance)[0];
    if (!closest || closest.distance > rowTolerance) rows.push({ center: item.point.y, items: [item] });
    else {
      const row = rows[closest.index]!;
      row.items.push(item);
      row.center = row.items.reduce((sum, current) => sum + current.point.y, 0) / row.items.length;
    }
  }
  rows.sort((left, right) => left.center - right.center);
  const selectedRows = rows.slice(0, 3);
  const gridRows = selectedRows.map((row) => row.items.length);
  const structurallyValid = rows.length <= 3
    && gridRows.every((count) => count >= 1 && count <= 6)
    && gridRows.slice(0, -1).every((count) => count === 6)
    && candidates.length <= 18;
  const medianAspect = median(normalized.map(({ point }) => point.width / Math.max(1, point.height)));
  let gridIndex = 0;
  const ordered = selectedRows.flatMap((row) => row.items
    .sort((left, right) => left.point.x - right.point.x)
    .slice(0, 6)
    .map(({ candidate, point }) => ({
      ...candidate,
      gridIndex: gridIndex++,
      sideways: point.width / Math.max(1, point.height) >= Math.max(1.45, medianAspect * 1.3),
    })));
  return { candidates: ordered, gridValid: structurallyValid && ordered.length === candidates.length, gridRows };
}
