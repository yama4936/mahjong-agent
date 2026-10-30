/** Inputs cover only extracted norths and visible west indicator tiles. */
export type SanmaKitaDoraInput = { extractedNorthCount: number; westIndicatorCount: number };

/**
 * Experimental counting helper, not connected to scoring or gameplay.
 * Each extracted north contributes one bonus han and one more for each west
 * indicator. Sources describe Mahjong Soul's sanma rule:
 * https://note.com/kyuuuuuuuuuso/n/ncd6e98f692d9
 * https://ja.everybodywiki.com/雀魂_-じゃんたま-
 * These cases have not been corroborated against an in-game winning result.
 * This does not decide yaku validity or yakuman treatment and excludes norths
 * in the hand, red tiles and all other dora; callers must handle these separately.
 */
export function countSanmaKitaDora(input: SanmaKitaDoraInput): number {
  if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("Invalid kita dora input");
  const keys = Object.keys(input);
  if (keys.length !== 2 || keys.some(key => key !== "extractedNorthCount" && key !== "westIndicatorCount")) {
    throw new Error("Unsupported kita dora input");
  }
  for (const count of [input.extractedNorthCount, input.westIndicatorCount]) {
    if (!Number.isInteger(count) || count < 0 || count > 4) throw new Error("Invalid tile count");
  }
  return input.extractedNorthCount * (1 + input.westIndicatorCount);
}
