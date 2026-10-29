import type { DecisionRecord } from "./replay.js";

type BooleanOutcome = "won" | "dealIn" | "tenpaiAtDraw";

export function groupByRound(records: readonly DecisionRecord[]): DecisionRecord[][] {
  const groups = new Map<string, DecisionRecord[]>();
  for (const record of records) {
    const key = String(record.actualResult?.round?.observedAt ?? record.actualResult?.roundId ?? record.id);
    const group = groups.get(key) ?? [];
    group.push(record);
    groups.set(key, group);
  }
  return [...groups.values()];
}

function uniqueValue<T>(observations: readonly T[]): T | null {
  const values = new Set(observations);
  return values.size === 1 ? [...values][0]! : null;
}

/** Missing and conflicting labels remain unknown rather than becoming losses. */
export function roundBoolean(group: readonly DecisionRecord[], field: BooleanOutcome): boolean | null {
  return uniqueValue(group.flatMap((record) => {
    const value = record.actualResult?.[field];
    return typeof value === "boolean" ? [value] : [];
  }));
}

export function roundNumber(group: readonly DecisionRecord[], field: "pointsDelta" | "finalRank"): number | null {
  return uniqueValue(group.flatMap((record) => {
    const value = record.actualResult?.[field];
    return typeof value === "number" ? [value] : [];
  }));
}

export function summarizeRoundBooleans(groups: readonly (readonly DecisionRecord[])[], field: BooleanOutcome) {
  let samples = 0;
  let positive = 0;
  for (const group of groups) {
    const value = roundBoolean(group, field);
    if (value === null) continue;
    samples += 1;
    if (value) positive += 1;
  }
  return { samples, positive };
}
