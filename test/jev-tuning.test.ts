import assert from "node:assert/strict";
import test from "node:test";
import { summarizeJevTrials, type JevTuningTrial } from "../src/jev/tuning.js";

function trial(overrides: Partial<JevTuningTrial>): JevTuningTrial {
  return {
    recordId: "record",
    expectedActionId: "discard_E",
    selectedActionId: "discard_E",
    correct: true,
    expectedProbability: 0.8,
    confidence: 0.8,
    model: "jev-test",
    promptVersion: "mahjong-discard-v2",
    latencyMs: 100,
    inputTokens: 1000,
    ...overrides,
  };
}

test("Jev tuning summary reports accuracy, probability quality and threshold coverage", () => {
  const summary = summarizeJevTrials([
    trial({ confidence: 0.9, expectedProbability: 0.8 }),
    trial({ selectedActionId: "discard_1m", correct: false, confidence: 0.6, expectedProbability: 0.2, latencyMs: 200 }),
  ]);
  assert.equal(summary.labeledRecords, 2);
  assert.equal(summary.accuracy, 0.5);
  assert.equal(summary.meanExpectedProbability, 0.5);
  assert.equal(summary.meanConfidence, 0.75);
  assert.equal(summary.meanLatencyMs, 150);
  assert.equal(summary.totalInputTokens, 2000);
  assert.equal(summary.thresholds.find((entry) => entry.threshold === 0.8)?.coverage, 0.5);
  assert.equal(summary.thresholds.find((entry) => entry.threshold === 0.8)?.accuracy, 1);
});
