import assert from "node:assert/strict";
import test from "node:test";
import { decide } from "../src/agent/decision.js";
import { deterministicAdvice } from "../src/evaluation/advisor.js";
import { parseGameState } from "../src/game/state.js";

const state = parseGameState({
  seat: "south",
  scores: { east: 25000, south: 25000, west: 25000, north: 25000 },
  hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"],
  draw: "6p",
  doraIndicators: ["4m"],
  recognitionConfidence: 1,
});

test("advisor attaches bounded heuristic outcome estimates", () => {
  const result = deterministicAdvice(state);
  for (const candidate of result.candidates) {
    assert.equal(candidate.evaluationModel, "heuristic-v1");
    assert.ok(candidate.estimatedValue! >= 1000);
    assert.ok(candidate.winProbability! > 0 && candidate.winProbability! <= 1);
    assert.ok(candidate.tenpaiProbability! > 0 && candidate.tenpaiProbability! <= 1);
    assert.ok(Number.isFinite(candidate.expectedRoundValue));
  }
});

test("auto requires independently trusted public state", async () => {
  const result = await decide(state, { mode: "auto" });
  assert.ok(result.safety.reasons.includes("public_state_confidence_below_threshold"));
  assert.equal(result.executable, false);
});

test("red and ordinary fives remain distinct discard candidates", () => {
  const redState = parseGameState({
    hand: ["0m", "5m", "1m", "2m", "3m", "1p", "2p", "3p", "4p", "5p", "6p", "7s", "8s"],
    draw: "9s",
    recognitionConfidence: 1,
  });
  assert.equal(redState.hand[0], "0m");
  const candidates = deterministicAdvice(redState).candidates;
  const red = candidates.find((candidate) => candidate.tile === "0m")!;
  const ordinary = candidates.find((candidate) => candidate.tile === "5m")!;
  assert.ok(red);
  assert.ok(ordinary);
  assert.notEqual(red.actionId, ordinary.actionId);
  assert.ok(ordinary.estimatedValue! > red.estimatedValue!);
  assert.ok(candidates.indexOf(ordinary) < candidates.indexOf(red));
});

test("an active threat orders viable choices by defensive round EV", () => {
  const threatened = parseGameState({
    ...state,
    opponents: [
      { seat: "east", discards: ["E"], riichi: true },
      { seat: "west", discards: [] },
      { seat: "north", discards: [] },
    ],
  });
  const result = deterministicAdvice(threatened);
  const minimumShanten = Math.min(...result.candidates.map((candidate) => candidate.shanten));
  const viable = result.candidates.filter((candidate) => candidate.shanten <= minimumShanten + 1);
  assert.equal(result.candidates[0]!.expectedRoundValue, Math.max(...viable.map((candidate) => candidate.expectedRoundValue!)));
});
