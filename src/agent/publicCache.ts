import { normalizeTile, parseGameTile, type GameTile } from "../game/tiles.js";
import type { PublicTileObservation } from "../recognition/publicTileRecognizer.js";

export interface CachedPublicObservation extends PublicTileObservation {
  capturedAt: string;
  recognizedAt: string;
  recognitionLatencyMs: number;
  configuredRegions: string[];
}

export function cachedPublicStatePatch(
  observation: CachedPublicObservation,
  concealedTiles: readonly string[],
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
  const opponents = observation.opponentDiscards.map((opponent) => ({
    seat: opponent.seat,
    discards: accept(opponent.discards),
    riichi: Boolean(opponent.riichiDeclared),
    openMelds: opponent.melds?.length ?? 0,
  }));
  const visibleTiles = accept(observation.allMeldTiles ?? observation.ownMeldTiles);
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
