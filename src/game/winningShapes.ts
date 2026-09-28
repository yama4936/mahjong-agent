import { tileFromIndex, tileIndex, toCounts, type Tile } from "./tiles.js";

export interface WinningShape {
  pair: Tile;
  groups: Array<{ type: "sequence" | "triplet"; tiles: Tile[] }>;
}

/** Exact standard-hand decompositions, not a yaku or points evaluator. */
export function standardWinningShapes(tiles: readonly string[], openMelds = 0): WinningShape[] {
  if (!Number.isInteger(openMelds) || openMelds < 0 || openMelds > 4) throw new Error("Invalid open meld count");
  if (tiles.length !== 14 - openMelds * 3) return [];
  const counts = toCounts(tiles);
  const result: WinningShape[] = [];
  const groups: WinningShape["groups"] = [];
  function search(pair: number): void {
    const index = counts.findIndex((count) => count > 0);
    if (index === -1) {
      if (groups.length === 4 - openMelds) result.push({ pair: tileFromIndex(pair), groups: groups.map((group) => ({ ...group, tiles: [...group.tiles] })) });
      return;
    }
    if (counts[index]! >= 3) {
      counts[index]! -= 3;
      groups.push({ type: "triplet", tiles: Array<Tile>(3).fill(tileFromIndex(index)) });
      search(pair);
      groups.pop();
      counts[index]! += 3;
    }
    if (index < 27 && index % 9 <= 6 && counts[index + 1]! > 0 && counts[index + 2]! > 0) {
      for (const offset of [0, 1, 2]) counts[index + offset]!--;
      groups.push({ type: "sequence", tiles: [0, 1, 2].map((offset) => tileFromIndex(index + offset)) });
      search(pair);
      groups.pop();
      for (const offset of [0, 1, 2]) counts[index + offset]!++;
    }
  }
  for (let pair = 0; pair < 34; pair++) {
    if (counts[pair]! < 2) continue;
    counts[pair]! -= 2;
    search(pair);
    counts[pair]! += 2;
  }
  return result;
}

export type WaitShape = "tanki" | "shanpon" | "kanchan" | "penchan" | "ryanmen";

export function standardWaitShapes(concealed: readonly string[], winningTile: string, openMelds = 0): WaitShape[] {
  const winner = tileIndex(winningTile);
  const waits = new Set<WaitShape>();
  for (const shape of standardWinningShapes([...concealed, winningTile], openMelds)) {
    if (tileIndex(shape.pair) === winner) waits.add("tanki");
    for (const group of shape.groups) {
      if (!group.tiles.some((tile) => tileIndex(tile) === winner)) continue;
      if (group.type === "triplet") waits.add("shanpon");
      else {
        const start = tileIndex(group.tiles[0]!);
        if (winner === start + 1) waits.add("kanchan");
        else if ((start % 9 === 0 && winner === start + 2) || (start % 9 === 6 && winner === start)) waits.add("penchan");
        else waits.add("ryanmen");
      }
    }
  }
  return [...waits];
}
