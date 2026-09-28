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
  expectedOwnMelds = 0,
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
  // Publish own groups only when all physical tiles and the independently
  // inferred group count agree. Never publish a partial pon after copy filtering.
  const recognizedOwnMelds = observation.ownMelds ?? [];
  const typedTiles = recognizedOwnMelds.flatMap((meld) => meld.tiles);
  const sameTiles = [...typedTiles].sort().join(",") === [...observation.ownMeldTiles].sort().join(",");
  const nextCounts = new Map(counts);
  let completeOwnMelds = expectedOwnMelds > 0 && recognizedOwnMelds.length === expectedOwnMelds && sameTiles;
  for (const meld of recognizedOwnMelds) {
    if (meld.tiles.length !== (meld.type === "minkan" ? 4 : 3)) completeOwnMelds = false;
    for (const value of meld.tiles) {
      const tile = normalizeTile(value);
      const count = nextCounts.get(tile) ?? 0;
      if (count >= 4) completeOwnMelds = false;
      nextCounts.set(tile, count + 1);
    }
  }
  const melds = completeOwnMelds ? recognizedOwnMelds.map(({ type, tiles }) => ({ type, tiles: [...tiles] })) : [];
  // Typed meld tiles must not also appear in visibleTiles.
  const visibleTiles = completeOwnMelds ? [] : accept(observation.ownMeldTiles);
  return {
    patch: {
      doraIndicators,
      ownDiscards,
      opponents,
      visibleTiles,
      melds,
      riichiDeclared: Boolean(observation.ownRiichiDeclared),
      turn: ownDiscards.length,
      publicStateConfidence: 0,
    },
    rejectedTiles,
  };
}
