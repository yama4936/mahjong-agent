import assert from "node:assert/strict";
import test from "node:test";
import { decide } from "../src/agent/decision.js";
import { parseGameState } from "../src/game/state.js";

const state = parseGameState({
  hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"],
  draw: "6p",
  recognitionConfidence: 1,
});

test("advisor produces a recommendation but is never executable", async () => {
  const result = await decide(state, { mode: "advisor" });
  assert.equal(result.tile, "E");
  assert.equal(result.executable, false);
  assert.equal(result.safety.allowed, true);
});

test("auto mode refuses to act without Jev", async () => {
  const result = await decide(state, { mode: "auto" });
  assert.equal(result.executable, false);
  assert.ok(result.safety.reasons.includes("jev_required_for_auto_mode"));
});

test("low recognition confidence blocks action", async () => {
  const unsafe = parseGameState({ ...state, recognitionConfidence: 0.5 });
  const result = await decide(unsafe, { mode: "advisor" });
  assert.equal(result.safety.allowed, false);
});

test("auto requires a complete and internally consistent public state", async () => {
  const complete = parseGameState({
    ...state,
    round: "east_1",
    scores: { east: 25000, south: 25000, west: 25000, north: 25000 },
    doraIndicators: ["4s"],
    remainingTiles: 60,
    publicStateConfidence: 1,
    opponents: [
      { seat: "south", discards: [] },
      { seat: "west", discards: [] },
      { seat: "north", discards: [] },
    ],
  });
  const jev = { chooseDiscard: async (_state: unknown, candidates: any[]) => ({
    actionId: candidates[0].actionId,
    confidence: 1,
    probabilities: Object.fromEntries(candidates.map((candidate) => [candidate.actionId, candidate === candidates[0] ? 1 : 0])),
    model: "fake",
    promptVersion: "test",
    latencyMs: 1,
  }) } as any;
  const result = await decide(complete, { mode: "auto", jev });
  assert.deepEqual(result.safety.reasons, []);
  assert.equal(result.executable, true);
});

test("winning and riichi UI actions are selected ahead of a plain discard", async () => {
  const winning = parseGameState({
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "1p", "2p", "3p", "7s", "8s", "9s", "E"],
    draw: "E",
    availableUiActions: ["tsumo"],
  });
  assert.equal((await decide(winning, { mode: "advisor" })).selectedAction.action, "tsumo");

  const ready = parseGameState({ ...state, scores: { east: 25000 }, availableUiActions: ["riichi"] });
  const result = await decide(ready, { mode: "advisor" });
  assert.equal(result.selectedAction.action, "riichi");
  assert.equal(result.selectedActionId, "riichi_discard_E");
});

test("force-auto remains executable when normal safety checks are ambiguous", async () => {
  const unsafe = parseGameState({ ...state, recognitionConfidence: 0.5 });
  const result = await decide(unsafe, { mode: "force-auto" });
  assert.equal(result.safety.allowed, false);
  assert.equal(result.executable, true);
});

test("advisor recommends a non-worsening closed kan outside riichi", async () => {
  const closed = parseGameState({
    hand: ["1m", "2m", "3m", "1p", "2p", "3p", "1s", "2s", "3s", "E", "E", "E", "E"],
    draw: "5m",
    availableUiActions: ["kan"],
  });
  assert.equal((await decide(closed, { mode: "advisor" })).selectedAction.action, "ankan");
  const riichi = parseGameState({ ...closed, riichiDeclared: true });
  assert.notEqual((await decide(riichi, { mode: "advisor" })).selectedAction.action, "ankan");
});

test("reaction policy wins immediately and folds calls against riichi", async () => {
  const ron = parseGameState({
    phase: "reaction",
    seat: "south",
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "1p", "2p", "3p", "7s", "8s", "9s", "E"],
    pendingDiscard: { tile: "E", fromSeat: "east" },
    availableUiActions: ["ron", "pon", "pass"],
  });
  assert.equal((await decide(ron, { mode: "advisor" })).selectedAction.action, "ron");

  const threatened = parseGameState({
    phase: "reaction",
    seat: "south",
    hand: ["1m", "2m", "4m", "4m", "4m", "5p", "6p", "7p", "2s", "3s", "4s", "E", "E"],
    pendingDiscard: { tile: "3m", fromSeat: "east" },
    availableUiActions: ["chi", "pass"],
    opponents: [{ seat: "east", discards: [], riichi: true }],
  });
  assert.equal((await decide(threatened, { mode: "advisor" })).selectedAction.action, "pass");
});

test("reaction policy calls only when the call improves shanten", async () => {
  const callable = parseGameState({
    phase: "reaction",
    seat: "south",
    hand: ["1m", "2m", "3p", "9m", "4s", "5p", "P", "C", "3m", "4p", "4s", "5m", "1s"],
    pendingDiscard: { tile: "3m", fromSeat: "east" },
    availableUiActions: ["chi", "pass"],
  });
  assert.equal((await decide(callable, { mode: "advisor" })).selectedAction.action, "chi");
  const jev = { chooseReaction: async (_state: unknown, actions: any[]) => ({
    actionId: actions.find((action) => action.action === "pass").id,
    confidence: 0.88,
    probabilities: Object.fromEntries(actions.map((action) => [action.id, action.action === "pass" ? 0.88 : 0.12])),
    model: "fake", promptVersion: "mahjong-reaction-v1", latencyMs: 1,
  }) } as any;
  const judged = await decide(callable, { mode: "advisor", jev });
  assert.equal(judged.selectedAction.action, "pass");
  assert.equal(judged.source, "jev");
  assert.equal(judged.jev?.promptVersion, "mahjong-reaction-v1");
});
