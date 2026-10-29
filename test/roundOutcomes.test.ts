import assert from "node:assert/strict";
import test from "node:test";
import { decide } from "../src/agent/decision.js";
import { parseGameState } from "../src/game/state.js";
import { summarizeBenchmark } from "../src/logging/benchmark.js";
import { summarizeDecisionMetrics } from "../src/logging/metrics.js";
import type { ActualResult, DecisionRecord } from "../src/logging/replay.js";

const state = parseGameState({
  hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"], draw: "6p",
});
const decision = await decide(state, { mode: "advisor" });

function record(id: string, actualResult?: ActualResult, called = false): DecisionRecord {
  return {
    schemaVersion: 1, id, timestamp: new Date(0).toISOString(), state,
    decision: called ? { ...decision, selectedAction: {
      id: "chi_3p", action: "chi", tile: "3p", consumedTiles: ["4p", "5p"],
    } } : decision,
    ...(actualResult ? { actualResult } : {}),
  };
}

test("reports exclude conflicting labels per field and retain zero-valued outcomes", () => {
  const records = [
    record("win", { roundId: "win", won: true, pointsDelta: 1000, finalRank: 1 }),
    record("win-call", { roundId: "win", dealIn: false, pointsDelta: 1000, finalRank: 1 }, true),
    record("draw", { roundId: "draw", won: false, dealIn: false, pointsDelta: 0, finalRank: 3 }),
    record("draw-call", { roundId: "draw" }, true),
    record("conflict-a", { roundId: "conflict", won: true, dealIn: true, pointsDelta: -2000, finalRank: 2 }, true),
    record("conflict-b", { roundId: "conflict", won: false, dealIn: true, pointsDelta: 2000, finalRank: 4 }),
    record("unknown", { roundId: "unknown" }, true),
    record("legacy"),
  ];
  const benchmark = summarizeBenchmark(records).overall;
  assert.deepEqual(benchmark, {
    decisions: 8, completedOutcomes: 4, wins: 1, dealIns: 1,
    winRate: 0.5, dealInRate: 1 / 3, averagePointsDelta: 500, averageFinalRank: 2,
  });
  const metrics = summarizeDecisionMetrics(records);
  assert.equal(metrics.completedRounds, 3);
  assert.equal(metrics.winSamples, 2);
  assert.equal(metrics.dealInSamples, 3);
  assert.equal(metrics.winRate, benchmark.winRate);
  assert.equal(metrics.dealInRate, benchmark.dealInRate);
  assert.equal(metrics.calledRounds, 4);
  assert.equal(metrics.calledRoundWins, 1);
  assert.equal(metrics.calledRoundWinSamples, 2);
  assert.equal(metrics.calledRoundWinRate, 0.5);
  assert.equal(summarizeDecisionMetrics([...records].reverse()).calledRoundWinRate, 0.5);
});

test("reports prefer observed round identity and keep legacy records separate", () => {
  const round = {
    observedAt: "2026-10-29T00:00:00.000Z", screenshot: "round.png",
    screenState: "round_result" as const, screenConfidence: 1,
  };
  const records = [
    record("observed-a", { round, roundId: "first-id", won: true }),
    record("observed-b", { round, roundId: "second-id", dealIn: false }, true),
    record("id-only", { roundId: "first-id", won: false, dealIn: true }, true),
    record("legacy-a", { won: true, dealIn: false }, true),
    record("legacy-b", { won: false, dealIn: false }),
  ];
  const benchmark = summarizeBenchmark(records).overall;
  assert.equal(benchmark.completedOutcomes, 4);
  assert.equal(benchmark.winRate, 0.5);
  assert.equal(benchmark.dealInRate, 0.25);
  const metrics = summarizeDecisionMetrics(records);
  assert.equal(metrics.completedRounds, 4);
  assert.equal(metrics.winSamples, 4);
  assert.equal(metrics.winRate, benchmark.winRate);
  assert.equal(metrics.dealInRate, benchmark.dealInRate);
  assert.equal(metrics.calledRounds, 3);
  assert.equal(metrics.calledRoundWins, 2);
  assert.equal(metrics.calledRoundWinSamples, 3);
  assert.equal(metrics.calledRoundWinRate, 2 / 3);
});
