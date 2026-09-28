import assert from "node:assert/strict";
import test from "node:test";
import { knownTiles, knownTilesOutsideHand, parseGameState, parsePublicGameState } from "../src/game/state.js";

test("verified river-tail pending tile is counted once while genuine fifth copies still fail", () => {
  const input = {
    phase: "reaction", seat: "east",
    hand: ["5m", "6m", "7m", "8m", "9m", "2p", "3p", "4p", "7s", "7s", "8s", "8s", "9s"],
    opponents: [{ seat: "south", discards: ["7s", "4s", "7s"] }],
    pendingDiscard: { tile: "7s", fromSeat: "south", inRiver: true },
  };
  const state = parseGameState(input);
  assert.equal(knownTiles(state).filter((tile) => tile === "7s").length, 4);
  assert.equal(knownTilesOutsideHand(state).filter((tile) => tile === "7s").length, 2);
  assert.throws(() => parseGameState({ ...input, pendingDiscard: { ...input.pendingDiscard, inRiver: false } }), /More than four/);
  assert.throws(() => parseGameState({ ...input, opponents: [{ seat: "south", discards: ["7s", "7s", "7s"] }] }), /More than four/);
  assert.throws(() => parseGameState({ ...input, pendingDiscard: { ...input.pendingDiscard, fromSeat: "west" } }), /river tail/);
  assert.throws(() => parseGameState({ ...input, opponents: [{ seat: "south", discards: ["7s", "4s"] }] }), /river tail/);
});

test("public state parser enforces the same river-tail evidence without guessing", () => {
  const input = { phase: "reaction", opponents: [{ seat: "south", discards: ["7s", "7s", "7s", "7s"] }],
    pendingDiscard: { tile: "7s", fromSeat: "south", inRiver: true } };
  assert.doesNotThrow(() => parsePublicGameState(input));
  assert.throws(() => parsePublicGameState({ ...input, pendingDiscard: { tile: "7s", fromSeat: "south" } }), /More than four/);
});
