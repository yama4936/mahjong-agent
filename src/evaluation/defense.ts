import { assertYonmaEvaluation } from "../game/state.js";
import { knownTiles, type GameState } from "../game/state.js";
import { doraFromIndicator, normalizeTile, suitRank, tileIndex, toCounts, type Tile } from "../game/tiles.js";

export interface OpponentDanger {
  seat: "east" | "south" | "west" | "north";
  probability: number;
  reasons: string[];
}

export interface TileDanger {
  tile: Tile;
  byOpponent: OpponentDanger[];
  combinedProbability: number;
}

function hasFourKnownSets(opponent: GameState["opponents"][number]): boolean {
  if (opponent.openMelds !== 4 || opponent.melds?.length !== 4) return false;
  // Positive tile evidence is sufficient even if the whole-row observation
  // flag is unknown. A geometry-only count cannot prove a single-tile wait.
  return opponent.melds.every((meld) => {
    const indexes = meld.tiles.map((value) => tileIndex(normalizeTile(value))).sort((a, b) => a - b);
    if (meld.type === "chi") return indexes.length === 3 && indexes[2]! < 27
      && Math.floor(indexes[0]! / 9) === Math.floor(indexes[2]! / 9)
      && indexes[1] === indexes[0]! + 1 && indexes[2] === indexes[0]! + 2;
    return indexes.length === (meld.type === "pon" ? 3 : 4)
      && indexes.every((index) => index === indexes[0]);
  });
}

export function evaluateTileDanger(tileInput: string, state: GameState): TileDanger {
  assertYonmaEvaluation(state);
  const tile = normalizeTile(tileInput);
  const visibleCounts = toCounts(knownTiles(state));
  const tileIdx = tileIndex(tile);
  const isDora = state.doraIndicators.some((indicator) => doraFromIndicator(indicator, state.rules) === tile);

  const byOpponent = state.opponents.map((opponent): OpponentDanger => {
    const discardedTypes = new Set(opponent.discards.map(normalizeTile));
    const reasons: string[] = [];
    if (discardedTypes.has(tile)) return { seat: opponent.seat, probability: 0, reasons: ["genbutsu"] };
    if (opponent.riichi && opponent.postRiichiSafeTiles?.some((safe) => normalizeTile(safe) === tile)) {
      return { seat: opponent.seat, probability: 0, reasons: ["post_riichi_passed"] };
    }
    let probability = opponent.riichi ? 0.12 : opponent.openMelds >= 2 ? 0.07 : opponent.openMelds === 1 ? 0.045 : 0.025;
    if (opponent.riichi) reasons.push("riichi_threat");
    if (opponent.openMelds > 0) reasons.push(`${opponent.openMelds}_open_melds`);

    const known = visibleCounts[tileIdx]!;
    // With four completed sets the only concealed wait is tanki. Before
    // discarding, four physically known copies leave none for its pair.
    // This says nothing about sequence waits against the other opponents.
    if (known === 4 && hasFourKnownSets(opponent)) {
      return { seat: opponent.seat, probability: 0, reasons: ["four_sets_tanki_all_copies_visible"] };
    }
    if (tileIdx >= 27) {
      if (known >= 4) return { seat: opponent.seat, probability: 0, reasons: ["all_copies_visible"] };
      if (known === 3) { probability *= 0.1; reasons.push("honor_one_copy_left"); }
      else if (known === 2) { probability *= 0.45; reasons.push("honor_two_copies_visible"); }
      else probability *= 1.1;
    } else {
      const rank = suitRank(tileIdx) + 1;
      const suit = tile.slice(1);
      const anchors = [rank - 3, rank + 3].filter((value) => value >= 1 && value <= 9).map((value) => `${value}${suit}` as Tile);
      const safeAnchors = anchors.filter((anchor) => discardedTypes.has(anchor)).length;
      if (safeAnchors > 0) {
        probability *= safeAnchors === anchors.length ? 0.5 : 0.68;
        reasons.push(safeAnchors === anchors.length ? "full_suji" : "partial_suji");
      }
      const neighborIndexes = [tileIdx - 1, tileIdx + 1].filter((index) => index >= Math.floor(tileIdx / 9) * 9 && index < Math.floor(tileIdx / 9) * 9 + 9);
      if (neighborIndexes.some((index) => visibleCounts[index]! >= 3)) {
        probability *= 0.72;
        reasons.push("one_chance");
      }
    }
    if (isDora) { probability *= 1.35; reasons.push("dora"); }
    return { seat: opponent.seat, probability: Math.min(0.35, probability), reasons };
  });
  const combinedProbability = 1 - byOpponent.reduce((product, opponent) => product * (1 - opponent.probability), 1);
  return { tile, byOpponent, combinedProbability };
}
