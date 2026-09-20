import assert from "node:assert/strict";
import test from "node:test";
import { calculateShanten } from "../src/game/shanten.js";
import { evaluateDiscards } from "../src/game/ukeire.js";
import { parseGameState, parsePublicGameState } from "../src/game/state.js";

test("complete standard hand is -1 shanten", () => {
  assert.equal(calculateShanten(["1m", "2m", "3m", "4m", "5m", "6m", "1p", "2p", "3p", "7s", "8s", "9s", "E", "E"]).shanten, -1);
});

test("complete seven pairs is -1 shanten", () => {
  const result = calculateShanten(["1m", "1m", "3m", "3m", "5p", "5p", "7p", "7p", "2s", "2s", "9s", "9s", "E", "E"]);
  assert.equal(result.chiitoitsu, -1);
  assert.equal(result.shanten, -1);
});

test("complete kokushi is -1 shanten", () => {
  const result = calculateShanten(["1m", "9m", "1p", "9p", "1s", "9s", "E", "S", "W", "N", "P", "F", "C", "C"]);
  assert.equal(result.kokushi, -1);
  assert.equal(result.shanten, -1);
});

test("discard evaluation returns legal unique tiles and ukeire", () => {
  const hand = ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "6p", "7s", "8s", "9s", "E"];
  const results = evaluateDiscards(hand);
  assert.equal(results.length, new Set(hand).size);
  assert.ok(results.every((result) => hand.includes(result.tile)));
  assert.ok(results[0]!.ukeire >= 0);
});

test("red fives normalize to ordinary five counts", () => {
  assert.throws(() => calculateShanten(["0m", "5m", "5mr", "5m", "5m", "1p", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "9p"]), /More than four/);
});

test("state parser accepts the documented snake_case JSON contract", () => {
  const state = parseGameState({
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"],
    draw: "6p",
    riichi_sticks: 2,
    dora_indicators: ["4s"],
    recognition_confidence: 0.99,
  });
  assert.equal(state.riichiSticks, 2);
  assert.deepEqual(state.doraIndicators, ["4s"]);
  assert.equal(state.recognitionConfidence, 0.99);
});

test("state parser rejects more than four physically visible copies", () => {
  assert.throws(() => parseGameState({
    hand: ["1m", "1m", "1m", "1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m", "E"],
    draw: "S",
    dora_indicators: ["1m"],
  }), /More than four copies of 1m/);
});

test("state derives fixed meld count and tracks structured visible tiles", () => {
  const state = parseGameState({
    hand: ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "9s", "E"],
    draw: "E",
    melds: [{ type: "pon", tiles: ["P", "P", "P"], fromSeat: "west" }],
    own_discards: ["1s", "2s"],
    remaining_tiles: 42,
  });
  assert.equal(state.openMelds, 1);
  assert.equal(state.melds.length, 1);
  assert.deepEqual(state.ownDiscards, ["1s", "2s"]);
  assert.equal(state.remainingTiles, 42);
});

test("public state parser does not invent concealed tiles", () => {
  const state = parsePublicGameState({
    round: "east_2",
    own_discards: ["5m", "5m", "5m", "5m"],
    public_state_confidence: 0.5,
  });
  assert.equal(state.round, "east_2");
  assert.deepEqual(state.ownDiscards, ["5m", "5m", "5m", "5m"]);
  assert.equal(state.publicStateConfidence, 0.5);
});

test("high public confidence cannot be supplied with incomplete evidence", () => {
  assert.throws(() => parseGameState({
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"],
    draw: "6p",
    publicStateConfidence: 0.98,
  }), /requires complete evidence/);
});

test("public state parser enforces visible four-copy consistency", () => {
  assert.throws(() => parsePublicGameState({
    ownDiscards: ["5m", "5m", "5m", "5m"],
    doraIndicators: ["5m"],
  }), /More than four copies of 5m/);
});
