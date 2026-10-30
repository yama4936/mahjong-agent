import assert from "node:assert/strict";
import test from "node:test";
import { decide } from "../src/agent/decision.js";
import { deterministicAdvice } from "../src/evaluation/advisor.js";
import { parseGameState } from "../src/game/state.js";
import { evaluateRoundValue } from "../src/evaluation/value.js";

// Recognized state from the 2026-10-30 04:00:10 friend-match replay.
const live = parseGameState({
  round: "east_3", honba: 1, riichiSticks: 1, seat: "north",
  scores: { north: 18500, east: 27000, south: 25000, west: 28500 },
  hand: ["3m", "5m", "7m", "7m", "7m", "6p", "7p", "1s", "2s", "3s", "E", "E", "E"],
  draw: "5p", doraIndicators: ["3p"], ownDiscards: ["1p", "8s", "S", "6m", "1m"],
  remainingTiles: 46, turn: 5, phase: "self_turn", recognitionConfidence: 0.9379812139194453,
  availableUiActions: ["riichi", "tsumo", "kan", "kyuushu"],
  opponents: [
    { seat: "east", discards: ["P", "C", "8p", "P", "9p", "8m"], openMelds: 0 },
    { seat: "south", discards: ["F", "W", "3s", "7m", "S", "5s"], openMelds: 0 },
    { seat: "west", discards: ["1p", "1p", "S", "P", "1p", "4p"], openMelds: 0 },
  ],
});

test("known river furiten remains visible when closed-hand winning modes are unknown", async () => {
  const result = deterministicAdvice(live);
  const furiten = result.candidates.find(c => c.tile === "3m")!;
  assert.deepEqual(furiten.knownDiscardFuritenWaits, ["6m"]);
  assert.deepEqual(furiten.effectiveTiles.map(w => w.tile), ["5m", "6m"]);
  assert.ok(furiten.winProbability! > 0);
  const { knownDiscardFuritenWaits: _waits, ...withoutFuriten } = furiten;
  const unadjusted = evaluateRoundValue(withoutFuriten, live);
  assert.equal(furiten.winProbability, unadjusted.winProbability);
  assert.equal(result.tile, "3m");
  const decision = await decide(live, { mode: "force-auto" });
  assert.ok("tile" in decision.selectedAction && decision.selectedAction.tile === "E");
  assert.equal(decision.localRiichiWaitComparison?.candidates.find(c => c.tile === "3m")?.weightedWaitCopies, 1.5);
  assert.equal(decision.localRiichiWaitComparison?.temporaryOrRiichiPassFuriten, "unknown");
});

test("red fives normalize and missing river matches do not certify no furiten", () => {
  const redRiver = parseGameState({ ...live, ownDiscards: ["0m"] });
  assert.deepEqual(deterministicAdvice(redRiver).candidates.find(c => c.tile === "3m")!.knownDiscardFuritenWaits, ["5m"]);
  const noMatch = parseGameState({ ...live, ownDiscards: [] });
  assert.equal(deterministicAdvice(noMatch).candidates.find(c => c.tile === "3m")!.knownDiscardFuritenWaits, undefined);
});

test("an exhausted discarded wait still makes every wait furiten", () => {
  const exhausted = parseGameState({ ...live, opponents: live.opponents.map((op, index) => index === 0
    ? { ...op, discards: [...op.discards, "6m", "6m", "6m"] } : op) });
  const candidate = deterministicAdvice(exhausted).candidates.find(c => c.tile === "3m")!;
  assert.deepEqual(candidate.knownDiscardFuritenWaits, ["6m"]);
  assert.deepEqual(candidate.effectiveTiles.map(w => w.tile), ["5m"]);
  assert.ok(candidate.winProbability! > 0);
});

test("a furiten riichi remains legal and is explicitly identified", async () => {
  const allFuriten = parseGameState({ ...live, ownDiscards: ["3m", "4m", "6m"] });
  const result = await decide(allFuriten, { mode: "force-auto" });
  assert.equal(result.selectedAction.action, "riichi");
  assert.ok(result.riichiAssessment?.reasons.includes("known_discard_furiten_ron_unavailable"));
});
