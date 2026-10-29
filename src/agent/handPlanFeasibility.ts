import { normalizeTile, parseGameTile } from "../game/tiles.js";

export interface HandPlanMeld {
  type: "chi" | "pon" | "minkan" | "ankan" | "kakan";
  tiles: readonly string[];
}

/** Complete fixed groups only; missing open groups are not proof of a yaku path. */
function fixedMelds(openMelds: number, melds?: readonly HandPlanMeld[]): readonly HandPlanMeld[] | undefined {
  if (!Number.isInteger(openMelds) || openMelds < 0 || openMelds > 4) return undefined;
  if (melds === undefined) return openMelds === 0 ? [] : undefined;
  if (!Array.isArray(melds)) return undefined;
  if (melds.length !== openMelds) return undefined;
  try {
    for (const meld of melds as readonly HandPlanMeld[]) {
      const tiles = meld.tiles.map(tile => normalizeTile(parseGameTile(tile)));
      if (meld.type === "chi") {
        const sorted = [...tiles].sort();
        if (sorted.length !== 3 || !sorted.every(tile => /^[1-9][mps]$/.test(tile))
          || !sorted.every(tile => tile[1] === sorted[0]![1])
          || Number(sorted[1]![0]) !== Number(sorted[0]![0]) + 1
          || Number(sorted[2]![0]) !== Number(sorted[0]![0]) + 2) return undefined;
      } else if (!["pon", "minkan", "ankan", "kakan"].includes(meld.type)
        || tiles.length !== (meld.type === "pon" ? 3 : 4)
        || !tiles.every(tile => tile === tiles[0])) return undefined;
    }
    return melds;
  } catch { return undefined; }
}

/** A cache identity, not additional physically visible tiles. Preserve red identity. */
export function handPlanMeldSignature(openMelds: number, melds?: readonly HandPlanMeld[]): string | undefined {
  const fixed = fixedMelds(openMelds, melds);
  return fixed && JSON.stringify(fixed.map(meld => [meld.type, [...meld.tiles].sort()])
    .sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))));
}

/** Remove only directions contradicted by immutable melds; do not score or approve actions. */
export function isHandPlanFeasible(id: string, openMelds: number, melds?: readonly HandPlanMeld[]): boolean {
  if (id === "efficient_standard") return true;
  const fixed = fixedMelds(openMelds, melds);
  if (!fixed) return false; // Unknown open groups retain the generic route only.
  if (id === "toitoi") return fixed.every(meld => meld.type !== "chi");
  const suit = /^honitsu_([mps])$/.exec(id)?.[1];
  if (suit) return fixed.every(meld => meld.tiles.every(tile => tile.length === 1 || tile.endsWith(suit)));
  if (id === "tanyao") return fixed.every(meld => meld.tiles.every(tile => /^[2-8][mps]$/.test(normalizeTile(tile))));
  if (id === "closed_sequence" || id === "riichi/efficient_standard") return fixed.every(meld => meld.type === "ankan");
  if (id === "chiitoitsu") return fixed.length === 0;
  return true;
}
