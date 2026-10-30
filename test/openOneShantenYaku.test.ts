import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { deterministicAdvice } from "../src/evaluation/advisor.js";
import { createOpenOneShantenAnalyzer } from "../src/evaluation/openOneShantenYaku.js";
import { evaluateRoundValue } from "../src/evaluation/value.js";
import { parseGameState, knownTiles, knownTilesOutsideHand, type GameState } from "../src/game/state.js";
import { TILE_NAMES, toCounts } from "../src/game/tiles.js";
import { decide } from "../src/agent/decision.js";
import { evaluateDiscards } from "../src/game/ukeire.js";
import { buildJevRequest } from "../src/jev/client.js";

const fixture = JSON.parse(readFileSync("test/fixtures/open-one-shanten-yaku-19f3329-20261030.json", "utf8"));
const states = fixture.parts.filter((part: any) => part.event === "decision").map((part: any) => parseGameState(part.state)) as GameState[];
const first = states[2]!;
const candidate = (state: GameState, tile: string) => deterministicAdvice(state).candidates.find(row => row.tile === tile)!;

test("recorded first C loses shortest ordinary route, not structural shanten or draw value", () => {
  const result = deterministicAdvice(first);
  const c = result.candidates.find(row => row.tile === "C")!;
  assert.equal(c.shanten, 1);
  assert.equal(c.ukeire, 12);
  assert.equal(c.openOneShantenYaku?.ordinaryProgressUkeire, 0);
  assert.equal(c.openOneShantenYaku?.longerRoutes, "not_evaluated");
  assert.equal(c.estimatedValue, 0);
  assert.equal(c.winProbability, 0);
  assert.ok(c.tenpaiProbability! > 0);
  assert.equal(c.expectedRoundValue, 83); // original 173 included a fictitious ordinary win term
  for (const tile of ["2m", "7m"]) {
    const retained = result.candidates.find(row => row.tile === tile)!;
    assert.equal(retained.shanten, 1);
    assert.equal(retained.openOneShantenYaku?.ordinaryProgressUkeire, 9);
    assert.ok(retained.winProbability! > 0);
  }
  // No honor hardlock or forced dangerous attack; all legal discards survive.
  assert.ok(result.candidates.some(row => row.tile === "C"));
  assert.equal(result.tile, "C");
});

test("recorded second C and later N remain shortest-route yakuless, not future-impossible", () => {
  for (const [state, tile] of [[states[3]!, "C"], [states[4]!, "N"]] as const) {
    const row = candidate(state, tile);
    assert.equal(row.openOneShantenYaku?.ordinaryProgressUkeire, 0);
    assert.equal(row.winProbability, 0);
    assert.ok(row.tenpaiProbability! > 0);
  }
});

test("closed initial chiitoitsu choices and fields remain unchanged", () => {
  for (const [state, tile] of [[states[0]!, "6m"], [states[1]!, "9m"]] as const) {
    const result = deterministicAdvice(state);
    assert.equal(result.tile, tile);
    assert.equal(result.candidates[0]!.form, "chiitoitsu");
    assert.ok(result.candidates.every(row => row.openOneShantenYaku === undefined));
    assert.ok(result.candidates[0]!.winProbability! > 0);
  }
});

test("unknown melds/wind/wall/physical counts retain unknown fallback", () => {
  const cases = [
    { ...first, melds: [] }, { ...first, round: "unknown" },
    { ...first, remainingTiles: undefined }, { ...first, remainingTiles: 4 },
    { ...first, visibleTiles: ["1m", "1m"] },
    { ...first, visibleTiles: ["0s", "0s"] },
    { ...first, opponents: first.opponents.map((opponent, index) => index === 0
      ? { ...opponent, openMeldsObserved: false } : opponent) },
    { ...first, opponents: first.opponents.map((opponent, index) => index === 0
      ? { ...opponent, openMeldsObserved: undefined } : opponent) },
    { ...first, melds: [{ type: "ankan", tiles: ["1m", "1m", "1m", "1m"] }] },
  ];
  const raw = evaluateDiscards([...first.hand, first.draw!], knownTilesOutsideHand(first), 1).find(row => row.tile === "C")!;
  for (const state of cases) assert.equal(createOpenOneShantenAnalyzer(state as GameState)(raw), undefined);
  const mismatched = { ...raw, effectiveTiles: raw.effectiveTiles.map(row => ({ ...row, remaining: row.remaining + 1 })) };
  assert.equal(createOpenOneShantenAnalyzer(first)(mismatched), undefined);
});

test("duplicate, missing and self opponent seats never certify a false zero", () => {
  const east = first.opponents.find(opponent => opponent.seat === "east")!;
  const south = first.opponents.find(opponent => opponent.seat === "south")!;
  const malformed = [
    [east, east, south], // C river counted twice would falsely exhaust C.
    first.opponents.slice(0, 2),
    first.opponents.map(opponent => opponent.seat === "north" ? { ...opponent, seat: first.seat } : opponent),
  ];
  for (const opponents of malformed) {
    const state = parseGameState({ ...first, opponents });
    const row = candidate(state, "2m");
    assert.equal(row.openOneShantenYaku, undefined);
    assert.ok(row.winProbability! > 0);
  }
});

test("invalid opponent groups never create false exhaustion; valid kans remain supported", () => {
  const clean = first.opponents.map(opponent => ({ ...opponent, discards: [], openMelds: 0, melds: [] }));
  for (const meld of [
    { type: "chi", tiles: ["C", "C", "1m"] },
    { type: "chi", tiles: ["2p", "3p", "5p"] },
    { type: "chi", tiles: ["2p", "3s", "4p"] },
    { type: "pon", tiles: ["C", "C", "1m"] },
    { type: "pon", tiles: ["F", "F", "F", "F"] },
    { type: "ankan", tiles: ["F", "F", "F"] },
    { type: "minkan", tiles: ["C", "C", "F", "F"] },
    { type: "kakan", tiles: ["F", "F", "F"] },
  ]) {
    const state = parseGameState({ ...first, opponents: clean.map(opponent => opponent.seat === "east"
      ? { ...opponent, openMelds: 1, melds: [meld] } : opponent) });
    assert.equal(candidate(state, "2m").openOneShantenYaku, undefined, JSON.stringify(meld));
  }
  for (const type of ["ankan", "minkan", "kakan"] as const) {
    const state = parseGameState({ ...first, opponents: clean.map(opponent => opponent.seat === "east"
      ? { ...opponent, openMelds: 1, melds: [{ type, tiles: ["F", "F", "F", "F"] }] } : opponent) });
    assert.ok((candidate(state, "2m").openOneShantenYaku?.ordinaryProgressUkeire ?? 0) > 0);
  }
});

test("state-shared work cap is explicit unknown and never a false zero", () => {
  const counts = toCounts(knownTiles(first));
  // Deliberately overbroad synthetic progress stresses the work guard; this
  // is not a claim that these are actual effective draws in the saved hand.
  const effectiveTiles = TILE_NAMES.flatMap((tile, index) => counts[index]! < 4
    ? [{ tile, remaining: 4 - counts[index]! }] : []);
  const row = candidate(first, "C");
  const analyze = createOpenOneShantenAnalyzer(first);
  const capped = analyze({ ...row, effectiveTiles, ukeire: effectiveTiles.reduce((sum, tile) => sum + tile.remaining, 0) });
  assert.equal(capped?.status, "unknown");
  assert.equal(capped?.unknownReason, "work_limit");
  assert.equal(capped?.ordinaryProgressUkeire, undefined);
  const subsequent = analyze(row);
  assert.equal(subsequent?.status, "unknown");
  assert.equal(subsequent?.ordinaryProgressUkeire, undefined);
  const fallback = evaluateRoundValue({ ...row, openOneShantenYaku: subsequent! }, first);
  assert.equal(fallback.estimatedValue, 1000);
  assert.ok(fallback.winProbability! > 0);
});

test("recorded pon remains viable through C-preserving alternatives, not a blanket call ban", async () => {
  const input = fixture.parts.find((part: any) => part.event === "reaction_call").state;
  const result = await decide(parseGameState(input), { mode: "force-auto" });
  assert.equal(result.callAssessments?.[0]?.approved, true);
  assert.equal(result.selectedAction.action, "pon");
});

test("known yakuhai, tanyao, toitoi and flush routes retain live ordinary witnesses", () => {
  const base = { round: "east_1", seat: "west", remainingTiles: 40, openMelds: 1,
    scores: { east: 25000, south: 25000, west: 25000, north: 25000 }, turn: 5,
    opponents: ["east", "south", "north"].map(seat => ({ seat, discards: [], openMelds: 0, openMeldsObserved: true, melds: [] })) };
  const cases = [
    { ...base, melds: [{ type: "pon", tiles: ["C", "C", "C"] }], hand: ["2m", "2m", "7m", "7m", "2s", "3s", "5s", "6s", "7s", "N"], draw: "9s" },
    { ...base, melds: [{ type: "chi", tiles: ["2p", "3p", "4p"] }], hand: ["2m", "2m", "7m", "7m", "2s", "3s", "0s", "6s", "7s", "N"], draw: "9s" },
    { ...base, melds: [{ type: "pon", tiles: ["1m", "1m", "1m"] }], hand: ["2m", "2m", "2m", "7m", "7m", "2s", "2s", "5s", "N", "N"], draw: "9s" },
    { ...base, melds: [{ type: "chi", tiles: ["1m", "2m", "3m"] }], hand: ["2m", "2m", "7m", "7m", "4m", "5m", "6m", "8m", "N", "N"], draw: "9p" },
  ];
  for (const input of cases) {
    const result = deterministicAdvice(parseGameState(input));
    assert.ok(result.candidates.some(row => row.shanten === 1 && (row.openOneShantenYaku?.ordinaryProgressUkeire ?? 0) > 0), JSON.stringify(input));
  }
});

test("own discard furiten does not erase an ordinary tsumo witness", () => {
  const row = candidate({ ...first, ownDiscards: [...first.ownDiscards, "C"] }, "2m");
  // C is now exhausted, but 1s/4s progress can still make a C singleton
  // wait only if available; zero live C must never be accepted as a witness.
  assert.equal(row.openOneShantenYaku?.ordinaryProgressUkeire, 0);
  const furiten = candidate({ ...first, ownDiscards: [...first.ownDiscards, "1s"] }, "2m");
  assert.ok((furiten.openOneShantenYaku?.ordinaryProgressUkeire ?? 0) > 0);
});

test("Jev profiles receive scoped evidence without removing the defensive C", () => {
  const advice = deterministicAdvice(first);
  for (const profile of ["legacy-v1", "balanced-v2", "hierarchical-v3"] as const) {
    const request = buildJevRequest(first, advice.candidates, "unused-model", profile);
    const text = JSON.stringify(request);
    assert.match(text, /shortest_ordinary_open_progress/);
    assert.match(text, /longerRoutes/);
    assert.match(text, /defensive discard/);
    assert.match(text, /discard_C/);
  }
});

test("threat defense remains possible with corrected value and shape-tenpai term", () => {
  const defended = { ...first, opponents: first.opponents.map((opponent, index) => index === 0 ? { ...opponent, riichi: true } : opponent) };
  const result = deterministicAdvice(defended);
  assert.ok(result.candidates.some(row => row.tile === "C"));
  assert.equal(result.tile, "C");
  const ordinary = candidate(first, "C");
  const { openOneShantenYaku: _proof, ...raw } = ordinary;
  assert.ok(evaluateRoundValue(raw, first).expectedRoundValue! > ordinary.expectedRoundValue!);
});

test("unknown proof status and late situational context cannot be promoted to no route", () => {
  const row = candidate(first, "C");
  const unknown = { ...row, openOneShantenYaku: { ...row.openOneShantenYaku!, status: "unknown" as const } };
  assert.ok(evaluateRoundValue(unknown, first).winProbability! > 0);
  assert.ok(evaluateRoundValue(row, { ...first, remainingTiles: 4 }).winProbability! > 0);
  const mismatch = { ...row, openOneShantenYaku: { ...row.openOneShantenYaku!, discardTile: "2m" } };
  assert.ok(evaluateRoundValue(mismatch, first).winProbability! > 0);
  const scope = { ...row, openOneShantenYaku: { ...row.openOneShantenYaku!, scope: "all_future_wins" as any } };
  assert.ok(evaluateRoundValue(scope, first).winProbability! > 0);
  const shape = { ...row, shanten: 2 };
  assert.ok(evaluateRoundValue(shape, first).winProbability! > 0);
});
