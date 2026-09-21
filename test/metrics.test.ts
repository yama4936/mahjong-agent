import assert from "node:assert/strict";
import test from "node:test";
import { decide } from "../src/agent/decision.js";
import { parseGameState } from "../src/game/state.js";
import { summarizeDecisionMetrics } from "../src/logging/metrics.js";
import type { DecisionRecord } from "../src/logging/replay.js";

test("decision metrics expose explicit denominators and optional telemetry", async () => {
  const state = parseGameState({
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"], draw: "6p",
  });
  const decision = await decide(state, { mode: "advisor" });
  decision.jev = { actionId: "discard_E", confidence: .7, reasoning: "test", model: "test" } as any;
  const record: DecisionRecord = {
    schemaVersion: 1, id: "r1", timestamp: new Date(0).toISOString(), state, decision,
    evidence: { recognition: { backend: "template", tiles: [], confidence: 1, ambiguityMargin: 1, safe: true }, recognitionRetries: 2 },
    executionEvidence: { status: "verified", actionId: decision.selectedActionId,
      receipt: { clicked: true, action: "discard", actionTiming: { deadlineMet: false } } as any },
    actualResult: { won: true, dealIn: false, tenpaiAtDraw: true, roundId: "east-1", winTurn: 9 },
  };
  const result = summarizeDecisionMetrics([record]);
  assert.equal(result.winRate, 1);
  assert.equal(result.dealInRate, 0);
  assert.equal(result.deadlineMissRate, 1);
  assert.equal(result.recognitionRetries, 2);
  assert.equal(result.averageWinTurn, 9);
  assert.equal(result.averageSelectedShanten, decision.candidates[0]?.shanten);
  assert.equal(result.jevLocalComparable, 1);
});

test("decision metrics do not count missing outcomes as losses", () => {
  assert.equal(summarizeDecisionMetrics([]).winRate, null);
  assert.equal(summarizeDecisionMetrics([]).deadlineMissRate, null);
});
