import assert from "node:assert/strict";
import test from "node:test";
import { decide } from "../src/agent/decision.js";
import { parseGameState } from "../src/game/state.js";
import { compareReplayPolicies, deterministicReplayPolicy, strategyReplayPolicies, type ReplayPolicy } from "../src/logging/policyComparison.js";
import type { DecisionRecord } from "../src/logging/replay.js";

test("policy comparison runs the same replay through extensible policies", async () => {
  const state = parseGameState({
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"],
    draw: "6p",
  });
  const recorded = await decide(state, { mode: "advisor" });
  const record: DecisionRecord = {
    schemaVersion: 1, id: "r1", timestamp: new Date(0).toISOString(), state, decision: recorded,
    actualResult: { expertActionId: recorded.selectedActionId },
  };
  const alternative: ReplayPolicy = { name: "future-search", decide: async () => ({ actionId: "discard_6p", confidence: 0.7 }) };
  const result = await compareReplayPolicies([record], [deterministicReplayPolicy(), alternative]);
  assert.equal(result.summary.recorded!.expertAccuracy, 1);
  assert.equal(result.summary["deterministic-current"]!.expertAccuracy, 1);
  assert.equal(result.summary["future-search"]!.expertAccuracy, 0);
  assert.equal(result.pairwiseAgreement["recorded::deterministic-current"]!.rate, 1);
  assert.equal(result.pairwiseAgreement["recorded::future-search"]!.rate, 0);
});

test("standard A/B suite exposes stable profile IDs and per-policy metrics", async () => {
  assert.deepEqual(strategyReplayPolicies().map((policy) => policy.name), [
    "current", "no-unconditional-call", "phase-efficiency", "placement-push-fold",
  ]);
  const state = parseGameState({
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"], draw: "6p",
  });
  const decision = await decide(state, { mode: "advisor" });
  const record: DecisionRecord = { schemaVersion: 1, id: "metrics", timestamp: new Date(0).toISOString(), state, decision };
  const result = await compareReplayPolicies([record], strategyReplayPolicies());
  assert.equal(result.summary.current!.metrics.decisions, 1);
  assert.equal(result.summary["phase-efficiency"]!.metrics.averageSelectedShanten, decision.candidates[0]?.shanten);
});

test("policy comparison records one policy failure without aborting the corpus", async () => {
  const state = parseGameState({
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"], draw: "6p",
  });
  const decision = await decide(state, { mode: "advisor" });
  const record: DecisionRecord = { schemaVersion: 1, id: "r1", timestamp: new Date(0).toISOString(), state, decision };
  const failing: ReplayPolicy = { name: "failing", decide: async () => { throw new Error("unavailable"); } };
  const result = await compareReplayPolicies([record], [failing]);
  assert.equal(result.summary.failing!.errors, 1);
  assert.deepEqual(result.rows[0]?.decisions.failing, { error: "unavailable" });
});
