import { test } from "node:test";
import assert from "node:assert/strict";
import { doraFromIndicator } from "../src/game/tiles.js";
import { evaluateDiscards } from "../src/game/ukeire.js";
import { isAllLastRound, parseGameState } from "../src/game/state.js";
import { generateLegalActions } from "../src/game/actions.js";

const hand = ["1m", "9m", "1p", "2p", "3p", "4p", "5p", "6p", "1s", "2s", "3s", "E", "E", "P"];

test("sanma dora cycles between 1m and 9m, while yonma stays unchanged", () => {
  assert.equal(doraFromIndicator("1m", "sanma"), "9m");
  assert.equal(doraFromIndicator("9m", "sanma"), "1m");
  assert.equal(doraFromIndicator("1m"), "2m");
  assert.equal(doraFromIndicator("9m"), "1m");
  assert.equal(doraFromIndicator("9p", "sanma"), "1p");
  assert.throws(() => doraFromIndicator("0m", "sanma"), /unavailable/);
});

test("sanma ukeire excludes removed tiles and rejects impossible observations", () => {
  const results = evaluateDiscards(hand, [], 0, "sanma");
  assert.ok(results.length);
  assert.ok(results.every(row => row.effectiveTiles.every(({ tile }) => !/^[2-8]m$/.test(tile))));
  assert.throws(() => evaluateDiscards(hand, ["0m"], 0, "sanma"), /unavailable/);
  assert.ok(evaluateDiscards(hand).some(row => row.effectiveTiles.some(({ tile }) => /^[2-8]m$/.test(tile))));
});

test("sanma uses three players and third hand for scheduled last round", () => {
  const base = { rules: "sanma", hand, round: "east_3", matchLength: "east", seat: "east", scores: { east: 35000, south: 35000, west: 35000 }, doraIndicators: ["1m"], remainingTiles: 20, publicStateConfidence: 1, opponents: [{ seat: "south" }, { seat: "west" }] };
  const state = parseGameState(base);
  assert.equal(isAllLastRound(state), true);
  assert.equal(isAllLastRound({ round: "east_3", matchLength: "east" }), false);
  assert.equal(isAllLastRound({ rules: "sanma", round: "south_3", matchLength: "south" }), true);
  assert.throws(() => isAllLastRound({ rules: "sanma", round: "west_4", matchLength: "east" }), /fourth hand/);
  assert.throws(() => parseGameState({ ...base, hand: ["2m", ...hand.slice(1)] }), /unavailable/);
  assert.throws(() => parseGameState({ ...base, opponents: [{ seat: "south" }, { seat: "north" }] }), /north seat/);
  assert.throws(() => generateLegalActions(state), /not implemented/);
});

test("sanma rejects impossible round, north seats and chi even at low confidence", () => {
  const base = { rules: "sanma", hand, seat: "east", opponents: [] };
  for (const invalid of [
    { round: "east_4" }, { seat: "north" }, { scores: { north: 0 } },
    { opponents: [{ seat: "north" }] }, { availableUiActions: ["chi"] },
    { opponents: [{ seat: "south", melds: [{ type: "chi", tiles: ["1p", "2p", "3p"] }] }] },
    { openMelds: 1, hand: hand.slice(3), melds: [{ type: "chi", tiles: ["1p", "2p", "3p"] }] },
  ]) assert.throws(() => parseGameState({ ...base, ...invalid }), /Sanma|sanma|Chi/);
});

test("direct four-player evaluation and scorer reject sanma rather than returning misleading estimates", async () => {
  const state = parseGameState({ rules: "sanma", hand });
  const candidate = evaluateDiscards(hand, [], 0, "sanma")[0]!;
  const { deterministicAdvice } = await import("../src/evaluation/advisor.js");
  const { evaluateRoundValue } = await import("../src/evaluation/value.js");
  const { scoreClosedWaits } = await import("../src/evaluation/closedWaitScorer.js");
  const { scoreOpenWinningTile } = await import("../src/evaluation/openTenpaiScore.js");
  const { buildStrategyHandPlan } = await import("../src/agent/decision.js");
  for (const invoke of [() => deterministicAdvice(state), () => evaluateRoundValue(candidate, state),
    () => scoreClosedWaits(state, "P", ["E"]), () => scoreOpenWinningTile(state.hand, "E", state, true),
    () => buildStrategyHandPlan(state)]) assert.throws(invoke, /Sanma evaluation is not implemented/);
});
