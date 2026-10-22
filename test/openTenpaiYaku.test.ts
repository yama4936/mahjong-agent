import assert from "node:assert/strict";
import test from "node:test";
import { parseGameState, type GameState } from "../src/game/state.js";
import { parseGameTile } from "../src/game/tiles.js";
import { evaluateDiscards } from "../src/game/ukeire.js";
import { openTenpaiYaku } from "../src/evaluation/openTenpaiYaku.js";

function report(concealed: string[], melds: GameState["melds"], winner: string, extra: Partial<GameState> = {}) {
  const state = parseGameState({ round: "east_2", seat: "south", hand: concealed, draw: "N", melds,
    openMelds: melds.length, ...extra });
  const candidate = evaluateDiscards([...state.hand, state.draw!], [], state.openMelds).find(item => item.tile === "N")!;
  const result = openTenpaiYaku(candidate, state);
  assert.ok(result);
  const wait = result.waits.find(wait => wait.tile === winner);
  assert.ok(wait);
  return { result, wait, state, candidate };
}
const chi = (tiles: string[]): GameState["melds"][number] => ({ type: "chi", tiles: tiles.map(parseGameTile) });
const pon = (tiles: string[]): GameState["melds"][number] => ({ type: "pon", tiles: tiles.map(parseGameTile) });

test("native9s choice loses chanta but preserves sanshoku1p; both4p sides have no ordinary yaku", () => {
  const common = ["2p", "3p", "1s", "2s", "3s", "F", "F"];
  const original = report([...common, "7s", "8s", "9s"], [chi(["1m", "2m", "3m"])], "1p");
  const after = report([...common, "6s", "7s", "8s"], [chi(["1m", "2m", "3m"])], "1p");
  assert.ok(original.wait.ronYaku.includes("chanta"));
  assert.ok(original.wait.ronYaku.includes("sanshoku_doujun"));
  assert.deepEqual(after.wait.ronYaku, ["sanshoku_doujun"]);
  for (const { result } of [original, after]) {
    assert.deepEqual(result.waits.find(wait => wait.tile === "4p")!.ronYaku, []);
    assert.deepEqual(result.waits.find(wait => wait.tile === "4p")!.tsumoYaku, []);
    assert.equal(result.ronUkeire, 4);
    assert.equal(result.tsumoUkeire, 4);
  }
});

test("ordinary open yaku families survive complete-shape analysis", () => {
  const cases: Array<[string, string[], GameState["melds"], string]> = [
    ["yakuhai:F", ["1m","2m","3m","4p","5p","6p","7s","8s","9s","E"], [pon(["F","F","F"])], "E"],
    ["tanyao", ["2p","3p","4p","4s","5s","6s","6s","7s","8s","2p"], [chi(["2m","3m","4m"])], "2p"],
    ["junchan", ["1p","2p","3p","7s","8s","9s","9p","9p","9p","1s"], [chi(["1m","2m","3m"])], "1s"],
    ["sanshoku_doukou", ["2p","2p","2p","2s","2s","2s","7m","8m","9m","F"], [pon(["2m","2m","2m"])], "F"],
    ["ittsuu", ["4m","5m","6m","7m","8m","9m","4p","5p","6p","F"], [chi(["1m","2m","3m"])], "F"],
    ["toitoi", ["4p","4p","4p","6s","6s","6s","8m","8m","8m","F"], [pon(["2m","2m","2m"])], "F"],
    ["sanankou", ["2p","2p","2p","4s","4s","4s","6m","6m","6m","F"], [chi(["1m","2m","3m"])], "F"],
    ["ryuuiisou", ["2s","3s","4s","6s","6s","6s","8s","8s","8s","F"], [chi(["2s","3s","4s"])], "F"],
    ["honitsu", ["4m","5m","6m","7m","8m","9m","N","N","N","F"], [chi(["1m","2m","3m"])], "F"],
    ["chinitsu", ["3m","4m","5m","6m","7m","8m","9m","9m","9m","1m"], [chi(["2m","3m","4m"])], "1m"],
    ["shousangen", ["F","F","F","1m","2m","3m","7p","8p","9p","C"], [pon(["P","P","P"])], "C"],
  ];
  for (const [yaku, concealed, melds, winner] of cases) {
    const { wait } = report(concealed, melds, winner);
    assert.ok(wait.ronYaku.includes(yaku), yaku);
    assert.ok(wait.tsumoYaku.includes(yaku), yaku);
  }
});

test("ron-completed third triplet does not invent sanankou, while tsumo can provide it", () => {
  const { wait } = report(["2p","2p","2p","4s","4s","4s","6m","6m","F","F"], [chi(["1m","2m","3m"])], "6m");
  assert.deepEqual(wait.ronYaku, []);
  assert.deepEqual(wait.tsumoYaku, ["sanankou"]);
});

test("dora-only and value-honor pairs do not create yaku", () => {
  const { wait } = report(["2p","3p","4p","4s","5s","6s","7m","8m","9m","F"], [chi(["1m","2m","3m"])], "F", { doraIndicators: ["P", "P"] });
  assert.deepEqual(wait.ronYaku, []);
  assert.deepEqual(wait.tsumoYaku, []);
});


test("incomplete or malformed meld/wind evidence stays unknown", () => {
  const { state, candidate } = report(["2p","3p","1s","2s","3s","7s","8s","9s","F","F"], [chi(["1m","2m","3m"])], "1p");
  for (const changed of [{ ...state, round: "unknown" }, { ...state, melds: [] },
    { ...state, melds: [pon(["1m","2m","3m"])] },
    { ...state, melds: [chi([])] }, { ...state, melds: [pon(["2m","2m"])] }]) {
    assert.equal(openTenpaiYaku(candidate, changed), undefined);
  }
});

test("discarding either structural wait causes furiten even on a no-yaku wait", () => {
  const { result } = report(["2p","3p","1s","2s","3s","7s","8s","9s","F","F"], [chi(["1m","2m","3m"])], "1p", { ownDiscards: ["4p"] });
  assert.equal(result.knownDiscardFuriten, true);
  assert.equal(result.ronUkeire, 0);
  assert.equal(result.tsumoUkeire, 4);
});

test("CPU immediate no-yaku waits and later chanta are distinguished", () => {
  const common = ["1m","2m","3m","7s","8s","C","C"];
  const immediate = report([...common,"6p","7p","8p"], [pon(["1p","1p","1p"])], "9s");
  for (const wait of immediate.result.waits) {
    assert.deepEqual(wait.ronYaku, []);
    assert.deepEqual(wait.tsumoYaku, []);
  }
  const later = report([...common,"7p","8p","9p"], [pon(["1p","1p","1p"])], "9s");
  assert.deepEqual(later.wait.ronYaku, ["chanta"]);
  assert.deepEqual(later.result.waits.find(wait => wait.tile === "6s")!.ronYaku, []);
});

test("three known kans retain their ordinary kan yaku and concealed-kan distinction", () => {
  const kan = (type: "ankan" | "minkan" | "kakan", tile: string): GameState["melds"][number] =>
    ({ type, tiles: [tile,tile,tile,tile].map(parseGameTile) });
  const { wait } = report(["1m","2m","F","F"],
    [kan("ankan","4p"), kan("minkan","6s"), kan("kakan","8m")], "3m");
  assert.deepEqual(wait.ronYaku, ["sankantsu"]);
  assert.deepEqual(wait.tsumoYaku, ["sankantsu"]);
});

test("honroutou is a positive ordinary-yaku path", () => {
  const { wait } = report(["9p","9p","9p","1s","1s","1s","N","N","N","F"],
    [pon(["1m","1m","1m"])], "F");
  assert.ok(wait.ronYaku.includes("honroutou"));
});

test("physically impossible fifth-copy evidence stays unknown instead of throwing", () => {
  const { state, candidate } = report(["2p","3p","1s","2s","3s","7s","8s","9s","F","F"],
    [chi(["1m","2m","3m"])], "1p");
  const broken = { ...state, melds: [pon(["F","F","F"])] };
  assert.equal(openTenpaiYaku(candidate, broken), undefined);
});
