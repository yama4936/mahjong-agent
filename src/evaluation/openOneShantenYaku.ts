import { assertYonmaEvaluation } from "../game/state.js";
import { knownTiles, type GameState } from "../game/state.js";
import { normalizeTile, tileIndex, TILE_NAMES, toCounts } from "../game/tiles.js";
import { standardWinningShapes } from "../game/winningShapes.js";
import type { DiscardEvaluation } from "../game/ukeire.js";
import { knownOpenGroups, ordinaryOpenShapeYaku } from "./openTenpaiYaku.js";

export interface OpenOneShantenYaku {
  scope: "shortest_structural_progress_to_ordinary_open_win_only";
  discardTile: string;
  status: "known" | "unknown";
  unknownReason?: "work_limit";
  structuralProgressUkeire: number;
  ordinaryProgressUkeire?: number;
  // No shortest-route witness is NOT a proof against longer reconstruction,
  // calls, future situational yaku, or shape-tenpai draw payments.
  longerRoutes: "not_evaluated";
}

// Match knownOpenGroups' physical validation, but do not reject a legal
// opponent ankan-only hand merely because that opponent is still closed.
function legalPublicMeld(meld: GameState["melds"][number]): boolean {
  try {
    const indices = meld.tiles.map(tile => tileIndex(normalizeTile(tile))).sort((a, b) => a - b);
    const start = indices[0]!;
    if (meld.type === "chi") return indices.length === 3 && start < 27 && start % 9 <= 6
      && indices[1] === start + 1 && indices[2] === start + 2;
    return ["pon", "minkan", "ankan", "kakan"].includes(meld.type)
      && indices.length === (meld.type === "pon" ? 3 : 4)
      && indices.every(index => index === start);
  } catch { return false; }
}

/** One bounded, memoized analysis per actual state, shared by all discards.
 * Existence only, not points or an exhaustive future win forecast. A work
 * cap or incomplete physical/meld/wind evidence returns unknown, never zero.
 */
export function createOpenOneShantenAnalyzer(state: GameState) {
  assertYonmaEvaluation(state);
  const exposed = knownOpenGroups(state);
  let counts: number[] | undefined;
  try {
    const physical = knownTiles(state);
    const redValid = ["m", "p", "s"].every(suit => physical.filter(tile => tile === `0${suit}`).length <= 1
      && physical.filter(tile => tile === `5${suit}`).length <= 3);
    if (redValid) counts = toCounts(physical);
  } catch { /* unknown */ }
  const publicMeldsKnown = state.opponents.length === 3
    && new Set(state.opponents.map(opponent => opponent.seat)).size === 3
    && state.opponents.every(opponent => opponent.seat !== state.seat && opponent.openMeldsObserved === true
      && (opponent.melds?.length ?? 0) === opponent.openMelds
      && (opponent.melds ?? []).every(legalPublicMeld));
  const enabled = exposed && counts && state.phase === "self_turn"
    && publicMeldsKnown
    && state.remainingTiles !== undefined && state.remainingTiles > 4;
  const memo = new Map<string, boolean>();
  let work = 0;
  return (candidate: DiscardEvaluation): OpenOneShantenYaku | undefined => {
    if (!enabled || !exposed || !counts || candidate.shanten !== 1) return;
    const concealed = [...state.hand, ...(state.draw ? [state.draw] : [])].map(normalizeTile);
    const discardIndex = concealed.indexOf(normalizeTile(candidate.tile));
    if (discardIndex < 0 || concealed.length !== 14 - 3 * state.openMelds) return;
    concealed.splice(discardIndex, 1);
    let structuralProgressUkeire = 0;
    let ordinaryProgressUkeire = 0;
    for (const progress of candidate.effectiveTiles) {
      const progressIndex = TILE_NAMES.indexOf(progress.tile);
      if (progressIndex < 0 || progress.remaining !== 4 - counts[progressIndex]!
        || progress.remaining <= 0) return;
      structuralProgressUkeire += progress.remaining;
      let possible = false;
      const drawn = [...concealed, progress.tile];
      for (const discard of new Set(drawn)) {
        const next = [...drawn];
        next.splice(next.indexOf(discard), 1);
        const key = `${progress.tile}:${[...next].sort().join(",")}`;
        let witness = memo.get(key);
        if (witness === undefined) {
          witness = false;
          for (let index = 0; index < TILE_NAMES.length; index++) {
            if (counts[index]! + Number(index === progressIndex) >= 4) continue;
            if (++work > 4096) return { scope: "shortest_structural_progress_to_ordinary_open_win_only", discardTile: candidate.tile,
              status: "unknown", unknownReason: "work_limit", structuralProgressUkeire: candidate.ukeire,
              longerRoutes: "not_evaluated" };
            const winner = TILE_NAMES[index]!;
            for (const shape of standardWinningShapes([...next, winner], state.openMelds)) {
              // Tsumo witnesses retain sanankou when ron is unavailable or
              // furiten. Ordinary self-draw alone does not create an open yaku.
              if (ordinaryOpenShapeYaku(shape, exposed, winner, state, true).length
                || ordinaryOpenShapeYaku(shape, exposed, winner, state, false).length) {
                witness = true;
                break;
              }
            }
            if (witness) break;
          }
          memo.set(key, witness);
        }
        if (witness) { possible = true; break; }
      }
      if (possible) ordinaryProgressUkeire += progress.remaining;
    }
    if (!structuralProgressUkeire || structuralProgressUkeire !== candidate.ukeire) return;
    return { scope: "shortest_structural_progress_to_ordinary_open_win_only",
      discardTile: candidate.tile, status: "known", structuralProgressUkeire, ordinaryProgressUkeire, longerRoutes: "not_evaluated" };
  };
}
