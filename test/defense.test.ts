import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { evaluateTileDanger } from "../src/evaluation/defense.js";
import { parseGameState, type GameState } from "../src/game/state.js";

const base = {
  hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"],
  draw: "6p",
  opponents: [{ seat: "west", discards: ["5m"], riichi: true, openMelds: 0 }],
};

test("native four-pon opponent cannot tanki-ron a tile with every copy in our hand", async () => {
  const fixture = JSON.parse(await readFile("test/fixtures/four-meld-tanki-copies-20261023.json", "utf8"));
  const state = parseGameState(fixture.state);
  const danger = evaluateTileDanger("8p", state);
  assert.equal(danger.byOpponent.find(item => item.seat === "east")!.probability, 0);
  assert.ok(danger.byOpponent.filter(item => item.seat !== "east").every(item => item.probability > 0));
  assert.ok(danger.combinedProbability > 0);
});

const fourSets: NonNullable<GameState["opponents"][number]["melds"]> = [
  { type: "pon", tiles: ["E", "E", "E"] },
  { type: "pon", tiles: ["S", "S", "S"] },
  { type: "pon", tiles: ["W", "W", "W"] },
  { type: "pon", tiles: ["N", "N", "N"] },
];

function tankiState(opponent: Partial<GameState["opponents"][number]> = {}, hand?: string[], doraIndicators: string[] = []) {
  return parseGameState({
    hand: hand ?? ["8p", "8p", "8p", "8p", "1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m"],
    draw: "6p", doraIndicators,
    opponents: [{ seat: "west", discards: [], openMelds: 4, melds: fourSets, ...opponent }],
  });
}

test("four-set copy exhaustion covers mixed sets, kans, red fives and public copies", () => {
  for (const type of ["minkan", "ankan", "kakan"] as const) {
    const melds: typeof fourSets = [{ type, tiles: ["E", "E", "E", "E"] }, ...fourSets.slice(1)];
    assert.equal(evaluateTileDanger("8p", tankiState({ melds })).byOpponent[0]!.probability, 0);
  }
  const mixed: typeof fourSets = [{ type: "chi", tiles: ["2m", "3m", "4m"] }, ...fourSets.slice(1)];
  for (const openMeldsObserved of [true, false, undefined]) {
    assert.deepEqual(evaluateTileDanger("8p", tankiState({ melds: mixed, openMeldsObserved })).byOpponent[0]!.reasons,
      ["four_sets_tanki_all_copies_visible"]);
  }
  const red = tankiState().hand.map(tile => tile === "8p" ? "5p" : tile);
  red[0] = "0p";
  for (const tile of ["0p", "5p"]) {
    assert.equal(evaluateTileDanger(tile, tankiState({}, red)).byOpponent[0]!.probability, 0);
  }
  const threeInHand = [...tankiState().hand];
  threeInHand[0] = "2p";
  assert.equal(evaluateTileDanger("8p", tankiState({}, threeInHand, ["8p"])).byOpponent[0]!.probability, 0);
  assert.ok(evaluateTileDanger("8p", tankiState({}, threeInHand)).byOpponent[0]!.probability > 0);
});

test("suited copy exhaustion does not prove safety with three sets or incomplete or malformed evidence", () => {
  const cases: Partial<GameState["opponents"][number]>[] = [
    { openMelds: 3, melds: fourSets.slice(0, 3) },
    { melds: undefined },
    { melds: fourSets.slice(0, 3), openMeldsObserved: false },
    { melds: [{ type: "pon", tiles: ["E", "S", "N"] }, ...fourSets.slice(1)] },
    { melds: [{ type: "chi", tiles: ["9m", "1p", "2p"] }, ...fourSets.slice(1)] },
    { melds: [{ type: "ankan", tiles: ["E", "E", "E"] }, ...fourSets.slice(1)] },
  ];
  for (const opponent of cases) {
    const danger = evaluateTileDanger("8p", tankiState(opponent));
    assert.ok(danger.byOpponent[0]!.probability > 0, JSON.stringify(opponent));
    assert.ok(!danger.byOpponent[0]!.reasons.includes("four_sets_tanki_all_copies_visible"));
  }
});

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
