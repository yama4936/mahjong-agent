import { sanmaStructuralCandidates } from "./sanmaLegalExperiment.js";
import { knownTilesOutsideHand, parseGameState } from "./state.js";
import { evaluateDiscards, type DiscardEvaluation } from "./ukeire.js";

/** Offline structural ordering, not a gameplay decision or win-rate model. */
export function sanmaDiscardExperiment(input: {
  state: unknown;
  riichiStatus: "not_declared";
  ui: { status: "confirmed"; actions: readonly ("kita" | "tsumo" | "ron" | "pon" | "kan" | "pass")[] };
  turnContext: "ordinary_draw_confirmed";
  handEvidence: "confirmed";
  meldEvidence: "confirmed";
  visibleEvidence: "confirmed_complete";
}): DiscardEvaluation[] {
  if (!input || input.turnContext !== "ordinary_draw_confirmed" || input.handEvidence !== "confirmed" || input.meldEvidence !== "confirmed"
      || input.visibleEvidence !== "confirmed_complete") throw new Error("Complete hand, meld and visible evidence required");
  if (!input.state || typeof input.state !== "object" || Array.isArray(input.state)) throw new Error("Explicit state required");
  const raw = input.state as Record<string, unknown>;
  if (raw.phase !== "self_turn" || !["east", "south", "west"].includes(raw.seat as string)
      || typeof raw.draw !== "string" || !Array.isArray(raw.hand) || !Array.isArray(raw.melds)
      || !Number.isInteger(raw.openMelds) || raw.openMelds !== raw.melds.length
      || !Array.isArray(raw.visibleTiles) || !Array.isArray(raw.doraIndicators)
      || !Array.isArray(raw.ownDiscards) || !Number.isInteger(raw.ownKitaCount)
      || !Array.isArray(raw.opponents) || raw.opponents.length !== 2) {
    throw new Error("Complete explicit sanma state required");
  }
  for (const opponent of raw.opponents) {
    if (!opponent || typeof opponent !== "object" || !Array.isArray(opponent.discards)
        || !Array.isArray(opponent.melds) || !Number.isInteger(opponent.openMelds)
        || opponent.openMelds !== opponent.melds.length || !Number.isInteger(opponent.kitaCount)) {
      throw new Error("Complete opponent visible evidence required");
    }
  }
  const candidates = sanmaStructuralCandidates(input);
  // Any prompt requires its own policy (including kita/win and kan). Do not
  // bypass even a skip prompt with a speculative discard recommendation.
  if (input.ui.actions.length || candidates.some(candidate => candidate.action !== "discard")) {
    throw new Error("Outstanding UI action requires separate handling");
  }
  const state = parseGameState(raw);
  const hand = [...state.hand, ...(state.draw ? [state.draw] : [])];
  const legal = new Set(candidates.map(candidate => candidate.action === "discard" ? candidate.tile : undefined));
  const evaluations = evaluateDiscards(hand, knownTilesOutsideHand(state), state.openMelds, "sanma");
  if (evaluations.some(row => !legal.has(row.tile)) || evaluations.length !== legal.size) throw new Error("Discard candidate mismatch");
  return evaluations;
}
