import { isAllLastRound, knownTilesOutsideHand, type GameState } from "../game/state.js";
import { evaluateDiscards, type DiscardEvaluation } from "../game/ukeire.js";
import { evaluateTileDanger } from "./defense.js";
import { evaluateRoundValue } from "./value.js";
import { createOpenOneShantenAnalyzer } from "./openOneShantenYaku.js";
import { calculateShanten } from "../game/shanten.js";
import { normalizeTile, toCounts, tileIndex, type Tile } from "../game/tiles.js";

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

/** A structural closed wait can win by menzen tsumo; open waits need ordinary yaku evidence. */
export function hasLiveWinningTenpai(candidate: DiscardEvaluation, state: GameState): boolean {
  if (candidate.shanten !== 0 || candidate.ukeire <= 0) return false;
  const closed = state.openMelds === 0 || (state.melds.length === state.openMelds
    && state.melds.every(meld => meld.type === "ankan"));
  return closed || candidate.openTenpaiScore?.scope === "ordinary_open_hand_without_situational_yaku_honba_or_deposits"
    && candidate.openTenpaiScore.winningUkeire > 0;
}

/** Positive evidence only; includes the just-discarded tile and dead waits. */
function knownDiscardFuritenWaits(candidate: DiscardEvaluation, state: GameState): Tile[] {
  if (candidate.shanten !== 0) return [];
  const remaining = [...state.hand, ...(state.draw ? [state.draw] : [])];
  const index = remaining.indexOf(candidate.tile);
  if (index < 0) throw new Error("Furiten evaluation requires a discard in hand");
  remaining.splice(index, 1);
  const counts = toCounts(remaining);
  return [...new Set([...state.ownDiscards, candidate.tile].map(normalizeTile))]
    .filter(tile => counts[tileIndex(tile)]! < 4
      && calculateShanten([...remaining, tile], state.openMelds).shanten === -1);
}

export function deterministicAdvice(state: GameState): AdvisorResult {
  const hand = state.draw ? [...state.hand, state.draw] : state.hand;
  const ordinaryProgress = createOpenOneShantenAnalyzer(state);
  const structural = evaluateDiscards(
    hand,
    knownTilesOutsideHand(state),
    state.openMelds,
  );
  const evaluated = structural.map((candidate) => {
    const evidence = ordinaryProgress(candidate);
    const furitenWaits = knownDiscardFuritenWaits(candidate, state);
    return evaluateRoundValue({ ...candidate, ...(evidence ? { openOneShantenYaku: evidence } : {}),
      ...(furitenWaits.length ? { knownDiscardFuritenWaits: furitenWaits } : {}),
      danger: evaluateTileDanger(candidate.tile, state).combinedProbability }, state);
  });
  const minimumShanten = Math.min(...evaluated.map((candidate) => candidate.shanten));
  const underThreat = state.opponents.some((opponent) => opponent.riichi || opponent.openMelds >= 2);
  const ownScore = state.scores[state.seat];
  const scores = Object.values(state.scores).sort((a, b) => b - a);
  const rank = ownScore === undefined || scores.length < 4 ? 2 : scores.indexOf(ownScore) + 1;
  const allLast = isAllLastRound(state);
  const phase = state.turn <= 6 ? "early" : state.turn <= 11 ? "middle" : "late";
  const urgentPush = allLast && rank === 4;
  const protectLead = rank === 1;
  const candidates = evaluated.sort((left, right) => {
    // Unopposed late-hand EV estimates must not break a live winning tenpai.
    // A visible attack still allows folding; dead/uncertified open waits get no protection.
    if (!underThreat) {
      const leftLive = hasLiveWinningTenpai(left, state);
      const rightLive = hasLiveWinningTenpai(right, state);
      if (leftLive !== rightLive) return leftLive ? -1 : 1;
    }
    if (phase === "early" && !underThreat) {
      // Apply mode-specific evidence only when available; otherwise ron
      // eligibility (including dama and situational yaku) remains unknown.
      const effective = (candidate: DiscardEvaluation) => candidate.openTenpaiScoreApplied && candidate.openTenpaiScore
        ? (3 * candidate.openTenpaiScore.ronUkeire + candidate.openTenpaiScore.tsumoUkeire) / 4
        : candidate.ukeire;
      return left.shanten - right.shanten || effective(right) - effective(left)
        || (right.expectedRoundValue ?? Number.NEGATIVE_INFINITY) - (left.expectedRoundValue ?? Number.NEGATIVE_INFINITY);
    }
    if (!underThreat && phase !== "late" && left.shanten !== right.shanten) return left.shanten - right.shanten;
    const leftInRange = left.shanten <= minimumShanten + 1;
    const rightInRange = right.shanten <= minimumShanten + 1;
    if (leftInRange !== rightInRange) return leftInRange ? -1 : 1;
    if ((underThreat || phase === "late") && !urgentPush && leftInRange && rightInRange) {
      const defenseWeight = protectLead ? 1.5 : 1;
      const leftAdjusted = (left.expectedRoundValue ?? Number.NEGATIVE_INFINITY) - (left.dealInProbability ?? left.danger ?? 0) * 8000 * defenseWeight;
      const rightAdjusted = (right.expectedRoundValue ?? Number.NEGATIVE_INFINITY) - (right.dealInProbability ?? right.danger ?? 0) * 8000 * defenseWeight;
      if (leftAdjusted !== rightAdjusted) return rightAdjusted - leftAdjusted;
    }
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
