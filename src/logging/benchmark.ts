import type { DecisionRecord } from "./replay.js";

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
  const completed = records.filter((record) => record.actualResult);
  const winLabels = completed.filter((record) => typeof record.actualResult?.won === "boolean");
  const dealInLabels = completed.filter((record) => typeof record.actualResult?.dealIn === "boolean");
  const wins = winLabels.filter((record) => record.actualResult?.won === true).length;
  const dealIns = dealInLabels.filter((record) => record.actualResult?.dealIn === true).length;
  const pointDeltas = completed.flatMap((record) => typeof record.actualResult?.pointsDelta === "number" ? [record.actualResult.pointsDelta] : []);
  const ranks = completed.flatMap((record) => typeof record.actualResult?.finalRank === "number" ? [record.actualResult.finalRank] : []);
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
