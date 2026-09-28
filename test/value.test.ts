import assert from "node:assert/strict";
import test from "node:test";
import { decide } from "../src/agent/decision.js";
import { deterministicAdvice } from "../src/evaluation/advisor.js";
import { parseGameState } from "../src/game/state.js";
import { estimateHeuristicRonPoints, evaluateRoundValue } from "../src/evaluation/value.js";
import type { DiscardEvaluation } from "../src/game/ukeire.js";

const state = parseGameState({
  seat: "south",
  scores: { east: 25000, south: 25000, west: 25000, north: 25000 },
  hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"],
  draw: "6p",
  doraIndicators: ["4m"],
  recognitionConfidence: 1,
});

test("limit estimates preserve boundaries and cap counted hands at one yakuman", () => {
  for (const [han, points] of [[5, 8000], [6, 12000], [7, 12000], [8, 16000],
    [10, 16000], [11, 24000], [12, 24000], [13, 32000], [20, 32000]]) {
    assert.equal(estimateHeuristicRonPoints(han!, false), points);
    assert.equal(estimateHeuristicRonPoints(han!, true), points! * 1.5);
    assert.equal(estimateHeuristicRonPoints(han!, false, true), points);
  }
  for (const han of [0, -1, 1.5, NaN, Infinity]) assert.throws(() => estimateHeuristicRonPoints(han, false));
});

test("advisor attaches bounded heuristic outcome estimates", () => {
  const result = deterministicAdvice(state);
  for (const candidate of result.candidates) {
    assert.equal(candidate.evaluationModel, "heuristic-v4");
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
  assert.equal(value({ ...base, doraIndicators: ["4m", "4m", "4m"] }), 8000);
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

test("seven-pairs value uses two yaku han, simple tiles and fixed 25 fu", () => {
  const paired = parseGameState({ seat: "south",
    hand: ["2m", "2m", "3m", "3m", "4p", "4p", "5p", "5p", "6s", "6s", "7s", "7s", "8s"],
    draw: "E", doraIndicators: ["4p"] });
  const candidate: DiscardEvaluation = { actionId: "discard_E", action: "discard", tile: "E",
    shanten: 0, form: "chiitoitsu", effectiveTiles: [], ukeire: 3 };
  assert.equal(evaluateRoundValue(candidate, paired).estimatedValue, 12000);
  assert.equal(evaluateRoundValue(candidate, { ...paired, seat: "east" }).estimatedValue, 18000);
  assert.equal(evaluateRoundValue(candidate, { ...paired, doraIndicators: [] }).estimatedValue, 6400);
  const honor = { ...paired, hand: paired.hand.map(tile => tile === "8s" ? "N" as const : tile), doraIndicators: [] };
  assert.equal(evaluateRoundValue(candidate, honor).estimatedValue, 3200);
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

test("higher seven-pairs value does not force a dangerous cut when genbutsu preserves tenpai", () => {
  for (const turn of [7, 12, 16]) for (const remainingTiles of [4, 16, 40]) {
    const boundary = parseGameState({
      seat: "south", round: "south_3", turn, remainingTiles,
      scores: { east: 30000, south: 24000, west: 23000, north: 23000 },
      hand: ["2m", "2m", "3m", "3m", "4p", "4p", "5p", "5p", "6s", "6s", "7s", "7s", "8s"],
      draw: "E", doraIndicators: ["4p"],
      opponents: [{ seat: "east", discards: ["8s"], riichi: true }],
    });
    const advice = deterministicAdvice(boundary);
    const highValue = advice.candidates.find(candidate => candidate.tile === "E")!;
    const safe = advice.candidates.find(candidate => candidate.tile === "8s")!;
    assert.equal(highValue.estimatedValue, 12000);
    assert.equal(safe.estimatedValue, 8000);
    assert.equal(safe.shanten, 0);
    assert.equal(safe.danger, 0);
    assert.ok((highValue.danger ?? 0) > 0);
    assert.equal(advice.tile, "8s");
  }
});
