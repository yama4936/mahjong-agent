import { decide } from "../agent/decision.js";
import { parseGameState, type GameState } from "../game/state.js";
import type { JevClient } from "../jev/client.js";
import type { DecisionRecord } from "./replay.js";
import { summarizeDecisionMetrics } from "./metrics.js";

export interface PolicyDecision {
  actionId: string;
  confidence: number;
}

export interface ReplayPolicy {
  name: string;
  decide(state: GameState): Promise<PolicyDecision>;
}

export interface PolicyComparisonRow {
  recordId: string;
  expertActionId?: string;
  decisions: Record<string, PolicyDecision | { error: string }>;
}

export function deterministicReplayPolicy(): ReplayPolicy {
  return {
    name: "deterministic-current",
    decide: async (state) => {
      const result = await decide(state, { mode: "advisor" });
      return { actionId: result.selectedActionId, confidence: result.confidence };
    },
  };
}

export type StrategyProfile = "current" | "no-unconditional-call" | "phase-efficiency" | "placement-push-fold";

/** Named, stable policy suite used by corpus A/B runs and CI reports. */
export function strategyReplayPolicies(): ReplayPolicy[] {
  const policy = (name: StrategyProfile): ReplayPolicy => ({
    name,
    decide: async (state) => {
      const result = await decide(state, { mode: "advisor" });
      if (name === "phase-efficiency" && state.phase === "self_turn" && (state.turn ?? 1) <= 6) {
        const minimumShanten = Math.min(...result.candidates.map((candidate) => candidate.shanten));
        const selected = result.candidates.filter((candidate) => candidate.shanten === minimumShanten)
          .sort((left, right) => right.ukeire - left.ukeire)[0];
        if (selected) return { actionId: selected.actionId, confidence: result.confidence };
      }
      if (name === "no-unconditional-call" && state.phase === "reaction") {
        const assessments = (result as any).callAssessments as Array<{ actionId?: string; recommended?: boolean }> | undefined;
        const approved = assessments?.find((assessment) => assessment.recommended && assessment.actionId);
        if (!approved) {
          const pass = result.legalActions.find((action) => action.action === "pass");
          if (pass) return { actionId: pass.id, confidence: result.confidence };
        }
        if (approved?.actionId) return { actionId: approved.actionId, confidence: result.confidence };
      }
      // placement-push-fold consumes the placement-aware choice produced by
      // the current strategy engine (including its exported hand plan).
      return { actionId: result.selectedActionId, confidence: result.confidence };
    },
  });
  return [policy("current"), policy("no-unconditional-call"), policy("phase-efficiency"), policy("placement-push-fold")];
}

export function jevReplayPolicy(client: JevClient): ReplayPolicy {
  return {
    name: "jev-current",
    decide: async (state) => {
      const result = await decide(state, { mode: "advisor", jev: client });
      const jevError = result.safety.reasons.find((reason) => reason.startsWith("jev_error:"));
      if (jevError) throw new Error(jevError);
      if (result.source !== "jev" && result.selectedAction.action !== "tsumo") throw new Error("Jev did not return a decision");
      return { actionId: result.selectedActionId, confidence: result.confidence };
    },
  };
}

export async function compareReplayPolicies(records: readonly DecisionRecord[], policies: readonly ReplayPolicy[]) {
  if (policies.length === 0) throw new Error("At least one replay policy is required");
  if (new Set(policies.map((policy) => policy.name)).size !== policies.length) throw new Error("Replay policy names must be unique");
  if (policies.some((policy) => policy.name === "recorded")) throw new Error("recorded is a reserved replay policy name");
  const rows: PolicyComparisonRow[] = [];
  for (const record of records) {
    const state = parseGameState(record.state);
    const decisions: PolicyComparisonRow["decisions"] = {
      "recorded": { actionId: record.decision.selectedActionId, confidence: record.decision.confidence },
    };
    for (const policy of policies) {
      try {
        decisions[policy.name] = await policy.decide(state);
      } catch (error) {
        decisions[policy.name] = { error: error instanceof Error ? error.message : String(error) };
      }
    }
    const expertActionId = typeof record.actualResult?.expertActionId === "string" ? record.actualResult.expertActionId : undefined;
    rows.push({ recordId: record.id, ...(expertActionId ? { expertActionId } : {}), decisions });
  }
  const policyNames = ["recorded", ...policies.map((policy) => policy.name)];
  const summary = Object.fromEntries(policyNames.map((name) => {
    const successful = rows.flatMap((row) => {
      const decision = row.decisions[name];
      return decision && "actionId" in decision ? [{ row, decision }] : [];
    });
    const labeled = successful.filter(({ row }) => row.expertActionId !== undefined);
    const metricRecords = successful.map(({ row, decision }) => {
      const original = records.find((record) => record.id === row.recordId)!;
      const candidate = original.decision.candidates?.find((item) => item.actionId === decision.actionId);
      const selectedAction = original.decision.legalActions?.find((action) => action.id === decision.actionId)
        ?? original.decision.selectedAction;
      return { ...original, decision: { ...original.decision, selectedActionId: decision.actionId,
        selectedAction, ...(candidate ? { candidates: [candidate, ...original.decision.candidates.filter((item) => item !== candidate)] } : {}) } };
    });
    return [name, {
      records: rows.length,
      decisions: successful.length,
      errors: rows.length - successful.length,
      expertLabels: labeled.length,
      expertMatches: labeled.filter(({ row, decision }) => decision.actionId === row.expertActionId).length,
      expertAccuracy: labeled.length ? labeled.filter(({ row, decision }) => decision.actionId === row.expertActionId).length / labeled.length : null,
      metrics: summarizeDecisionMetrics(metricRecords),
    }];
  }));
  const pairwiseAgreement: Record<string, { comparable: number; matches: number; rate: number | null }> = {};
  for (let leftIndex = 0; leftIndex < policyNames.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < policyNames.length; rightIndex += 1) {
      const left = policyNames[leftIndex]!;
      const right = policyNames[rightIndex]!;
      const comparable = rows.flatMap((row) => {
        const leftDecision = row.decisions[left];
        const rightDecision = row.decisions[right];
        return leftDecision && rightDecision && "actionId" in leftDecision && "actionId" in rightDecision
          ? [[leftDecision, rightDecision] as const] : [];
      });
      const matches = comparable.filter(([leftDecision, rightDecision]) => leftDecision.actionId === rightDecision.actionId).length;
      pairwiseAgreement[`${left}::${right}`] = { comparable: comparable.length, matches, rate: comparable.length ? matches / comparable.length : null };
    }
  }
  return { records: rows.length, summary, pairwiseAgreement, rows };
}
