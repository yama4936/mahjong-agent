import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { scoreOpenTenpai, scoreOpenWinningTile } from "../src/evaluation/openTenpaiScore.js";
import { deterministicAdvice } from "../src/evaluation/advisor.js";
import { evaluateRoundValue } from "../src/evaluation/value.js";
import { buildJevRequest } from "../src/jev/client.js";
import { knownTilesOutsideHand, parseGameState, type GameState } from "../src/game/state.js";
import { parseGameTile, type GameTile } from "../src/game/tiles.js";
import { evaluateDiscards } from "../src/game/ukeire.js";

const meld = (type: GameState["melds"][number]["type"], tiles: string[]) => ({ type, tiles: tiles.map(parseGameTile) });
function state(hand: string[], melds: GameState["melds"], extra: Partial<GameState> = {}) {
  return parseGameState({ round: "east_2", seat: "south", hand, draw: "N", melds, openMelds: melds.length,
    remainingTiles: 40, ...extra });
}
function candidate(s: GameState, tile: string) {
  return evaluateDiscards([...s.hand, ...(s.draw ? [s.draw] : [])], knownTilesOutsideHand(s), s.openMelds)
    .find(c => c.tile === tile)!;
}
const simple = ["2p","3p","4p","4s","5s","6s","6s","7s","2p","2p"];

test("native sanshoku/chanta waits replace equal heuristic values without inventing a safer discard", async () => {
  const fixture = JSON.parse(await readFile("test/fixtures/open-tenpai-value-20261022.json", "utf8"));
  const s = parseGameState(fixture.state);
  const values = deterministicAdvice(s).candidates;
  for (const [discard, points] of [["9s",1500],["6s",2900]] as const) {
    const c = values.find(c => c.tile === discard)!;
    assert.equal(c.estimatedValue, points);
    assert.equal(c.ukeire, 7); // Shape-tenpai and draw-payment inputs stay structural.
    assert.equal(c.openTenpaiScore?.winningUkeire, 4);
    assert.equal(c.openTenpaiScore?.waits.find(w => w.tile === "4p")?.ron, undefined);
    assert.equal(c.openTenpaiScore?.waits.find(w => w.tile === "1p")?.ron?.total, points);
    assert.equal(c.openTenpaiScoreApplied, true);
    const before = fixture.before.find((c: { tile: string }) => c.tile === discard);
    assert.equal(c.danger, before.danger);
    assert.equal(c.tenpaiProbability, before.tenpaiProbability);
    assert.ok(c.winProbability! < before.winProbability);
  }
  // Different danger can still justify9s; this correction does not force6s.
  assert.equal(values.find(c => c.tile === "9s")!.danger! < values.find(c => c.tile === "6s")!.danger!, true);
});

test("open pinfu-form ron stays30fu, double wind triplet han and pair fu are counted separately", () => {
  const s = state(simple, [meld("chi", ["2m","3m","4m"])]);
  assert.equal(scoreOpenWinningTile(s.hand, "8s", s, false)?.fu, 30);
  assert.equal(scoreOpenWinningTile(s.hand, "8s", s, false)?.total, 1000);
  const doubles = state(["1m","2m","3m","4p","5p","6p","7s","8s","9s","P"],
    [meld("pon", ["E","E","E"])], { seat: "east" });
  assert.equal(scoreOpenWinningTile(doubles.hand, "P", doubles, false)?.han, 2);
  const pair = state(["1m","2m","3m","4p","5p","6p","7s","8s","9s","E"],
    [meld("pon", ["P","P","P"])], { seat: "east" });
  assert.equal(scoreOpenWinningTile(pair.hand, "E", pair, false)?.fu, 30);
  assert.equal(scoreOpenWinningTile(pair.hand, "E", pair, true)?.fu, 40);
});

test("winning-tile assignments preserve sanankou and choose the strongest fu decomposition", () => {
  const sanankou = state(["2p","2p","2p","4s","4s","4s","6m","6m","F","F"],
    [meld("chi", ["1m","2m","3m"])]);
  assert.equal(scoreOpenWinningTile(sanankou.hand, "6m", sanankou, false), undefined);
  assert.equal(scoreOpenWinningTile(sanankou.hand, "6m", sanankou, true)?.han, 2);
  const ambiguous = state(["3p","4p","5p","6m","7m","8m","2s","2s","2s","5p"],
    [meld("pon", ["P","P","P"])]);
  assert.equal(scoreOpenWinningTile(ambiguous.hand, "5p", ambiguous, false)?.fu, 30);
  assert.equal(scoreOpenWinningTile(ambiguous.hand, "5p", ambiguous, true)?.fu, 40);
});

test("dora-only never scores; winning dora, repeated indicators and red tiles do", () => {
  const noYaku = state(["2p","3p","4p","4s","5s","6s","7m","8m","9m","F"],
    [meld("chi", ["1m","2m","3m"])], { doraIndicators: ["P","P"] });
  assert.equal(scoreOpenWinningTile(noYaku.hand, "F", noYaku, false), undefined);
  const s = state(["3p","4p","5p","6m","7m","8m","2s","2s","2s","5p"],
    [meld("pon", ["P","P","P"])], { doraIndicators: ["4p","4p"] });
  assert.equal(scoreOpenWinningTile(s.hand, "5p", s, false)?.han, 7);
  assert.equal(scoreOpenWinningTile(s.hand, "5p", s, false)?.total, 12000);
  assert.equal(scoreOpenWinningTile(s.hand, "0p", s, false)?.han, 8);
  assert.equal(scoreOpenWinningTile(s.hand, "0p", s, false)?.total, 16000);
});

test("standard red-five variants use unseen copy counts and preserve retained red discard value", () => {
  const s = state(["2m","3m","4m","2p","3p","4p","6s","7s","0p","5p"],
    [meld("pon", ["P","P","P"])], { draw: "8s" });
  const redDiscard = evaluateRoundValue(candidate(s,"0p"), s);
  const normalDiscard = evaluateRoundValue(candidate(s,"5p"), s);
  assert.equal(redDiscard.estimatedValue, 1000); // P pon excludes tanyao.
  assert.equal(normalDiscard.estimatedValue, 2000);
  assert.equal(normalDiscard.openTenpaiScore?.waits.find(w => w.tile === "0p")?.remaining, 0);
  assert.equal(normalDiscard.openTenpaiScore?.waits.find(w => w.tile === "5p")?.remaining, 2);
});

test("yakuman overrides ordinary yaku/dora and multiple yakuman retain standard multipliers", () => {
  const allHonors = state(["E","E","E","S","S","S","C","C","C","N"],
    [meld("pon", ["P","P","P"])], { doraIndicators: ["F"] });
  assert.equal(scoreOpenWinningTile(allHonors.hand, "N", allHonors, false)?.total, 32000);
  assert.equal(scoreOpenWinningTile(allHonors.hand, "N", allHonors, false)?.doraHan, 0);
  const winds = state(["S","S","S","W","W","W","N","N","N","P"],
    [meld("pon", ["E","E","E"])], { draw: "C" });
  assert.equal(scoreOpenWinningTile(winds.hand, "P", winds, false)?.yakuman, 3);
  assert.equal(scoreOpenWinningTile(winds.hand, "P", winds, false)?.total, 96000);
});

test("ordinary-yakuless tenpai has zero ordinary win estimate while shape-tenpai payment value remains", () => {
  const s = state(["1m","2m","3m","6p","7p","8p","7s","8s","C","C"],
    [meld("pon", ["1p","1p","1p"])]);
  const c = candidate(s,"N");
  const value = evaluateRoundValue(c,s);
  assert.equal(value.shanten,0);
  assert.equal(value.estimatedValue,0);
  assert.equal(value.winProbability,0);
  assert.ok(value.tenpaiProbability! > 0);
  const last = evaluateRoundValue(c,{ ...s, remainingTiles:3 });
  assert.equal(last.openTenpaiScoreApplied,false);
  assert.ok(last.estimatedValue! > 0);
  assert.ok(last.winProbability! > 0);
});

test("unknown/malformed/physically impossible data falls back without certifying zero value", () => {
  const s = state(simple,[meld("chi",["2m","3m","4m"])]);
  const c = candidate(s,"N");
  for(const changed of [{...s,round:"unknown"},{...s,melds:[]},
    {...s,melds:[meld("pon",["2m","3m","4m"])]},
    {...s,ownDiscards:["0p","0p"] as GameTile[]}]) {
    assert.equal(scoreOpenTenpai(c,changed),undefined);
    assert.ok(evaluateRoundValue(c,changed).estimatedValue! > 0);
  }
});

test("Jev receives compact ordinary scoring waits and preserves the reported scoring scope", async () => {
  const fixture = JSON.parse(await readFile("test/fixtures/open-tenpai-value-20261022.json", "utf8"));
  const s = parseGameState(fixture.state);
  const candidates = deterministicAdvice(s).candidates.filter(c=>["9s","6s"].includes(c.tile));
  for (const profile of ["legacy-v1","balanced-v2","hierarchical-v3"] as const) {
    const request = buildJevRequest(s,candidates,"offline-only",profile);
    const text = JSON.stringify(request);
    assert.ok(text.includes("ordinary_open_waits"));
    assert.ok(text.includes('"ron_scoring_points":2900'));
    assert.ok(text.includes('"ron_scoring_points":null'));
    assert.ok(text.includes('"winning_tiles"'));
  }
});

test("independent mahjong2 oracle covers ordinary points, yakuman, assignments and kan fu", async () => {
  const fixture = JSON.parse(await readFile("test/fixtures/open-tenpai-score-oracle-20261022.json", "utf8"));
  for (const entry of fixture.cases) {
    const s = parseGameState({ ...entry.state, hand:entry.concealed, phase:"reaction",
      pendingDiscard:{ tile:entry.winner, fromSeat:entry.state.seat === "east" ? "south" : "east" } });
    for (const tsumo of [false,true]) {
      const actual = scoreOpenWinningTile(s.hand,parseGameTile(entry.winner),s,tsumo);
      const expected = tsumo ? entry.expectedTsumo : entry.expectedRon;
      const result = actual ? { han:actual.han,fu:actual.fu,main:actual.main,additional:actual.additional,total:actual.total } : null;
      assert.deepEqual(result,expected,`${entry.name}/${entry.winner}/${tsumo ? "tsumo" : "ron"}`);
    }
  }
});
