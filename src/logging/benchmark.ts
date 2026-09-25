import type { DecisionRecord } from "./replay.js";
import { groupByRound, roundBoolean } from "./roundOutcomes.js";

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
  const winLabels = completed.filter((group) => roundBoolean(group, "won") !== null);
  const dealInLabels = completed.filter((group) => roundBoolean(group, "dealIn") !== null);
  const wins = winLabels.filter((group) => roundBoolean(group, "won") === true).length;
  const dealIns = dealInLabels.filter((group) => roundBoolean(group, "dealIn") === true).length;
  const pointDeltas = completed.flatMap((group) => {
    const values = new Set(group.flatMap((record) => typeof record.actualResult?.pointsDelta === "number" ? [record.actualResult.pointsDelta] : []));
    return values.size === 1 ? [...values] : [];
  });
  const ranks = completed.flatMap((group) => {
    const values = new Set(group.flatMap((record) => typeof record.actualResult?.finalRank === "number" ? [record.actualResult.finalRank] : []));
    return values.size === 1 ? [...values] : [];
  });
  return {
    decisions: records.length,
    completedOutcomes: completed.length,
    wins,
    dealIns,
    winRate: winLabels.length ? wins / winLabels.length : null,
    dealInRate: dealInLabels.length ? dealIns / dealInLabels.length : null,
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
