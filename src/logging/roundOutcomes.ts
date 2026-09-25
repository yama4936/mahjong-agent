import type { DecisionRecord } from "./replay.js";

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

export function roundBoolean(group: readonly DecisionRecord[], field: "won" | "dealIn" | "tenpaiAtDraw"): boolean | null {
  const values = new Set(group.flatMap((record) => {
    const value = record.actualResult?.[field];
    return typeof value === "boolean" ? [value] : [];
  }));
  return values.size === 1 ? [...values][0]! : null;
}
