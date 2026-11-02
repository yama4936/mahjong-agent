import { calculateShanten } from "./shanten.js";
import { assertTilesAvailable, normalizeTile, parseGameTile, tileAvailableInRules, TILE_NAMES, tileFromIndex, toCounts, type Tile } from "./tiles.js";

/** Shape-only alternatives after hypothetically extracting one north.
 * Counts are maximum unaccounted copies, not verified availability or wall probabilities. This makes
 * no assertion about kita legality, action priority, score, or choice of UI.
 * Own melds are supplied separately and validated. The caller must provide
 * rivers, indicators, opponents’ melds and extracted norths separately.
 * Completeness of these observations cannot be established by this function.
 */
export function inspectSanmaKitaReplacementShapes(input: {
  hand: readonly string[];
  knownOutsideHand: readonly string[];
  ownMelds: readonly (readonly string[])[];
}) {
  if (!input || !Array.isArray(input.hand) || !Array.isArray(input.knownOutsideHand)
      || !Array.isArray(input.ownMelds) || input.ownMelds.length > 4
      || input.hand.length !== 14 - 3 * input.ownMelds.length) throw new Error("Complete self-turn tile inventory required");
  const hand = input.hand.map(parseGameTile);
  const visible = input.knownOutsideHand.map(parseGameTile);
  const ownMelds = input.ownMelds.map(meld => {
    if (!Array.isArray(meld) || (meld.length !== 3 && meld.length !== 4)) throw new Error("Invalid sanma meld");
    const tiles = meld.map(parseGameTile);
    if (tiles.some(tile => normalizeTile(tile) !== normalizeTile(tiles[0]!))) throw new Error("Invalid sanma meld");
    return tiles;
  });
  assertTilesAvailable([...hand, ...visible, ...ownMelds.flat()], "sanma");
  const north = hand.indexOf("N");
  if (north < 0) throw new Error("Hypothetical extraction requires north");
  const accounted = toCounts([...hand, ...visible, ...ownMelds.flat()]);
  const reduced = [...hand];
  reduced.splice(north, 1);
  const outcomes: { replacement: Tile; unaccountedCopies: number; completedShape: boolean; bestShantenAfterDiscard: number; bestDiscardClasses: Tile[] }[] = [];
  for (let index = 0; index < TILE_NAMES.length; index += 1) {
    const replacement = tileFromIndex(index);
    const unaccountedCopies = 4 - accounted[index]!;
    if (!tileAvailableInRules(replacement, "sanma") || unaccountedCopies <= 0) continue;
    // Red and ordinary replacement fives have identical shape; only the
    // normalized class is modeled, not their value or physical identity.
    const replacementHand = [...reduced, replacement];
    const completedShape = calculateShanten(replacementHand, ownMelds.length).shanten === -1;
    let bestShantenAfterDiscard = Infinity;
    const bestDiscardClasses: Tile[] = [];
    for (const discard of new Set(replacementHand)) {
      const rest = [...replacementHand];
      rest.splice(rest.indexOf(discard), 1);
      const shanten = calculateShanten(rest, ownMelds.length).shanten;
      if (shanten < bestShantenAfterDiscard) { bestShantenAfterDiscard = shanten; bestDiscardClasses.length = 0; }
      if (shanten === bestShantenAfterDiscard && !bestDiscardClasses.includes(normalizeTile(discard))) bestDiscardClasses.push(normalizeTile(discard));
    }
    outcomes.push({ replacement: normalizeTile(replacement), unaccountedCopies, completedShape, bestShantenAfterDiscard, bestDiscardClasses });
  }
  return { scope: "offline_untrusted_sanma_kita_shape" as const, operationAuthorized: false as const, inventoryCompleteness: "unverified" as const, outcomes };
}
