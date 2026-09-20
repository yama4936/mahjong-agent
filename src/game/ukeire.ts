import { calculateShanten } from "./shanten.js";
import { TILE_NAMES, isRedTile, normalizeTile, parseGameTile, tileFromIndex, tileIndex, toCounts, type GameTile, type Tile } from "./tiles.js";

export interface EffectiveTile {
  tile: Tile;
  remaining: number;
}

export interface DiscardEvaluation {
  actionId: string;
  action: "discard";
  tile: GameTile;
  shanten: number;
  form: "standard" | "chiitoitsu" | "kokushi";
  effectiveTiles: EffectiveTile[];
  ukeire: number;
  danger?: number;
  estimatedValue?: number;
  winProbability?: number;
  tenpaiProbability?: number;
  dealInProbability?: number;
  expectedRoundValue?: number;
  evaluationModel?: string;
}

export function evaluateDiscards(
  hand: readonly string[],
  visibleTiles: readonly string[] = [],
  openMelds = 0,
): DiscardEvaluation[] {
  if ((hand.length + openMelds * 3) % 3 !== 2) {
    throw new Error("Discard evaluation requires a 14-tile turn state");
  }
  const canonical = hand.map(parseGameTile);
  const normalized = canonical.map(normalizeTile);
  const fullCounts = toCounts([...canonical, ...visibleTiles.map(parseGameTile)]);
  const uniqueDiscards = [...new Set(canonical)];

  return uniqueDiscards.map((discard) => {
    const remainingCanonical = [...canonical];
    remainingCanonical.splice(remainingCanonical.indexOf(discard), 1);
    const remainingHand = remainingCanonical.map(normalizeTile);
    const base = calculateShanten(remainingHand, openMelds);
    const effectiveTiles: EffectiveTile[] = [];
    for (let index = 0; index < TILE_NAMES.length; index += 1) {
      const remaining = 4 - fullCounts[index]!;
      if (remaining <= 0) continue;
      const next = calculateShanten([...remainingHand, tileFromIndex(index)], openMelds);
      if (next.shanten < base.shanten) effectiveTiles.push({ tile: tileFromIndex(index), remaining });
    }
    return {
      actionId: `discard_${discard}`,
      action: "discard" as const,
      tile: discard,
      shanten: base.shanten,
      form: base.bestForm,
      effectiveTiles,
      ukeire: effectiveTiles.reduce((sum, tile) => sum + tile.remaining, 0),
    };
  }).sort((a, b) => a.shanten - b.shanten || b.ukeire - a.ukeire || Number(isRedTile(a.tile)) - Number(isRedTile(b.tile)) || tileIndex(a.tile) - tileIndex(b.tile));
}
