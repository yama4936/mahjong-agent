import type { DecisionRecord } from "./replay.js";
import { groupByRound, roundBoolean } from "./roundOutcomes.js";

export interface DecisionMetrics {
  decisions: number;
  completedRounds: number;
  wins: number;
  winRate: number | null;
  dealIns: number;
  dealInRate: number | null;
  riichi: number;
  riichiRate: number | null;
  calls: number;
  callRate: number | null;
  calledRounds: number;
  calledRoundWins: number;
  calledRoundWinRate: number | null;
  averageWinTurn: number | null;
  tenpaiReached: number;
  tenpaiRate: number | null;
  deadlineSamples: number;
  deadlineMisses: number;
  deadlineMissRate: number | null;
  recognitionRetries: number;
  averageSelectedShanten: number | null;
  averageSelectedUkeire: number | null;
  jevLocalComparable: number;
  jevLocalDifferences: number;
  jevLocalDifferenceRate: number | null;
}

const rate = (n: number, d: number): number | null => d ? n / d : null;
const average = (values: number[]): number | null => values.length
  ? values.reduce((sum, value) => sum + value, 0) / values.length : null;

/**
 * Aggregate optional replay telemetry without treating missing observations as
 * false. This keeps legacy corpora usable while making every denominator
 * explicit for live/A-B dashboards.
 */
export function summarizeDecisionMetrics(records: readonly DecisionRecord[]): DecisionMetrics {
  const rounds = groupByRound(records);
  const completed = rounds.filter((group) => roundBoolean(group, "won") !== null || roundBoolean(group, "dealIn") !== null);
  const winLabels = completed.filter((group) => roundBoolean(group, "won") !== null);
  const dealInLabels = completed.filter((group) => roundBoolean(group, "dealIn") !== null);
  const wins = winLabels.filter((group) => roundBoolean(group, "won") === true).length;
  const dealIns = dealInLabels.filter((group) => roundBoolean(group, "dealIn") === true).length;
  const actions = records.map((record) => record.decision.selectedAction?.action);
  const riichi = actions.filter((action) => action === "riichi").length;
  const callActions = new Set(["chi", "pon", "minkan", "ankan", "kakan"]);
  const calls = actions.filter((action) => action && callActions.has(action)).length;
  const roundKey = (record: DecisionRecord) => String(record.actualResult?.round?.observedAt
    ?? record.actualResult?.roundId ?? record.id);
  const calledRoundKeys = new Set(records.filter((record) => callActions.has(record.decision.selectedAction?.action))
    .map(roundKey));
  const wonRoundKeys = new Set(rounds.filter((group) => roundBoolean(group, "won") === true).map((group) => roundKey(group[0]!)));
  const selectedCandidates = records.flatMap((record) => {
    const selected = record.decision.candidates?.find((candidate) => candidate.actionId === record.decision.selectedActionId);
    return selected ? [selected] : [];
  });
  const timings = records.flatMap((record) => {
    const receipt = record.executionEvidence?.receipt as any;
    const timing = receipt?.actionTiming ?? receipt?.discard?.actionTiming;
    return timing && typeof timing.deadlineMet === "boolean" ? [timing] : [];
  });
  const comparable = records.flatMap((record) => {
    const local = record.decision.candidates?.[0]?.actionId;
    const jev = record.decision.jev?.actionId;
    return local && jev ? [{ local, jev }] : [];
  });
  const winTurns = records.flatMap((record) => record.actualResult?.won === true
    && typeof (record.actualResult as any).winTurn === "number" ? [(record.actualResult as any).winTurn] : []);
  const tenpaiObserved = records.filter((record) => typeof record.actualResult?.tenpaiAtDraw === "boolean");
  const retries = records.reduce((sum, record) => sum + Number((record.evidence as any)?.recognitionRetries ?? 0), 0);
  const differences = comparable.filter(({ local, jev }) => local !== jev).length;
  return {
    decisions: records.length, completedRounds: completed.length,
    wins, winRate: rate(wins, winLabels.length), dealIns, dealInRate: rate(dealIns, dealInLabels.length),
    riichi, riichiRate: rate(riichi, records.length), calls, callRate: rate(calls, records.length),
    calledRounds: calledRoundKeys.size,
    calledRoundWins: [...calledRoundKeys].filter((key) => wonRoundKeys.has(key)).length,
    calledRoundWinRate: rate([...calledRoundKeys].filter((key) => wonRoundKeys.has(key)).length, calledRoundKeys.size),
    averageWinTurn: average(winTurns),
    tenpaiReached: tenpaiObserved.filter((record) => record.actualResult?.tenpaiAtDraw === true).length,
    tenpaiRate: rate(tenpaiObserved.filter((record) => record.actualResult?.tenpaiAtDraw === true).length, tenpaiObserved.length),
    deadlineSamples: timings.length, deadlineMisses: timings.filter((timing) => !timing.deadlineMet).length,
    deadlineMissRate: rate(timings.filter((timing) => !timing.deadlineMet).length, timings.length),
    recognitionRetries: retries,
    averageSelectedShanten: average(selectedCandidates.map((candidate) => candidate.shanten)),
    averageSelectedUkeire: average(selectedCandidates.map((candidate) => candidate.ukeire)),
    jevLocalComparable: comparable.length, jevLocalDifferences: differences,
    jevLocalDifferenceRate: rate(differences, comparable.length),
  };
}
