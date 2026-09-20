import { knownTilesOutsideHand, type GameState } from "../game/state.js";
import { evaluateDiscards, type DiscardEvaluation } from "../game/ukeire.js";
import { evaluateTileDanger } from "./defense.js";
import { evaluateRoundValue } from "./value.js";

export interface AdvisorResult {
  recommendedAction: "discard" | "riichi" | "tsumo" | "ron" | "chi" | "pon" | "minkan" | "ankan" | "kakan" | "kyuushu" | "pass";
  tile: string;
  confidence: number;
  source: "deterministic" | "jev";
  candidates: DiscardEvaluation[];
  safety: { allowed: boolean; reasons: string[] };
}

export function safetyCheck(state: GameState, candidates: readonly DiscardEvaluation[], minRecognition = 0.98) {
  const reasons: string[] = [];
  if (state.recognitionConfidence < minRecognition) reasons.push("recognition_confidence_below_threshold");
  if (candidates.length === 0) reasons.push("no_legal_action");
  if (candidates.some((candidate) => !state.hand.includes(candidate.tile) && state.draw !== candidate.tile)) {
    reasons.push("candidate_not_in_hand");
  }
  return { allowed: reasons.length === 0, reasons };
}

export function deterministicAdvice(state: GameState): AdvisorResult {
  const hand = state.draw ? [...state.hand, state.draw] : state.hand;
  const evaluated = evaluateDiscards(
    hand,
    knownTilesOutsideHand(state),
    state.openMelds,
  ).map((candidate) => evaluateRoundValue({ ...candidate, danger: evaluateTileDanger(candidate.tile, state).combinedProbability }, state));
  const minimumShanten = Math.min(...evaluated.map((candidate) => candidate.shanten));
  const underThreat = state.opponents.some((opponent) => opponent.riichi || opponent.openMelds >= 2);
  const candidates = evaluated.sort((left, right) => {
    if (!underThreat && left.shanten !== right.shanten) return left.shanten - right.shanten;
    const leftInRange = left.shanten <= minimumShanten + 1;
    const rightInRange = right.shanten <= minimumShanten + 1;
    if (leftInRange !== rightInRange) return leftInRange ? -1 : 1;
    if (underThreat && leftInRange && rightInRange && left.expectedRoundValue !== right.expectedRoundValue) {
      return (right.expectedRoundValue ?? Number.NEGATIVE_INFINITY) - (left.expectedRoundValue ?? Number.NEGATIVE_INFINITY);
    }
    return left.shanten - right.shanten
      || (right.expectedRoundValue ?? Number.NEGATIVE_INFINITY) - (left.expectedRoundValue ?? Number.NEGATIVE_INFINITY)
      || right.ukeire - left.ukeire;
  });
  const safety = safetyCheck(state, candidates);
  const best = candidates[0];
  if (!best) throw new Error("No discard candidate");
  const second = candidates[1];
  const confidence = !second ? 1 : best.shanten < second.shanten ? 0.95 : Math.min(0.9, 0.55 + Math.max(0, best.ukeire - second.ukeire) / 80);
  return {
    recommendedAction: "discard",
    tile: best.tile,
    confidence,
    source: "deterministic",
    candidates,
    safety,
  };
}
