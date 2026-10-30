import type { GameState } from "../game/state.js";
import { doraFromIndicator, isRedTile, isTerminalOrHonor, normalizeTile, parseGameTile, tileIndex } from "../game/tiles.js";
import type { DiscardEvaluation } from "../game/ukeire.js";
import { scoreOpenTenpai } from "./openTenpaiScore.js";

export const HEURISTIC_EVALUATION_MODEL = "heuristic-v5";

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function currentRank(state: GameState): number {
  const score = state.scores[state.seat];
  if (score === undefined) return 2;
  return [...Object.values(state.scores)].sort((a, b) => b - a).findIndex((value) => value === score) + 1;
}

export function estimateHeuristicRonPoints(han: number, dealer: boolean, sevenPairs = false): number {
  if (!Number.isInteger(han) || han < 1) throw new Error("Estimated han must be a positive integer");
  if (sevenPairs && han < 5) {
    return Math.ceil(25 * 2 ** (han + 2) * (dealer ? 6 : 4) / 100) * 100;
  }
  // Cap counted hands at one yakuman, matching the independent scorer default.
  const nonDealer = [0, 1000, 2000, 3900, 7700, 8000, 12000, 12000,
    16000, 16000, 16000, 24000, 24000, 32000];
  const value = nonDealer[Math.min(nonDealer.length - 1, Math.max(1, han))]!;
  return dealer ? Math.round(value * 1.5 / 100) * 100 : value;
}

/**
 * Produces bounded, inspectable estimates for comparison and Jev context.
 * These are deliberately labelled heuristic; they are not calibrated game
 * outcome probabilities and must not independently unlock Auto Mode.
 */
export function evaluateRoundValue(candidate: DiscardEvaluation, state: GameState): DiscardEvaluation {
  const tiles = [...state.hand, ...(state.draw ? [state.draw] : [])].map(parseGameTile);
  const discardedIndex = tiles.indexOf(candidate.tile);
  if (discardedIndex < 0) throw new Error("Value evaluation requires a discard present in the concealed hand");
  tiles.splice(discardedIndex, 1);
  tiles.push(...state.melds.flatMap(meld => meld.tiles));
  const dora = state.doraIndicators.map(doraFromIndicator);
  const retainedDora = tiles.reduce((sum, tile) => sum
    + dora.filter(bonus => bonus === normalizeTile(tile)).length + (isRedTile(tile) ? 1 : 0), 0);
  const closed = state.openMelds === 0 || (state.melds.length === state.openMelds
    && state.melds.every(meld => meld.type === "ankan"));
  const likelyRiichiHan = state.riichiDeclared || closed ? 1 : 0;
  const sevenPairs = closed && candidate.form === "chiitoitsu";
  const baseHan = sevenPairs ? 2 + (tiles.every(tile => !isTerminalOrHonor(tileIndex(tile))) ? 1 : 0) : 1;
  const openTenpaiScore = scoreOpenTenpai(candidate, state);
  // Ordinary scoring cannot rule out last-tile situational yaku. Retain the
  // existing fallback there and when meld/wind/physical evidence is unknown.
  const ordinaryEstimate = openTenpaiScore && !(state.remainingTiles !== undefined && state.remainingTiles <= 4)
    ? openTenpaiScore : undefined;
  const noShortestOrdinaryRoute = candidate.shanten === 1 && state.openMelds > 0
    && state.remainingTiles !== undefined && state.remainingTiles > 4
    && candidate.openOneShantenYaku?.status === "known"
    && candidate.openOneShantenYaku.scope === "shortest_structural_progress_to_ordinary_open_win_only"
    && candidate.openOneShantenYaku.discardTile === candidate.tile
    && candidate.openOneShantenYaku.ordinaryProgressUkeire === 0;
  const estimatedValue = noShortestOrdinaryRoute ? 0 : ordinaryEstimate?.conditionalConservativePoints
    ?? estimateHeuristicRonPoints(baseHan + likelyRiichiHan + retainedDora, state.seat === "east", sevenPairs);

  const wallExhausted = state.remainingTiles === 0;
  const turnsLeftFactor = state.remainingTiles === undefined
    ? clamp((18 - state.turn) / 14, 0.15, 1.15)
    : wallExhausted ? 0 : clamp(state.remainingTiles / 55, 0.15, 1.15);
  const ukeireFactor = clamp(candidate.ukeire / 20, 0.12, 1.6);
  const winningUkeire = ordinaryEstimate?.winningUkeire ?? candidate.ukeire;
  const winningUkeireFactor = clamp(winningUkeire / 20, 0.12, 1.6);
  const winBase = candidate.shanten <= 0 ? 0.34 : candidate.shanten === 1 ? 0.18 : candidate.shanten === 2 ? 0.075 : 0.025;
  const unadjustedWinProbability = wallExhausted || noShortestOrdinaryRoute || ordinaryEstimate && winningUkeire === 0 ? 0
    : clamp(winBase * winningUkeireFactor * turnsLeftFactor, 0.005, 0.72);
  // A coarse four-player opportunity split, not a calibrated ron/tsumo
  // model. Unknown temporary and riichi-pass furiten are not inferred from
  // a missing river match. Without scoring evidence, the existing estimate
  // cannot distinguish a ron-eligible hand from a tsumo-only dama hand.
  // Ordinary open scoring identifies legal yaku by winning mode. Weight its
  // separate ron and tsumo copies once, including already-known furiten;
  // applying the generic furiten factor again would penalize tsumo-only yaku.
  const opportunityRatio = ordinaryEstimate && winningUkeire > 0
    ? (3 * ordinaryEstimate.ronUkeire + ordinaryEstimate.tsumoUkeire) / (4 * winningUkeire)
    : 1;
  const winProbability = unadjustedWinProbability * opportunityRatio;
  const tenpaiBase = candidate.shanten <= 0 ? 1 : candidate.shanten === 1 ? 0.48 : candidate.shanten === 2 ? 0.22 : 0.08;
  const tenpaiProbability = wallExhausted
    ? (candidate.shanten <= 0 ? 1 : 0)
    : clamp(tenpaiBase * Math.sqrt(ukeireFactor) * Math.sqrt(turnsLeftFactor), 0.01, 1);
  const dealInProbability = clamp(candidate.danger ?? 0, 0, 0.6);

  const rank = currentRank(state);
  const defenseMultiplier = rank === 1 ? 1.25 : rank === 4 ? 0.82 : 1;
  const expectedRoundValue = Math.round(
    winProbability * estimatedValue
    - dealInProbability * 8000 * defenseMultiplier
    + tenpaiProbability * 450,
  );

  return {
    ...candidate,
    estimatedValue,
    winProbability,
    tenpaiProbability,
    dealInProbability,
    expectedRoundValue,
    evaluationModel: HEURISTIC_EVALUATION_MODEL,
    ...(openTenpaiScore ? { openTenpaiScore, openTenpaiScoreApplied: Boolean(ordinaryEstimate) } : {}),
  };
}
