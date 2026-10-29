import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { buildStrategyHandPlan } from "../src/agent/decision.js";
import { handPlanMeldSignature, isHandPlanFeasible, type HandPlanMeld } from "../src/agent/handPlanFeasibility.js";
import { parseGameState, type GameState } from "../src/game/state.js";
import { deterministicAdvice } from "../src/evaluation/advisor.js";
import { buildJevHandPlanRequest, buildJevRequest, handPlanInputCacheKey,
  isHandPlanCompatible, JevClient, type JevHandPlan } from "../src/jev/client.js";

const fixture = JSON.parse(readFileSync("test/fixtures/fixed-meld-hand-plans-20261030.json", "utf8"));
function native(name: string): GameState {
  return parseGameState(fixture.cases.find((row: any) => row.name === name).state);
}
function plan(state: GameState, id: string, legacy = false): JevHandPlan {
  return { actionId: id, planId: id, sourceHand: state.hand, openMelds: state.openMelds,
    ...(legacy ? {} : { melds: state.melds }), confidence: .8, probabilities: { [id]: 1 },
    model: "offline-fixture", promptVersion: "mahjong-hand-plan-v1", latencyMs: 0,
    createdAt: "2026-10-29T21:57:40.021Z" };
}
function criteria(state: GameState, melds: readonly HandPlanMeld[] | undefined = state.melds) {
  return buildJevHandPlanRequest({ hand: state.hand, openMelds: state.openMelds,
    melds, seat: state.seat, round: state.round }, "offline");
}

test("real chi678m states no longer advertise impossible local primary or secondary targets", () => {
  for (const name of ["chi_other_suit_honitsu", "chi_toitoi_secondary", "chi_toitoi_primary", "chi_cached_candidate"]) {
    const state = native(name);
    const actual = buildStrategyHandPlan(state);
    const logged = fixture.cases.find((row: any) => row.name === name).loggedLocalPlan;
    assert.equal(actual.callsAllowed, logged.callsAllowed);
    assert.equal(actual.phase, logged.phase);
    assert.deepEqual(actual.placement, logged.placement);
    assert.deepEqual(actual.requiredTiles, logged.requiredTiles);
    assert.ok(![actual.primaryTarget, actual.secondaryTarget].includes("toitoi"), name);
    assert.ok(![actual.primaryTarget, actual.secondaryTarget].includes("honitsu_s"), name);
    assert.notEqual(actual.primaryTarget, "riichi/efficient_standard");
    const ids = Object.keys(criteria(state).questions.action.criteria);
    for (const impossible of ["toitoi", "honitsu_s", "honitsu_p", "closed_sequence", "chiitoitsu"]) {
      assert.ok(!ids.includes(impossible), `${name}: ${impossible}`);
    }
    assert.ok(ids.includes("efficient_standard"));
    assert.deepEqual(criteria(state).state.melds, state.melds);
  }
});

test("real red-five pon keeps legal toitoi direction but excludes an incompatible half flush", () => {
  const state = native("red_pon_toitoi_positive");
  assert.equal(buildStrategyHandPlan(state).primaryTarget, "toitoi");
  assert.equal(isHandPlanFeasible("toitoi", state.openMelds, state.melds), true);
  const offSuit = native("red_pon_other_suit_honitsu");
  assert.ok(![buildStrategyHandPlan(offSuit).primaryTarget, buildStrategyHandPlan(offSuit).secondaryTarget].includes("honitsu_m"));
  assert.ok(!Object.keys(criteria(offSuit).questions.action.criteria).includes("honitsu_m"));
  const prior = plan(state, "toitoi");
  assert.equal(isHandPlanCompatible(prior, [...state.hand, state.draw!], 1, state.melds), true);
  assert.equal((buildJevRequest(state, deterministicAdvice(state).candidates, "offline", "hierarchical-v3", prior)
    .state.cached_hand_plan as any).selected, "toitoi");
  // The real pre-discard state also contains the legal 4m discard. Its
  // resulting ten-tile source row is paired enough to offer toitoi normally.
  const afterFourMan = [...state.hand, state.draw!];
  afterFourMan.splice(afterFourMan.indexOf("4m"), 1);
  assert.equal(afterFourMan.length, 10);
  assert.ok(Object.keys(buildJevHandPlanRequest({ hand: afterFourMan, openMelds: 1,
    melds: state.melds }, "offline").questions.action.criteria).includes("toitoi"));
});

test("impossible existing cached directions cannot enter the final Jev prompt", () => {
  const state = native("chi_cached_candidate");
  for (const id of ["toitoi", "honitsu_s", "closed_sequence", "chiitoitsu"]) {
    for (const legacy of [true, false]) {
      const cached = plan(state, id, legacy);
      assert.equal(isHandPlanCompatible(cached, [...state.hand, state.draw!], 1, state.melds), false);
      assert.equal(buildJevRequest(state, deterministicAdvice(state).candidates, "offline", "hierarchical-v3", cached)
        .state.cached_hand_plan, undefined);
    }
  }
});

test("generic selected plan cannot leak impossible targets through its top-three alternatives", () => {
  const state = native("chi_cached_candidate");
  for (const legacy of [true, false]) {
    const cached = { ...plan(state, "efficient_standard", legacy),
      probabilities: { efficient_standard: .6, toitoi: .2, honitsu_s: .15, tanyao: .05 } };
    const summary = buildJevRequest(state, deterministicAdvice(state).candidates, "offline", "hierarchical-v3", cached)
      .state.cached_hand_plan as any;
    assert.equal(summary.selected, "efficient_standard");
    assert.deepEqual(summary.alternatives.map((entry: any) => entry.id), ["efficient_standard", "tanyao"]);
  }
});

test("legacy closed plans stay compatible; unknown open groups only retain the generic route", () => {
  const closed = native("closed_legacy_positive");
  assert.equal(isHandPlanCompatible(plan(closed, "closed_sequence", true), [...closed.hand, closed.draw!], 0), true);
  assert.ok(Object.keys(criteria(closed).questions.action.criteria).includes("closed_sequence"));
  const state = native("chi_cached_candidate");
  for (const melds of [undefined, [], [{ type: "chi", tiles: ["7m", "7m", "8m"] }] as HandPlanMeld[]]) {
    const request = buildJevHandPlanRequest({ hand: state.hand, openMelds: 1,
      ...(melds ? { melds } : {}) }, "offline");
    assert.deepEqual(Object.keys(request.questions.action.criteria), ["efficient_standard"]);
    for (const id of ["toitoi", "honitsu_s", "tanyao", "closed_sequence", "chiitoitsu"]) {
      assert.equal(isHandPlanFeasible(id, 1, melds), false);
    }
  }
  assert.equal(isHandPlanCompatible(plan(state, "efficient_standard", true), [...state.hand, state.draw!], 1), true);
  assert.equal(isHandPlanCompatible(plan(state, "toitoi", true), [...state.hand, state.draw!], 1), false);
});

test("cache signatures distinguish immutable meld identity, type, red copies, seat and round", () => {
  const state = native("red_pon_toitoi_positive");
  const key = { hand: state.hand, openMelds: 1, melds: state.melds, seat: state.seat, round: state.round };
  assert.equal(handPlanInputCacheKey(key), handPlanInputCacheKey({ ...key, hand: [...key.hand].reverse(),
    melds: key.melds.map(meld => ({ ...meld, tiles: [...meld.tiles].reverse() })) }));
  for (const altered of [
    { ...key, melds: [{ type: "chi" as const, tiles: ["6m", "7m", "8m"] }] },
    { ...key, melds: [{ type: "pon" as const, tiles: ["5p", "5p", "5p"] }] },
    { ...key, seat: "south" }, { ...key, round: "south_1" },
  ]) assert.notEqual(handPlanInputCacheKey(key), handPlanInputCacheKey(altered));
  assert.equal(isHandPlanCompatible(plan(state, "efficient_standard"), [...state.hand, state.draw!], 1,
    [{ type: "chi", tiles: ["6m", "7m", "8m"] }]), false);
  assert.notEqual(handPlanMeldSignature(1, [{ type: "ankan", tiles: ["5p", "5p", "5p", "0p"] }]),
    handPlanMeldSignature(1, [{ type: "minkan", tiles: ["5p", "5p", "5p", "0p"] }]));
});

test("fixed honor/terminal groups cannot support tanyao; concealed quads remain closed but not seven-pairs", () => {
  assert.equal(isHandPlanFeasible("tanyao", 1, [{ type: "pon", tiles: ["P", "P", "P"] }]), false);
  assert.equal(isHandPlanFeasible("tanyao", 1, [{ type: "chi", tiles: ["1m", "2m", "3m"] }]), false);
  assert.equal(isHandPlanFeasible("honitsu_s", 1, [{ type: "pon", tiles: ["P", "P", "P"] }]), true);
  assert.equal(isHandPlanFeasible("closed_sequence", 1, [{ type: "ankan", tiles: ["4s", "4s", "4s", "4s"] }]), true);
  assert.equal(isHandPlanFeasible("chiitoitsu", 1, [{ type: "ankan", tiles: ["4s", "4s", "4s", "4s"] }]), false);
});

test("an unknown current meld context removes named alternatives even from a generic legacy cache", () => {
  const state = native("chi_cached_candidate");
  const unknown = { ...state, melds: [] };
  const cached = { ...plan(state, "efficient_standard", true),
    probabilities: { efficient_standard: .6, toitoi: .2, honitsu_s: .15, tanyao: .05 } };
  const summary = buildJevRequest(unknown, deterministicAdvice(unknown).candidates, "offline", "hierarchical-v3", cached)
    .state.cached_hand_plan as any;
  assert.equal(summary.selected, "efficient_standard");
  assert.deepEqual(summary.alternatives.map((entry: any) => entry.id), ["efficient_standard"]);
  assert.equal(isHandPlanCompatible(plan(state, "toitoi"), [...state.hand, state.draw!], 1), false);
});

test("chooseHandPlan transports and freezes the actual meld context without an LLM call", async () => {
  const state = native("chi_cached_candidate");
  const melds = state.melds.map(meld => ({ ...meld, tiles: [...meld.tiles] }));
  const originalFetch = globalThis.fetch;
  let observed: any;
  globalThis.fetch = (async (_url, options) => {
    observed = JSON.parse(options!.body as string);
    const ids = Object.keys(observed.questions.action.criteria);
    melds[0]!.tiles[0] = "P";
    return new Response(JSON.stringify({ model: "offline", answers: { action: { type: "choice",
      choice: "efficient_standard", confidence: 1,
      probabilities: Object.fromEntries(ids.map(id => [id, id === "efficient_standard" ? 1 : 0])) } } }));
  }) as typeof fetch;
  try {
    const actual = await new JevClient("offline-test").chooseHandPlan({ hand: state.hand, openMelds: 1, melds });
    assert.deepEqual(observed.state.melds, state.melds);
    assert.deepEqual(actual.melds, state.melds);
    assert.notEqual(actual.melds![0]!.tiles[0], "P");
    assert.ok(!Object.keys(observed.questions.action.criteria).includes("toitoi"));
  } finally { globalThis.fetch = originalFetch; }
});
