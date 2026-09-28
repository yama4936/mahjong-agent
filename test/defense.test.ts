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

for (const suit of ["m", "p", "s"]) {
  test(`red and ordinary fives share genbutsu and suji in ${suit}`, () => {
    for (const discarded of [`0${suit}`, `5${suit}`]) {
      const state = parseGameState({ ...base, opponents: [{ seat: "west", discards: [discarded], riichi: true, openMelds: 0 }] });
      for (const candidate of [`0${suit}`, `5${suit}`]) {
        assert.deepEqual(evaluateTileDanger(candidate, state).byOpponent[0], { seat: "west", probability: 0, reasons: ["genbutsu"] });
      }
      const ordinary = parseGameState({ ...base, opponents: [{ seat: "west", discards: [`5${suit}`], riichi: true, openMelds: 0 }] });
      for (const rank of [2, 8]) {
        assert.deepEqual(evaluateTileDanger(`${rank}${suit}`, state), evaluateTileDanger(`${rank}${suit}`, ordinary));
        assert.ok(evaluateTileDanger(`${rank}${suit}`, state).byOpponent[0]!.reasons.includes("full_suji"));
      }
      assert.ok(!evaluateTileDanger(`4${suit}`, state).byOpponent[0]!.reasons.includes("genbutsu"));
      assert.deepEqual(state.opponents[0]!.discards, [discarded]);
    }
  });
}

test("red-five genbutsu is safe only against the player who discarded it", () => {
  const state = parseGameState({ ...base, opponents: [
    { seat: "west", discards: ["0p"], riichi: true, openMelds: 0 },
    { seat: "south", discards: ["1s"], riichi: true, openMelds: 0 },
  ] });
  const danger = evaluateTileDanger("5p", state);
  assert.equal(danger.byOpponent[0]!.probability, 0);
  assert.ok(danger.byOpponent[1]!.probability > 0);
  assert.equal(danger.combinedProbability, 1 - (1 - danger.byOpponent[1]!.probability));
});
