export const TILE_NAMES = [
  "1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m",
  "1p", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "9p",
  "1s", "2s", "3s", "4s", "5s", "6s", "7s", "8s", "9s",
  "E", "S", "W", "N", "P", "F", "C",
] as const;

export type Tile = (typeof TILE_NAMES)[number];
export const RED_TILE_NAMES = ["0m", "0p", "0s"] as const;
export type RedTile = (typeof RED_TILE_NAMES)[number];
export type GameTile = Tile | RedTile;
export type InputTile = GameTile | "5mr" | "5pr" | "5sr";

const TILE_INDEX = new Map<string, number>(TILE_NAMES.map((tile, index) => [tile, index]));
const ALIASES: Record<string, Tile> = {
  east: "E", south: "S", west: "W", north: "N",
  white: "P", green: "F", red: "C",
};

const RED_ALIASES: Record<string, RedTile> = {
  "0m": "0m", "0p": "0p", "0s": "0s",
  "5mr": "0m", "5pr": "0p", "5sr": "0s",
};

export function parseGameTile(value: string): GameTile {
  const red = RED_ALIASES[value];
  if (red) return red;
  const normalized = ALIASES[value] ?? value;
  if (!TILE_INDEX.has(normalized)) throw new Error(`Unknown tile: ${value}`);
  return normalized as Tile;
}

export function normalizeTile(value: string): Tile {
  const tile = parseGameTile(value);
  if (!isRedTile(tile)) return tile;
  return `5${tile[1]}` as Tile;
}

export function isRedTile(tile: string): tile is RedTile {
  return RED_TILE_NAMES.includes(tile as RedTile);
}

export function tileIndex(tile: string): number {
  return TILE_INDEX.get(normalizeTile(tile))!;
}

export function tileFromIndex(index: number): Tile {
  const tile = TILE_NAMES[index];
  if (!tile) throw new Error(`Tile index out of range: ${index}`);
  return tile;
}

export function toCounts(tiles: readonly string[]): number[] {
  const counts = Array<number>(34).fill(0);
  for (const tile of tiles) {
    const index = tileIndex(tile);
    counts[index] = (counts[index] ?? 0) + 1;
    if (counts[index]! > 4) throw new Error(`More than four copies of ${tileFromIndex(index)}`);
  }
  return counts;
}

export function isSuit(index: number): boolean {
  return index < 27;
}

export function suitRank(index: number): number {
  return index % 9;
}

export function isTerminalOrHonor(index: number): boolean {
  return index >= 27 || suitRank(index) === 0 || suitRank(index) === 8;
}

export function doraFromIndicator(indicatorInput: string): Tile {
  const indicator = normalizeTile(indicatorInput);
  const index = tileIndex(indicator);
  if (index < 27) {
    const suits = ["m", "p", "s"] as const;
    return normalizeTile(`${((suitRank(index) + 1) % 9) + 1}${suits[Math.floor(index / 9)]}`);
  }
  const group: Tile[] = index < 31 ? ["E", "S", "W", "N"] : ["P", "F", "C"];
  return group[(group.indexOf(indicator) + 1) % group.length]!;
}
