import { assertYonmaEvaluation } from "../game/state.js";
import { knownTilesOutsideHand, type GameState } from "../game/state.js";
import type { DiscardEvaluation } from "../game/ukeire.js";
import { calculateShanten } from "../game/shanten.js";
import { doraFromIndicator, isRedTile, normalizeTile, TILE_NAMES, toCounts } from "../game/tiles.js";

/** Facts derived from supplied tiles, not a second probabilistic policy. */
export function discardTacticalContext(state: GameState, candidates: readonly DiscardEvaluation[]) {
  assertYonmaEvaluation(state);
  const hand = [...state.hand, ...(state.draw ? [state.draw] : [])];
  const knownCounts = toCounts([...hand, ...knownTilesOutsideHand(state)]);
  const dora = state.doraIndicators.map((indicator) => doraFromIndicator(indicator, state.rules));
  const minimumShanten = candidates.length ? Math.min(...candidates.map(candidate => candidate.shanten)) : null;
  const bonusCount = (tiles: readonly string[]) => ({
    indicator_dora: state.doraIndicators.length ? tiles.reduce((sum, tile) => sum
      + dora.filter(bonus => bonus === normalizeTile(tile)).length, 0) : "unknown" as const,
    red_dora: tiles.filter(isRedTile).length,
  });
  const criteria = new Map(candidates.map(candidate => {
    const remaining = [...hand];
    const index = remaining.indexOf(candidate.tile);
    if (index < 0) throw new Error("Tactical context requires a discard in hand");
    remaining.splice(index, 1);
    const counts = toCounts(remaining);
    // Include exhausted waits too: a discarded exhausted wait still makes
    // the entire hand discard-furiten, even if another wait is live.
    const waits = candidate.shanten === 0 ? TILE_NAMES.flatMap((tile, index) =>
      counts[index]! < 4 && calculateShanten([...remaining, tile], state.openMelds).shanten === -1
        ? [{ tile, remaining: Math.max(0, 4 - knownCounts[index]!) }] : []) : [];
    const ownRiver = new Set([...state.ownDiscards, candidate.tile].map(normalizeTile));
    const furitenWaits = waits.filter(wait => ownRiver.has(wait.tile)).map(wait => wait.tile);
    return [candidate.actionId, {
      tenpai_after_discard: candidate.shanten === 0,
      breaks_available_tenpai: minimumShanten === 0 && candidate.shanten > 0,
      structural_waits: waits,
      live_structural_wait_copies: waits.reduce((sum, wait) => sum + wait.remaining, 0),
      discard_furiten: candidate.shanten === 0 ? furitenWaits.length > 0 : "not_applicable",
      discard_furiten_waits: furitenWaits,
      temporary_or_riichi_pass_furiten: "not_observed",
      lost_bonus: bonusCount([candidate.tile]),
      retained_bonus: bonusCount([...remaining, ...state.melds.flatMap(meld => meld.tiles)]),
    }] as const;
  }));
  return {
    summary: {
      minimum_shanten_in_offered_choices: minimumShanten,
      tenpai_choice_available: minimumShanten === 0,
      dora_tiles_from_indicators: state.doraIndicators.length ? dora : "unknown",
      visible_attack: state.opponents.some(opponent => opponent.riichi || opponent.openMelds >= 2),
      own_meld_tile_evidence_complete: state.melds.length === state.openMelds,
      scope: "derived_from_recognized_tiles_not_independent_recognition_or_win_legality",
    },
    criteria,
  };
}
