import type { GameState } from "../game/state.js";
import { doraFromIndicator, isRedTile, normalizeTile, parseGameTile } from "../game/tiles.js";
import type { DiscardEvaluation } from "../game/ukeire.js";

export const HEURISTIC_EVALUATION_MODEL = "heuristic-v1";

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function currentRank(state: GameState): number {
  const score = state.scores[state.seat];
  if (score === undefined) return 2;
  return [...Object.values(state.scores)].sort((a, b) => b - a).findIndex((value) => value === score) + 1;
}

function pointValue(han: number, dealer: boolean): number {
  const nonDealer = [0, 1000, 2000, 3900, 7700, 12000, 12000];
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
  tiles.splice(tiles.indexOf(candidate.tile), 1);
  const dora = state.doraIndicators.map(doraFromIndicator);
  const retainedDora = tiles.reduce((sum, tile) => sum + (dora.includes(normalizeTile(tile)) ? 1 : 0) + (isRedTile(tile) ? 1 : 0), 0);
  const likelyRiichiHan = state.openMelds === 0 && !state.riichiDeclared ? 1 : 0;
  const estimatedValue = pointValue(1 + likelyRiichiHan + retainedDora, state.seat === "east");

  const turnsLeftFactor = state.remainingTiles === undefined
    ? clamp((18 - state.turn) / 14, 0.15, 1.15)
    : clamp(state.remainingTiles / 55, 0.15, 1.15);
  const ukeireFactor = clamp(candidate.ukeire / 20, 0.12, 1.6);
  const winBase = candidate.shanten <= 0 ? 0.34 : candidate.shanten === 1 ? 0.18 : candidate.shanten === 2 ? 0.075 : 0.025;
  const winProbability = clamp(winBase * ukeireFactor * turnsLeftFactor, 0.005, 0.72);
  const tenpaiBase = candidate.shanten <= 0 ? 1 : candidate.shanten === 1 ? 0.48 : candidate.shanten === 2 ? 0.22 : 0.08;
  const tenpaiProbability = clamp(tenpaiBase * Math.sqrt(ukeireFactor) * Math.sqrt(turnsLeftFactor), 0.01, 1);
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
  };
}
