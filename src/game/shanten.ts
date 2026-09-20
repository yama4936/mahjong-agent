import { isSuit, isTerminalOrHonor, suitRank, toCounts } from "./tiles.js";

export interface ShantenResult {
  shanten: number;
  standard: number;
  chiitoitsu: number;
  kokushi: number;
  bestForm: "standard" | "chiitoitsu" | "kokushi";
}

function standardShanten(counts: number[], openMelds: number): number {
  let best = 8;

  function finish(melds: number, pairs: number, taatsu: number): void {
    const totalMelds = melds + openMelds;
    const usableTaatsu = Math.min(taatsu, Math.max(0, 4 - totalMelds));
    best = Math.min(best, 8 - totalMelds * 2 - usableTaatsu - Math.min(1, pairs));
  }

  function dfs(start: number, melds: number, pairs: number, taatsu: number): void {
    let index = start;
    while (index < 34 && counts[index] === 0) index += 1;
    if (index >= 34) {
      finish(melds, pairs, taatsu);
      return;
    }

    // Skip this tile as an isolated tile.
    counts[index]!--;
    dfs(index, melds, pairs, taatsu);
    counts[index]!++;

    if (counts[index]! >= 3) {
      counts[index]! -= 3;
      dfs(index, melds + 1, pairs, taatsu);
      counts[index]! += 3;
    }

    if (counts[index]! >= 2) {
      counts[index]! -= 2;
      dfs(index, melds, pairs + 1, taatsu);
      dfs(index, melds, pairs, taatsu + 1);
      counts[index]! += 2;
    }

    if (!isSuit(index)) return;
    const rank = suitRank(index);
    if (rank <= 6 && counts[index + 1]! > 0 && counts[index + 2]! > 0) {
      counts[index]!--;
      counts[index + 1]!--;
      counts[index + 2]!--;
      dfs(index, melds + 1, pairs, taatsu);
      counts[index]!++;
      counts[index + 1]!++;
      counts[index + 2]!++;
    }
    if (rank <= 7 && counts[index + 1]! > 0) {
      counts[index]!--;
      counts[index + 1]!--;
      dfs(index, melds, pairs, taatsu + 1);
      counts[index]!++;
      counts[index + 1]!++;
    }
    if (rank <= 6 && counts[index + 2]! > 0) {
      counts[index]!--;
      counts[index + 2]!--;
      dfs(index, melds, pairs, taatsu + 1);
      counts[index]!++;
      counts[index + 2]!++;
    }
  }

  dfs(0, 0, 0, 0);
  return best;
}

function chiitoitsuShanten(counts: readonly number[], openMelds: number): number {
  if (openMelds > 0) return 99;
  const pairs = counts.filter((count) => count >= 2).length;
  const unique = counts.filter((count) => count > 0).length;
  return 6 - pairs + Math.max(0, 7 - unique);
}

function kokushiShanten(counts: readonly number[], openMelds: number): number {
  if (openMelds > 0) return 99;
  let unique = 0;
  let pair = false;
  for (let i = 0; i < 34; i += 1) {
    if (!isTerminalOrHonor(i)) continue;
    if (counts[i]! > 0) unique += 1;
    if (counts[i]! > 1) pair = true;
  }
  return 13 - unique - Number(pair);
}

export function calculateShanten(tiles: readonly string[], openMelds = 0): ShantenResult {
  const expectedRemainder = (tiles.length + openMelds * 3) % 3;
  if (expectedRemainder !== 1 && expectedRemainder !== 2) {
    throw new Error(`Hand must represent a 13/14-tile turn state; got ${tiles.length} concealed tiles and ${openMelds} open melds`);
  }
  const counts = toCounts(tiles);
  const standard = standardShanten([...counts], openMelds);
  const chiitoitsu = chiitoitsuShanten(counts, openMelds);
  const kokushi = kokushiShanten(counts, openMelds);
  const shanten = Math.min(standard, chiitoitsu, kokushi);
  const bestForm = shanten === standard ? "standard" : shanten === chiitoitsu ? "chiitoitsu" : "kokushi";
  return { shanten, standard, chiitoitsu, kokushi, bestForm };
}
