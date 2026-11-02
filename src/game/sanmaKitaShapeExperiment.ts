import { calculateShanten } from "./shanten.js";
import { assertTilesAvailable, normalizeTile, parseGameTile, tileAvailableInRules, TILE_NAMES, tileFromIndex, toCounts, type Tile } from "./tiles.js";

/** Shape-only alternatives after hypothetically extracting one north.
 * Counts are unobserved copies, not probabilities of a wall draw. This makes
 * no assertion about kita legality, action priority, score, or choice of UI.
 * The caller must include every known tile outside the concealed hand (melds,
 * rivers, indicators and prior extracted norths) exactly once.
 */
export function inspectSanmaKitaReplacementShapes(input: {
  hand: readonly string[];
  knownOutsideHand: readonly string[];
  openMelds: number;
}) {
  if (!input || !Array.isArray(input.hand) || !Array.isArray(input.knownOutsideHand)
      || !Number.isInteger(input.openMelds) || input.openMelds < 0 || input.openMelds > 4
      || input.hand.length !== 14 - 3 * input.openMelds) throw new Error("Complete self-turn tile inventory required");
  const hand = input.hand.map(parseGameTile);
  const visible = input.knownOutsideHand.map(parseGameTile);
  assertTilesAvailable([...hand, ...visible], "sanma");
  const north = hand.indexOf("N");
  if (north < 0) throw new Error("Hypothetical extraction requires north");
  const unseen = toCounts([...hand, ...visible]);
  const reduced = [...hand];
  reduced.splice(north, 1);
  const outcomes: { replacement: Tile; unseenCopies: number; completedShape: boolean; bestShantenAfterDiscard: number; bestDiscardClasses: Tile[] }[] = [];
  for (let index = 0; index < TILE_NAMES.length; index += 1) {
    const replacement = tileFromIndex(index);
    const unseenCopies = 4 - unseen[index]!;
    if (!tileAvailableInRules(replacement, "sanma") || unseenCopies <= 0) continue;
    // Red and ordinary replacement fives have identical shape; only the
    // normalized class is modeled, not their value or physical identity.
    const replacementHand = [...reduced, replacement];
    const completedShape = calculateShanten(replacementHand, input.openMelds).shanten === -1;
    let bestShantenAfterDiscard = Infinity;
    const bestDiscardClasses: Tile[] = [];
    for (const discard of new Set(replacementHand)) {
      const rest = [...replacementHand];
      rest.splice(rest.indexOf(discard), 1);
      const shanten = calculateShanten(rest, input.openMelds).shanten;
      if (shanten < bestShantenAfterDiscard) { bestShantenAfterDiscard = shanten; bestDiscardClasses.length = 0; }
      if (shanten === bestShantenAfterDiscard && !bestDiscardClasses.includes(normalizeTile(discard))) bestDiscardClasses.push(normalizeTile(discard));
    }
    outcomes.push({ replacement: normalizeTile(replacement), unseenCopies, completedShape, bestShantenAfterDiscard, bestDiscardClasses });
  }
  return { scope: "offline_untrusted_sanma_kita_shape" as const, operationAuthorized: false as const, outcomes };
}
