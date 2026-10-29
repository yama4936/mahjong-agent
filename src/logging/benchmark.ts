import type { DecisionRecord } from "./replay.js";
import { groupByRound, roundNumber, summarizeRoundBooleans } from "./roundOutcomes.js";

export interface BenchmarkGroup {
  decisions: number;
  completedOutcomes: number;
  wins: number;
  dealIns: number;
  winRate: number | null;
  dealInRate: number | null;
  averagePointsDelta: number | null;
  averageFinalRank: number | null;
}

function summarizeGroup(records: readonly DecisionRecord[]): BenchmarkGroup {
  const completed = groupByRound(records).filter((group) => group.some((record) => record.actualResult));
  const wins = summarizeRoundBooleans(completed, "won");
  const dealIns = summarizeRoundBooleans(completed, "dealIn");
  const pointDeltas = completed.flatMap((group) => {
    const value = roundNumber(group, "pointsDelta");
    return value === null ? [] : [value];
  });
  const ranks = completed.flatMap((group) => {
    const value = roundNumber(group, "finalRank");
    return value === null ? [] : [value];
  });
  return {
    decisions: records.length,
    completedOutcomes: completed.length,
    wins: wins.positive,
    dealIns: dealIns.positive,
    winRate: wins.samples ? wins.positive / wins.samples : null,
    dealInRate: dealIns.samples ? dealIns.positive / dealIns.samples : null,
    averagePointsDelta: pointDeltas.length ? pointDeltas.reduce((sum, value) => sum + value, 0) / pointDeltas.length : null,
    averageFinalRank: ranks.length ? ranks.reduce((sum, value) => sum + value, 0) / ranks.length : null,
  };
}

export function summarizeBenchmark(records: readonly DecisionRecord[]) {
  const grouped = new Map<string, DecisionRecord[]>();
  for (const record of records) {
    const model = record.decision.jev?.model;
    const key = model ? `${record.decision.source}:${model}` : record.decision.source;
    const group = grouped.get(key) ?? [];
    group.push(record);
    grouped.set(key, group);
  }
  return {
    overall: summarizeGroup(records),
    byDecisionSource: Object.fromEntries([...grouped].map(([key, group]) => [key, summarizeGroup(group)])),
  };
}
