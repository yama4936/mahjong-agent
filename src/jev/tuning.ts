import { deterministicAdvice } from "../evaluation/advisor.js";
import { parseGameState } from "../game/state.js";
import type { DecisionRecord } from "../logging/replay.js";
import { JevClient, type JevPromptProfile } from "./client.js";

export interface JevTuningTrial {
  recordId: string;
  expectedActionId: string;
  selectedActionId: string;
  correct: boolean;
  expectedProbability: number;
  confidence: number;
  model: string;
  promptVersion: string;
  latencyMs: number;
  inputTokens: number;
}

export interface JevThresholdResult {
  threshold: number;
  automaticDecisions: number;
  coverage: number;
  accuracy: number | null;
}

export interface JevTuningSummary {
  labeledRecords: number;
  accuracy: number | null;
  meanExpectedProbability: number | null;
  logLoss: number | null;
  meanConfidence: number | null;
  meanLatencyMs: number | null;
  totalInputTokens: number;
  thresholds: JevThresholdResult[];
}

export async function evaluateJevProfile(
  records: readonly DecisionRecord[],
  options: {
    apiKey: string;
    endpoint: string;
    model: string;
    profile: JevPromptProfile;
  },
): Promise<{ profile: JevPromptProfile; trials: JevTuningTrial[]; summary: JevTuningSummary }> {
  const labeled = records.flatMap((record) => {
    const expectedActionId = record.actualResult?.expertActionId;
    return typeof expectedActionId === "string" ? [{ record, expectedActionId }] : [];
  });
  if (labeled.length === 0) {
    throw new Error("No tuning labels found; attach actualResult.expertActionId to replay JSON files first");
  }
  const client = new JevClient(options.apiKey, options.endpoint, options.model, options.profile);
  const trials: JevTuningTrial[] = [];
  for (const { record, expectedActionId } of labeled) {
    const state = parseGameState(record.state);
    const candidates = deterministicAdvice(state).candidates;
    if (!candidates.some((candidate) => candidate.actionId === expectedActionId)) {
      throw new Error(`Expert action ${expectedActionId} is not legal in replay ${record.id}`);
    }
    const decision = await client.chooseDiscard(state, candidates);
    trials.push({
      recordId: record.id,
      expectedActionId,
      selectedActionId: decision.actionId,
      correct: decision.actionId === expectedActionId,
      expectedProbability: decision.probabilities[expectedActionId]!,
      confidence: decision.confidence,
      model: decision.model,
      promptVersion: decision.promptVersion,
      latencyMs: decision.latencyMs,
      inputTokens: decision.usage?.input_tokens ?? 0,
    });
  }
  return { profile: options.profile, trials, summary: summarizeJevTrials(trials) };
}

export function summarizeJevTrials(trials: readonly JevTuningTrial[]): JevTuningSummary {
  const count = trials.length;
  const mean = (values: readonly number[]) => values.reduce((sum, value) => sum + value, 0) / values.length;
  const thresholds = [0.5, 0.6, 0.7, 0.8, 0.9].map((threshold) => {
    const automatic = trials.filter((trial) => trial.confidence >= threshold);
    return {
      threshold,
      automaticDecisions: automatic.length,
      coverage: count ? automatic.length / count : 0,
      accuracy: automatic.length ? automatic.filter((trial) => trial.correct).length / automatic.length : null,
    };
  });
  return {
    labeledRecords: count,
    accuracy: count ? trials.filter((trial) => trial.correct).length / count : null,
    meanExpectedProbability: count ? mean(trials.map((trial) => trial.expectedProbability)) : null,
    logLoss: count ? mean(trials.map((trial) => -Math.log(Math.max(trial.expectedProbability, 1e-12)))) : null,
    meanConfidence: count ? mean(trials.map((trial) => trial.confidence)) : null,
    meanLatencyMs: count ? mean(trials.map((trial) => trial.latencyMs)) : null,
    totalInputTokens: trials.reduce((sum, trial) => sum + trial.inputTokens, 0),
    thresholds,
  };
}
