import assert from "node:assert/strict";
import test from "node:test";
import { evaluateTileDanger } from "../src/evaluation/defense.js";
import { parseGameState } from "../src/game/state.js";

const base = {
  hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"],
  draw: "6p",
  opponents: [{ seat: "west", discards: ["5m"], riichi: true, openMelds: 0 }],
};

test("genbutsu is zero danger against that opponent", () => {
  const danger = evaluateTileDanger("5m", parseGameState(base));
  assert.equal(danger.byOpponent[0]!.probability, 0);
  assert.deepEqual(danger.byOpponent[0]!.reasons, ["genbutsu"]);
});

test("suji is safer than an unrelated tile against riichi", () => {
  const state = parseGameState(base);
  assert.ok(evaluateTileDanger("2m", state).combinedProbability < evaluateTileDanger("3m", state).combinedProbability);
});
