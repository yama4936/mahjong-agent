import { normalizeTile, parseGameTile, type GameTile } from "../game/tiles.js";
import { opponentStatesFromObservation, type PublicTileObservation } from "../recognition/publicTileRecognizer.js";
import type { PublicGameState } from "../game/state.js";
import type { JevHandPlan } from "../jev/client.js";

export interface CachedPublicObservation extends PublicTileObservation {
  capturedAt: string;
  recognizedAt: string;
  recognitionLatencyMs: number;
  configuredRegions: string[];
  handPlan?: JevHandPlan;
}

export function cachedPublicStatePatch(
  observation: CachedPublicObservation,
  concealedTiles: readonly string[],
  previousOpponents: PublicGameState["opponents"] = [],
): { patch: Record<string, unknown>; rejectedTiles: number } {
  const counts = new Map<GameTile, number>();
  let rejectedTiles = 0;
  const accept = (values: readonly string[]) => values.flatMap((value) => {
    const tile = parseGameTile(value);
    const normalized = normalizeTile(tile);
    const count = counts.get(normalized) ?? 0;
    if (count >= 4) {
      rejectedTiles += 1;
      return [];
    }
    counts.set(normalized, count + 1);
    return [tile];
  });
  accept(concealedTiles);
  const doraIndicators = accept(observation.doraIndicators);
  const ownDiscards = accept(observation.ownDiscards);
  const opponents = opponentStatesFromObservation(observation, previousOpponents).map((opponent) => ({
    ...opponent, discards: accept(opponent.discards),
  }));
  for (const opponent of opponents) {
    const acceptedMelds = [];
    for (const meld of opponent.melds ?? []) {
      const next = new Map(counts);
      let valid = true;
      for (const value of meld.tiles) {
        const tile = normalizeTile(value);
        const count = next.get(tile) ?? 0;
        if (count >= 4) { valid = false; break; }
        next.set(tile, count + 1);
      }
      if (valid) {
        for (const [tile, count] of next) counts.set(tile, count);
        acceptedMelds.push(meld);
      } else {
        rejectedTiles += meld.tiles.length;
        opponent.openMeldsObserved = false;
      }
    }
    opponent.melds = acceptedMelds;
  }
  // Opponent melds are typed on each opponent, not duplicated in visibleTiles.
  const visibleTiles = accept(observation.ownMeldTiles);
  return {
    patch: {
      doraIndicators,
      ownDiscards,
      opponents,
      visibleTiles,
      riichiDeclared: Boolean(observation.ownRiichiDeclared),
      turn: ownDiscards.length,
      publicStateConfidence: 0,
    },
    rejectedTiles,
  };
}
