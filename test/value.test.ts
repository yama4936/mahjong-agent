import assert from "node:assert/strict";
import test from "node:test";
import { decide } from "../src/agent/decision.js";
import { deterministicAdvice } from "../src/evaluation/advisor.js";
import { parseGameState } from "../src/game/state.js";
import { evaluateRoundValue } from "../src/evaluation/value.js";
import type { DiscardEvaluation } from "../src/game/ukeire.js";

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
    assert.equal(candidate.evaluationModel, "heuristic-v2");
    assert.ok(candidate.estimatedValue! >= 1000);
    assert.ok(candidate.winProbability! > 0 && candidate.winProbability! <= 1);
    assert.ok(candidate.tenpaiProbability! > 0 && candidate.tenpaiProbability! <= 1);
    assert.ok(Number.isFinite(candidate.expectedRoundValue));
  }
});

test("heuristic value counts repeated indicators, meld dora and declared riichi", () => {
  const candidate: DiscardEvaluation = {
    actionId: "discard_E", action: "discard", tile: "E", shanten: 1,
    form: "standard", effectiveTiles: [], ukeire: 20,
  };
  const base = state;
  const value = (input: typeof base) => evaluateRoundValue(candidate, input).estimatedValue;
  assert.equal(value(base), 3900);
  assert.equal(value({ ...base, doraIndicators: ["4m", "4m"] }), 7700);
  assert.equal(value({ ...base, riichiDeclared: true }), value(base));
  const open = { ...base, hand: base.hand.filter(tile => !["4m", "5m", "6m"].includes(tile)), openMelds: 1,
    melds: [{ type: "chi" as const, tiles: ["4m", "0m", "6m"] as const }] };
  const openState = parseGameState(open);
  assert.equal(value(openState), 3900); // assumed base han + indicator dora + red dora
  const ankan = parseGameState({ ...base, hand: base.hand.slice(3), doraIndicators: [], openMelds: 1,
    melds: [{ type: "ankan", tiles: ["2p", "2p", "2p", "2p"] }] });
  assert.equal(value(ankan), 2000); // concealed kan does not remove the riichi assumption
  assert.equal(value({ ...ankan, melds: [] }), 1000); // unknown group is not certified closed
  assert.throws(() => evaluateRoundValue({ ...candidate, tile: "N" }, base), /discard present/);
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
