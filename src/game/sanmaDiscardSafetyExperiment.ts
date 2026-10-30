import { parseGameState } from "./state.js";
import { isOpponentGenbutsu } from "../evaluation/defense.js";
import { sanmaDiscardExperiment } from "./sanmaDiscardExperiment.js";

/**
 * Attach only direct own-river furiten evidence to the existing sanma shape
 * rows. No risk probabilities or push/fold policy are inferred. The input's
 * evidence flags are caller-supplied claims, not validated image observations.
 */
export function inspectSanmaDiscardSafety(input: Parameters<typeof sanmaDiscardExperiment>[0]) {
  const rows = sanmaDiscardExperiment(input);
  const state = parseGameState(input.state);
  return {
    scope: "offline_untrusted_sanma_discard_safety" as const,
    operationAuthorized: false as const,
    rows: rows.map(row => {
      const byOpponent = state.opponents.map(opponent => ({
        seat: opponent.seat,
        status: isOpponentGenbutsu(row.tile, opponent.discards)
          ? "genbutsu_candidate" as const : "unknown" as const,
      }));
      return { ...row, byOpponent, allOpponentsGenbutsuCandidate: byOpponent.every(item => item.status === "genbutsu_candidate") };
    }),
  };
}
