import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { assessReactionCalls } from "../src/agent/decision.js";
import { generateReactionActions } from "../src/game/actions.js";
import { parseGameState, type GameState } from "../src/game/state.js";

async function nativeState() {
  const fixture = JSON.parse(await readFile("test/fixtures/open-call-no-yaku-20261022.json", "utf8"));
  return parseGameState(fixture.state);
}
function calls(state: GameState) { return assessReactionCalls(state, generateReactionActions(state)); }
const reason = "post_call_tenpai_has_no_ordinary_yaku";

test("native CPU1p pon does not certify yakuless structural tenpai as a faster legal win", async () => {
  const assessment = calls(await nativeState()).find(item => item.actionId === "pon_1p")!;
  assert.equal(assessment.currentShanten, 1);
  assert.equal(assessment.resultingShanten, 0);
  assert.equal(assessment.approved, false);
  assert.ok(assessment.reasons.includes(reason));
  assert.ok(assessment.ordinaryTenpai?.length);
  assert.ok(assessment.ordinaryTenpai!.every(item => item.report?.waits.length
    && item.report.waits.every(wait => !wait.ronYaku.length && !wait.tsumoYaku.length)));
});

test("native later789p alternative retains chanta9s; do not repeat the refuted all-waits-yakuless claim", async () => {
  const state = await nativeState();
  const index = state.hand.indexOf("6p");
  state.hand[index] = "9p";
  const assessment = calls(state).find(item => item.actionId === "pon_1p")!;
  assert.equal(assessment.approved, true);
  assert.ok(!assessment.reasons.includes(reason));
  assert.ok(assessment.ordinaryTenpai?.some(item => item.report?.waits.some(wait => wait.tile === "9s" && wait.ronYaku.includes("chanta"))));
});

test("a yakuless first structural discard cannot hide another chanta tenpai alternative", () => {
  const state = parseGameState({ phase: "reaction", round: "east_1", seat: "south", turn: 7,
    hand: ["9m","9m","1m","2m","3m","1p","2p","3p","4p","7s","8s","C","C"],
    pendingDiscard: { tile: "9m", fromSeat: "north" }, availableUiActions: ["pon", "pass"] });
  const assessment = calls(state).find(item => item.actionId === "pon_9m")!;
  assert.equal(assessment.currentShanten, 1);
  assert.equal(assessment.resultingShanten, 0);
  assert.ok(assessment.ordinaryTenpai?.find(item => item.discard === "1p")?.report?.waits
    .every(wait => !wait.ronYaku.length && !wait.tsumoYaku.length));
  assert.ok(assessment.ordinaryTenpai?.find(item => item.discard === "4p")?.report?.waits
    .some(wait => wait.tile === "9s" && wait.ronYaku.includes("chanta")));
  assert.equal(assessment.approved, true);
});

test("late structural tenpai and last-tile situational context are not rejected by an ordinary-yaku-only guard", async () => {
  for (const change of [{ turn: 12, scores: { south: 24000, east: 26000, west: 25000, north: 25000 } }, { remainingTiles: 3 }]) {
    const assessment = calls({ ...await nativeState(), ...change }).find(item => item.actionId === "pon_1p")!;
    assert.ok(!assessment.reasons.includes(reason));
    assert.equal(assessment.approved, true);
  }
  const leading = calls({ ...await nativeState(), turn: 12 }).find(item => item.actionId === "pon_1p")!;
  assert.equal(leading.approved, false);
  assert.ok(leading.reasons.includes("hand_plan_disallows_calls"));
  assert.ok(!leading.reasons.includes(reason));
});

test("unknown round and replacement draw remain unknown to the new guard", async () => {
  const state = await nativeState();
  const unknown = calls({ ...state, round: "unknown" }).find(item => item.actionId === "pon_1p")!;
  assert.ok(!unknown.reasons.includes(reason));
  assert.ok(unknown.ordinaryTenpai?.every(item => !item.report));
  const kan = parseGameState({ ...state, hand: state.hand.map(tile => tile === "4p" ? "1p" : tile),
    availableUiActions: ["kan", "pass"] });
  const assessment = calls(kan).find(item => item.actionId === "minkan_1p")!;
  assert.ok(!assessment.reasons.includes(reason));
  assert.equal(assessment.ordinaryTenpai, undefined);
});

test("native sample34 winning C wait survives the guard in late and middle play", async () => {
  const fixture = JSON.parse(await readFile("test/fixtures/open-call-yakuhai-wait-20261022.json", "utf8"));
  const native = parseGameState(fixture.state);
  for (const turn of [native.turn, 7]) {
    const assessment = calls({ ...native, turn }).find(item => item.actionId === "pon_8s")!;
    const report = assessment.ordinaryTenpai?.find(item => item.discard === "2p")?.report;
    assert.ok(report);
    assert.ok(report.waits.find(wait => wait.tile === "C")!.ronYaku.includes("yakuhai:C"));
    assert.deepEqual(report.waits.find(wait => wait.tile === "9p")!.ronYaku, []);
    assert.equal(assessment.approved, true);
    assert.ok(!assessment.reasons.includes(reason));
  }
  const unknown = calls({ ...native, turn: 7, melds: [] }).find(item => item.actionId === "pon_8s")!;
  assert.ok(unknown.ordinaryTenpai?.every(item => !item.report));
  assert.ok(!unknown.reasons.includes(reason));
});

test("a non-tanyao ordinary yaku prevents the old sole-tanyao guard from rejecting chinitsu tenpai", async () => {
  const fixture = JSON.parse(await readFile("test/fixtures/open-call-flush-alternative-20261022.json", "utf8"));
  const state = parseGameState(fixture.state);
  const assessment = calls(state).find(item => item.actionId === "chi_3m_2m_4m")!;
  assert.equal(assessment.currentShanten, 1);
  assert.equal(assessment.resultingShanten, 0);
  assert.deepEqual(assessment.candidateYaku, ["tanyao"]);
  assert.equal(fixture.tanyaoDiscard.shanten, 1);
  assert.ok(assessment.ordinaryTenpai?.some(item => item.discard !== "3m" && item.report?.waits
    .some(wait => wait.ronYaku.includes("chinitsu"))));
  assert.ok(!assessment.reasons.includes("no_strict_tanyao_shanten_improvement"));
  assert.equal(assessment.approved, true);
});

test("ordinary-yaku evidence cannot approve a kuikae-only structural gain", () => {
  const state = parseGameState({ phase: "reaction", round: "east_1", seat: "south", turn: 7,
    hand: ["5m","5m","5m","2p","3p","4p","6p","7p","8p","7s","8s","2s","2s"],
    pendingDiscard: { tile: "5m", fromSeat: "north" }, availableUiActions: ["pon", "pass"] });
  const assessment = calls(state).find(item => item.actionId === "pon_5m")!;
  // Re-discarding the called face could reach tanyao tenpai, but the same
  // triplet already exists in the pre-call hand: there was no speed gain.
  assert.ok(assessment.ordinaryTenpai?.find(item => item.discard === "5m")?.report?.waits
    .some(wait => wait.ronYaku.includes("tanyao")));
  assert.equal(assessment.currentShanten, 0);
  assert.equal(assessment.resultingShanten, 0);
  assert.equal(assessment.approved, false);
  assert.ok(assessment.reasons.includes("no_strict_shanten_improvement"));
});
