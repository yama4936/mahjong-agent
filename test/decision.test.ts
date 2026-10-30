import assert from "node:assert/strict";
import test from "node:test";
import { buildStrategyHandPlan, decide, decideForceAutoWithJevDeadline } from "../src/agent/decision.js";
import { parseGameState } from "../src/game/state.js";
import { readFile } from "node:fs/promises";
import type { ClosedWaitReport } from "../src/evaluation/closedWaitScorer.js";
import type { JevClient } from "../src/jev/client.js";

const state = parseGameState({
  hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"],
  draw: "6p",
  recognitionConfidence: 1,
});

test("verified East-only final round reaches placement strategy without relabeling the round wind", async () => {
  const fixture = JSON.parse(await readFile("test/fixtures/east-only-final-round-20261021.json", "utf8"));
  const live = parseGameState({ ...fixture.state, matchLength: "east" });
  const plan = buildStrategyHandPlan(live);
  assert.equal(live.round, "east_4");
  assert.equal(plan.placement.rank, 4);
  assert.equal(plan.placement.allLast, true);
  assert.match(plan.changeReason, /オーラス/);
  const halfGame = parseGameState({ ...fixture.state, matchLength: "south" });
  assert.equal(buildStrategyHandPlan(halfGame).placement.allLast, false);
  assert.equal(buildStrategyHandPlan(parseGameState(fixture.state)).placement.allLast, false);
});

test("late value ordering cannot hide the actual open-hand tenpai discard from Jev", async () => {
  const fixture = JSON.parse(await readFile("test/fixtures/late-open-tenpai-candidate-20261021.json", "utf8"));
  const live = parseGameState(fixture.state);
  let offered: string[] = [];
  const jev = { chooseDiscard: async (_state: unknown, candidates: Array<{ actionId: string; tile: string }>) => {
    offered = candidates.map(candidate => candidate.tile);
    return { actionId: candidates[0]!.actionId, confidence: 1,
      probabilities: { [candidates[0]!.actionId]: 1 }, model: "first-offered-test", promptVersion: "test", latencyMs: 0 };
  } } as unknown as JevClient;
  const result = await decide(live, { mode: "force-auto", jev });
  // Preserve the certified open winning tenpai in both local ordering and Jev input.
  assert.equal(result.candidates[0]!.shanten, 0);
  assert.equal(result.candidates.find(candidate => candidate.tile === "8s")!.shanten, 0);
  assert.deepEqual(offered, ["8s"]);
  assert.deepEqual(result.selectedAction, { id: "discard_8s", action: "discard", tile: "8s" });
});

test("declaration comparison can choose dama and invalid/scorer failures retain riichi", async () => {
  const live = parseGameState(JSON.parse(await readFile("artifacts/live/south4-riichi-replay-20260928.json", "utf8")).state);
  const report: ClosedWaitReport = { library: "mahjong==2.0.0", discard: "5m",
    scope: "closed_hand_scoring_not_policy_ev", assumptions: { furiten_not_checked: true }, rows: [] };
  const choice = (actionId: string) => ({ actionId, confidence: 0.99, probabilities: { [actionId]: 1 },
    model: "test", promptVersion: "test", latencyMs: 0 });
  const jev = { chooseDiscard: async () => choice("discard_5m"),
    chooseDeclaration: async (_state: unknown, actions: any[], received: ClosedWaitReport) => {
      assert.deepEqual(actions.map((action) => action.id), ["discard_5m", "riichi_discard_5m"]);
      assert.equal(received, report);
      return choice("discard_5m");
    } } as unknown as JevClient;
  const dama = await decide(live, { mode: "advisor", jev, riichiScorer: async () => report });
  assert.equal(dama.selectedAction.action, "discard");
  assert.equal(dama.declarationComparison?.status, "selected");
  assert.ok(dama.riichiAssessment?.reasons.includes("declaration_comparison_selected_dama"));
  const failed = await decide(live, { mode: "advisor", jev, riichiScorer: async () => { throw new Error("scorer unavailable"); } });
  assert.equal(failed.selectedAction.action, "riichi");
  assert.equal(failed.declarationComparison?.reason, "Preselection declaration scoring unavailable within budget");
  const invalid = { ...jev, chooseDeclaration: async () => choice("discard_1m") } as unknown as JevClient;
  const rejected = await decide(live, { mode: "advisor", jev: invalid, riichiScorer: async () => report });
  assert.equal(rejected.selectedAction.action, "riichi");
  assert.equal(rejected.declarationComparison?.status, "fallback");
  assert.equal(rejected.declarationComparison?.report, report);
  assert.equal(rejected.declarationComparison?.decision?.actionId, "discard_1m");
  const uncertain = { ...jev, chooseDeclaration: async () => ({ ...choice("discard_5m"), confidence: 0.5 }) } as unknown as JevClient;
  const low = await decide(live, { mode: "advisor", jev: uncertain, riichiScorer: async () => report });
  assert.equal(low.selectedAction.action, "riichi");
  assert.equal(low.declarationComparison?.decision?.confidence, 0.5);
});

test("defensive candidate filter retains live dama and certified open tenpai without riichi UI", async () => {
  const fixture = JSON.parse(await readFile("test/fixtures/late-open-tenpai-candidate-20261021.json", "utf8"));
  const cases = [
    { state: parseGameState({ ...fixture.state, availableUiActions: [], opponents: [{ seat: "south", discards: ["6m"], riichi: true }] }), tile: "8s" },
    { state: parseGameState({ hand: ["2m", "2m", "3m", "3m", "4p", "4p", "5p", "5p", "6s", "6s", "7s", "7s", "8s"],
      draw: "E", availableUiActions: [], opponents: [{ seat: "south", discards: ["2m"], riichi: true }] }), tile: "E" },
  ];
  for (const scenario of cases) {
    const jev = { chooseDiscard: async (_state: unknown, candidates: any[]) => {
      const tenpai = candidates.find(candidate => candidate.tile === scenario.tile);
      assert.ok(tenpai, "a live winning tenpai must reach the push/fold comparison");
      assert.equal(tenpai.shanten, 0);
      if (scenario.state.openMelds) assert.ok(tenpai.openTenpaiScore.winningUkeire > 0);
      assert.ok(candidates.some(candidate => candidate.shanten > 0), "safe retreats remain available");
      return { actionId: tenpai.actionId, confidence: 1, probabilities: {}, model: "test", promptVersion: "test", latencyMs: 0 };
    } } as unknown as JevClient;
    const result = await decide(scenario.state, { mode: "force-auto", jev });
    assert.equal(result.source, "jev");
    assert.equal(result.tile, scenario.tile);
    assert.equal(result.selectedAction.action, "discard");
  }
});

test("discard adoption rejects legal candidates excluded from the supplied comparison", async () => {
  const jev = { chooseDiscard: async (_state: unknown, candidates: any[]) => {
    assert.ok(!candidates.some(candidate => candidate.actionId === "discard_1m"));
    return { actionId: "discard_1m", confidence: 1, probabilities: {}, model: "test", promptVersion: "test", latencyMs: 0 };
  } } as unknown as JevClient;
  const result = await decide(state, { mode: "force-auto", jev });
  assert.equal(result.source, "deterministic");
  assert.notEqual(result.tile, "1m");
  assert.ok(result.safety.reasons.some(reason => reason.includes("unknown candidate")));
});

test("discard comparison keeps completed scoring when a sibling exceeds its deadline", async () => {
  const live = parseGameState({ hand: ["2m", "2m", "3m", "3m", "4p", "4p", "5p", "5p", "6s", "6s", "7s", "7s", "8s"],
    draw: "E", availableUiActions: ["riichi"], scores: { east: 25000 } });
  const report: ClosedWaitReport = { library: "mahjong==2.0.0", discard: "E",
    scope: "closed_hand_scoring_not_policy_ev", assumptions: {}, rows: [] };
  let abortedSlow = false;
  const scorer = async (_state: unknown, tile: string, _waits: unknown, options: { signal?: AbortSignal } = {}) => {
    if (tile === "E") return report;
    options.signal?.addEventListener("abort", () => { abortedSlow = true; }, { once: true });
    return new Promise<ClosedWaitReport>(() => {});
  };
  const jev = { chooseDiscard: async (_state: unknown, candidates: any[]) => {
    assert.equal(candidates.find(candidate => candidate.tile === "E")?.closedWaitScore, report);
    assert.equal(candidates.find(candidate => candidate.tile === "8s")?.closedWaitScore, undefined);
    return { actionId: "discard_E", confidence: 1, probabilities: {}, model: "test", promptVersion: "test", latencyMs: 0 };
  } } as unknown as JevClient;
  const result = await decide(live, { mode: "force-auto", jev, riichiScorer: scorer });
  assert.equal(result.source, "jev");
  assert.equal(abortedSlow, true);
});

test("live south-three highlighted chi is passed without shanten gain or viable yaku", async () => {
  const reaction = parseGameState({
    phase: "reaction", round: "south_3", seat: "south", honba: 4, riichiSticks: 3,
    scores: { south: 28000, west: 38500, north: 13000, east: 17500 },
    hand: ["5m", "7m", "9m", "1p", "3p", "5p", "7p", "9p", "3s", "5s", "6s", "7s", "8s"],
    pendingDiscard: { tile: "8s", fromSeat: "east" }, availableUiActions: ["chi", "pass"],
    recognitionConfidence: 1,
  });
  const decision = await decide(reaction, { mode: "advisor" });
  assert.equal(decision.selectedAction.action, "pass");
  const assessment = decision.callAssessments?.find((item) => item.actionId === "chi_8s_6s_7s");
  assert.equal(assessment?.currentShanten, 3);
  assert.equal(assessment?.resultingShanten, 3);
  assert.equal(assessment?.approved, false);
  assert.deepEqual(assessment?.reasons, ["no_strict_shanten_improvement", "no_viable_yaku_path"]);
});

test("live sequence-heavy seven-sou pon cannot claim an unsupported toitoi path", async () => {
  const reaction = parseGameState({
    phase: "reaction", round: "south_4", seat: "east",
    hand: ["5m", "6m", "7m", "8m", "9m", "2p", "3p", "4p", "7s", "7s", "8s", "8s", "9s"],
    opponents: [{ seat: "south", discards: ["7s", "4s", "7s"] }],
    pendingDiscard: { tile: "7s", fromSeat: "south", inRiver: true },
    availableUiActions: ["pon", "pass"], recognitionConfidence: 1,
  });
  const decision = await decide(reaction, { mode: "advisor" });
  assert.equal(decision.selectedAction.action, "pass");
  assert.equal(decision.callAssessments?.[0]?.shantenImprovement, 1);
  assert.deepEqual(decision.callAssessments?.[0]?.candidateYaku, []);
  assert.ok(decision.callAssessments?.[0]?.reasons.includes("no_viable_yaku_path"));
});

test("tanyao calls retain exposed terminals but may discard a concealed terminal", async () => {
  const terminalMeld = parseGameState({
    phase: "reaction", seat: "south", round: "east_1",
    hand: ["1m", "2m", "2p", "3p", "4p", "4p", "5p", "6p", "4s", "5s", "6s", "7s", "7s"],
    pendingDiscard: { tile: "3m", fromSeat: "east" }, availableUiActions: ["chi", "pass"],
  });
  const invalid = await decide(terminalMeld, { mode: "advisor" });
  assert.equal(invalid.callAssessments?.[0]?.candidateYaku.includes("tanyao"), false);
  const discardable = parseGameState({
    phase: "reaction", seat: "south", round: "east_1",
    hand: ["1m", "2p", "3p", "4p", "4p", "5p", "6p", "4s", "5s", "6s", "7s", "7s", "8s"],
    pendingDiscard: { tile: "7s", fromSeat: "east" }, availableUiActions: ["chi", "pass"],
  });
  const valid = await decide(discardable, { mode: "advisor" });
  assert.ok(valid.callAssessments?.find((item) => item.actionId === "chi_7s_5s_6s")?.candidateYaku.includes("tanyao"));
  const unknownMeld = parseGameState({
    phase: "reaction", seat: "south", round: "east_1", openMelds: 1,
    hand: ["2m", "3m", "4m", "4p", "5p", "6p", "3s", "4s", "6s", "6s"],
    pendingDiscard: { tile: "5s", fromSeat: "east" }, availableUiActions: ["chi", "pass"],
  });
  const incomplete = await decide(unknownMeld, { mode: "advisor" });
  assert.ok(incomplete.callAssessments?.every((item) => !item.candidateYaku.includes("tanyao")));
});

test("advisor produces a recommendation but is never executable", async () => {
  const result = await decide(state, { mode: "advisor" });
  assert.equal(result.tile, "E");
  assert.equal(result.executable, false);
  assert.equal(result.safety.allowed, true);
});

test("auto mode refuses to act without Jev", async () => {
  const result = await decide(state, { mode: "auto" });
  assert.equal(result.executable, false);
  assert.ok(result.safety.reasons.includes("jev_required_for_auto_mode"));
});

test("auto refuses explicitly unobserved opponent melds", async () => {
  const incomplete = parseGameState({
    ...state,
    opponents: [{ seat: "south", openMelds: 0, openMeldsObserved: false }],
  });
  const result = await decide(incomplete, { mode: "auto" });
  assert.equal(result.executable, false);
  assert.ok(result.safety.reasons.includes("opponent_melds_not_fully_observed"));
});

test("dead tenpai does not spend a riichi stick but keeps the legal action visible", async () => {
  const dead = parseGameState({
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "1p", "2p", "3p", "4s", "5s", "6s", "E"],
    draw: "9p", scores: { east: 25000 }, availableUiActions: ["riichi"], remainingTiles: 37,
    visibleTiles: ["E", "E", "E", "9p", "9p", "9p"],
  });
  const result = await decide(dead, { mode: "advisor" });
  assert.equal(result.selectedAction.action, "discard");
  assert.equal(result.riichiAssessment?.remainingWinningTiles, 0);
  assert.equal(result.riichiAssessment?.approved, false);
  assert.ok(result.riichiAssessment?.reasons.includes("no_remaining_winning_tiles"));
  assert.ok(result.legalActions.some((action) => action.action === "riichi"));
  const live = await decide(parseGameState({ ...dead, visibleTiles: [] }), { mode: "advisor" });
  assert.equal(live.selectedAction.action, "riichi");
  assert.equal(live.riichiAssessment?.approved, true);
});

test("low recognition confidence blocks action", async () => {
  const unsafe = parseGameState({ ...state, recognitionConfidence: 0.5 });
  const result = await decide(unsafe, { mode: "advisor" });
  assert.equal(result.safety.allowed, false);
});

test("auto requires a complete and internally consistent public state", async () => {
  const complete = parseGameState({
    ...state,
    round: "east_1",
    scores: { east: 25000, south: 25000, west: 25000, north: 25000 },
    doraIndicators: ["4s"],
    remainingTiles: 60,
    publicStateConfidence: 1,
    opponents: [
      { seat: "south", discards: [] },
      { seat: "west", discards: [] },
      { seat: "north", discards: [] },
    ],
  });
  const jev = { chooseDiscard: async (_state: unknown, candidates: any[]) => ({
    actionId: candidates[0].actionId,
    confidence: 1,
    probabilities: Object.fromEntries(candidates.map((candidate) => [candidate.actionId, candidate === candidates[0] ? 1 : 0])),
    model: "fake",
    promptVersion: "test",
    latencyMs: 1,
  }) } as any;
  const result = await decide(complete, { mode: "auto", jev });
  assert.deepEqual(result.safety.reasons, []);
  assert.equal(result.executable, true);
});

test("winning and riichi UI actions are selected ahead of a plain discard", async () => {
  const winning = parseGameState({
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "1p", "2p", "3p", "7s", "8s", "9s", "E"],
    draw: "E",
    availableUiActions: ["tsumo"],
  });
  assert.equal((await decide(winning, { mode: "advisor" })).selectedAction.action, "tsumo");

  const ready = parseGameState({ ...state, scores: { east: 25000 }, availableUiActions: ["riichi"] });
  const result = await decide(ready, { mode: "advisor" });
  assert.equal(result.selectedAction.action, "riichi");
  assert.equal(result.selectedActionId, "riichi_discard_E");
});

test("force-auto remains executable when normal safety checks are ambiguous", async () => {
  const unsafe = parseGameState({ ...state, recognitionConfidence: 0.5 });
  const result = await decide(unsafe, { mode: "force-auto" });
  assert.equal(result.safety.allowed, false);
  assert.equal(result.executable, true);
});

test("force-auto gives Jev only non-worsening shanten choices when not under threat", async () => {
  const pairs = parseGameState({
    hand: ["1m", "1m", "2m", "2m", "3p", "3p", "4p", "4p", "5s", "5s", "E", "E", "P"],
    draw: "F",
    recognitionConfidence: 0.5,
  });
  let offered: any[] = [];
  const jev = { chooseDiscard: async (_state: unknown, candidates: any[]) => {
    offered = candidates;
    return {
      actionId: candidates[0].actionId,
      confidence: 1,
      probabilities: Object.fromEntries(candidates.map((candidate: any, index: number) => [candidate.actionId, index ? 0 : 1])),
      model: "fake", promptVersion: "test", latencyMs: 1,
    };
  } } as any;

  await decide(pairs, { mode: "force-auto", jev });
  assert.ok(offered.length > 0);
  assert.ok(offered.every((candidate) => candidate.shanten === Math.min(...offered.map((item) => item.shanten))));
});

test("force-auto adopts a valid Jev decision before its deadline", async (t) => {
  t.mock.method(performance, "now", () => 0);
  const local = await decide(state, { mode: "force-auto" });
  const jev = { chooseDiscard: async (_state: unknown, candidates: any[]) => {
    const selected = candidates.find((candidate) => candidate.actionId !== local.selectedActionId) ?? candidates[0];
    return {
      actionId: selected.actionId,
      confidence: 0.8,
      probabilities: Object.fromEntries(candidates.map((candidate) => [candidate.actionId, candidate === selected ? 1 : 0])),
      model: "fake", promptVersion: "test", latencyMs: 1,
    };
  } } as any;

  const result = await decideForceAutoWithJevDeadline(state, { jev, deadlineMs: 1_000 });

  assert.equal(result.source, "jev");
  assert.equal(result.arbitration?.selectedSource, "jev");
  assert.equal(result.arbitration?.deadlineMs, 1_000);
});

test("force-auto falls back locally when Jev exceeds its deadline", async (t) => {
  t.mock.method(performance, "now", () => 0);
  let aborted = false;
  const jev = { chooseDiscard: async (_state: unknown, _candidates: any[], signal: AbortSignal) => (
    new Promise((_resolve, reject) => signal.addEventListener("abort", () => { aborted = true; reject(new Error("aborted")); }, { once: true }))
  ) } as any;

  const result = await decideForceAutoWithJevDeadline(state, { jev, deadlineMs: 5 });

  assert.equal(result.source, "deterministic");
  assert.equal(result.arbitration?.selectedSource, "local");
  assert.equal(result.arbitration?.fallbackReason, "deadline_exceeded");
  assert.equal(aborted, true);
});

test("force-auto falls back locally when Jev fails", async (t) => {
  t.mock.method(performance, "now", () => 0);
  const jev = { chooseDiscard: async () => { throw new Error("offline"); } } as any;

  const result = await decideForceAutoWithJevDeadline(state, { jev, deadlineMs: 1_000 });

  assert.equal(result.source, "deterministic");
  assert.equal(result.arbitration?.selectedSource, "local");
  assert.equal(result.arbitration?.fallbackReason, "jev_error");
});

test("force-auto rejects a resolved Jev result that has already consumed its deadline", async (t) => {
  let elapsed = 0;
  t.mock.method(performance, "now", () => elapsed);
  const jev = { chooseDiscard: async (_state: unknown, candidates: any[]) => {
    // Synchronous work can postpone the timer until after promise microtasks.
    elapsed = 501;
    return { actionId: candidates[0].actionId, confidence: 0.9,
      probabilities: { [candidates[0].actionId]: 1 }, model: "fake", promptVersion: "test", latencyMs: 1 };
  } } as any;

  const result = await decideForceAutoWithJevDeadline(state, { jev, deadlineMs: 500 });
  assert.equal(result.arbitration?.selectedSource, "local");
  assert.equal(result.arbitration?.fallbackReason, "deadline_exceeded");
  assert.equal(result.source, "deterministic");
});

test("ranked deadline fixture preserves local advice and remote candidate choices", async () => {
  const fixture = JSON.parse(await readFile("test/fixtures/ranked-deadline-overrun-20261021.json", "utf8"));
  const live = parseGameState(fixture.state);
  const local = await decide(live, { mode: "force-auto" });
  let offered: any[] = [];
  const jev = { chooseDiscard: async (_state: unknown, candidates: any[]) => {
    offered = structuredClone(candidates);
    const selected = candidates.at(-1)!;
    return { actionId: selected.actionId, confidence: 0.9,
      probabilities: { [selected.actionId]: 1 }, model: "fake", promptVersion: "test", latencyMs: 1 };
  } } as any;
  const expected = await decide(live, { mode: "force-auto", jev });
  const expectedOffers = structuredClone(offered);
  const actual = await decideForceAutoWithJevDeadline(live, { jev, deadlineMs: 10_000 });
  assert.equal(local.tile, "1m");
  assert.deepEqual(offered, expectedOffers);
  assert.deepEqual(actual.candidates, local.candidates);
  assert.deepEqual(actual.handPlan, expected.handPlan);
  assert.deepEqual(actual.selectedAction, expected.selectedAction);
  const fallback = await decideForceAutoWithJevDeadline(live, { deadlineMs: 10_000 });
  const { arbitration: _arbitration, ...fallbackDecision } = fallback;
  assert.deepEqual(fallbackDecision, local);
  // Sharing must end with this request: a later draw needs fresh analysis.
  const next = parseGameState({ ...live, draw: "E" });
  const nextExpected = await decide(next, { mode: "force-auto", jev });
  const nextActual = await decideForceAutoWithJevDeadline(next, { jev, deadlineMs: 10_000 });
  assert.deepEqual(nextActual.candidates, nextExpected.candidates);
  assert.deepEqual(nextActual.legalActions, nextExpected.legalActions);
  assert.deepEqual(nextActual.handPlan, nextExpected.handPlan);
  assert.deepEqual(nextActual.selectedAction, nextExpected.selectedAction);
});

test("advisor recommends a non-worsening closed kan outside riichi", async () => {
  const closed = parseGameState({
    hand: ["1m", "2m", "3m", "1p", "2p", "3p", "1s", "2s", "3s", "E", "E", "E", "E"],
    draw: "5m",
    availableUiActions: ["kan"],
  });
  assert.equal((await decide(closed, { mode: "advisor" })).selectedAction.action, "ankan");
  const riichi = parseGameState({ ...closed, riichiDeclared: true });
  assert.notEqual((await decide(riichi, { mode: "advisor" })).selectedAction.action, "ankan");
});

test("reaction policy wins immediately and folds calls against riichi", async () => {
  const ron = parseGameState({
    phase: "reaction",
    seat: "south",
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "1p", "2p", "3p", "7s", "8s", "9s", "E"],
    pendingDiscard: { tile: "E", fromSeat: "east" },
    availableUiActions: ["ron", "pon", "pass"],
  });
  assert.equal((await decide(ron, { mode: "advisor" })).selectedAction.action, "ron");
  const passJev = { chooseReaction: async () => { throw new Error("Jev must not run for ron"); } } as any;
  assert.equal((await decide(ron, { mode: "force-auto", jev: passJev })).selectedAction.action, "ron");

  const threatened = parseGameState({
    phase: "reaction",
    seat: "south",
    hand: ["1m", "2m", "4m", "4m", "4m", "5p", "6p", "7p", "2s", "3s", "4s", "E", "E"],
    pendingDiscard: { tile: "3m", fromSeat: "east" },
    availableUiActions: ["chi", "pass"],
    opponents: [{ seat: "east", discards: [], riichi: true }],
  });
  assert.equal((await decide(threatened, { mode: "advisor" })).selectedAction.action, "pass");
});

test("reaction policy rejects a shanten-improving call without a viable yaku", async () => {
  const callable = parseGameState({
    phase: "reaction",
    seat: "south",
    hand: ["1m", "2m", "3p", "9m", "4s", "5p", "P", "C", "3m", "4p", "4s", "5m", "1s"],
    pendingDiscard: { tile: "3m", fromSeat: "east" },
    availableUiActions: ["chi", "pass"],
  });
  const local = await decide(callable, { mode: "advisor" });
  assert.equal(local.selectedAction.action, "pass");
  assert.deepEqual(local.callAssessments?.[0]?.reasons, ["no_viable_yaku_path"]);
  const jev = { chooseReaction: async (_state: unknown, actions: any[]) => ({
    actionId: actions.find((action) => action.action === "pass").id,
    confidence: 0.88,
    probabilities: Object.fromEntries(actions.map((action) => [action.id, action.action === "pass" ? 0.88 : 0.12])),
    model: "fake", promptVersion: "mahjong-reaction-v1", latencyMs: 1,
  }) } as any;
  const judged = await decide(callable, { mode: "advisor", jev });
  assert.equal(judged.selectedAction.action, "pass");
  assert.equal(judged.source, "jev");
  assert.equal(judged.jev?.promptVersion, "mahjong-reaction-v1");
});

test("force-auto restricts Jev to safer tiles under threat", async () => {
  const threatened = parseGameState({
    ...state, turn: 12,
    opponents: [{ seat: "south", discards: ["E"], riichi: true }],
  });
  let offered: any[] = [];
  const jev = { chooseDiscard: async (_state: unknown, candidates: any[]) => {
    offered = candidates;
    return { actionId: candidates[0].actionId, confidence: 1, probabilities: {}, model: "fake", promptVersion: "test", latencyMs: 1 };
  } } as any;
  const result = await decide(threatened, { mode: "force-auto", jev });
  assert.ok(offered.length > 0);
  const eligible = result.candidates.filter((candidate) => candidate.shanten <= Math.min(...result.candidates.map((item) => item.shanten)) + 1);
  const safest = Math.min(...eligible.map((candidate) => candidate.danger ?? 1));
  assert.ok(offered.every((candidate) => (candidate.danger ?? 1) <= safest + 0.02
    || candidate.shanten === 0 && candidate.ukeire > 0));
});

test("threat filtering retains live riichi discard for declaration comparison", async () => {
  const live = parseGameState({
    round: "east_1", seat: "east", turn: 6, remainingTiles: 41,
    scores: { east: 25000, south: 25000, west: 25000, north: 25000 },
    hand: ["4m", "5m", "2p", "3p", "4p", "6p", "6p", "4s", "0s", "5s", "6s", "7s", "W"],
    draw: "3m", doraIndicators: ["8p"], availableUiActions: ["riichi"],
    ownDiscards: ["9s", "5p", "1s", "3p", "7m", "1m"],
    opponents: [
      { seat: "south", discards: ["7s", "E", "3m", "2p", "8m", "E", "9p", "3s"], openMelds: 2 },
      { seat: "west", discards: ["S", "2p", "9s", "S", "3m", "C", "9p"], openMelds: 0 },
      { seat: "north", discards: ["1p", "S", "C", "E", "2s", "8p", "8m"], openMelds: 0 },
    ],
  });
  const report: ClosedWaitReport = { library: "mahjong==2.0.0", discard: "W",
    scope: "closed_hand_scoring_not_policy_ev", assumptions: { furiten_not_checked: true }, rows: [] };
  for (const actionId of ["riichi_discard_W", "discard_W"]) {
    let offered: string[] = [];
    const choice = (id: string) => ({ actionId: id, confidence: 1, probabilities: { [id]: 1 }, model: "test", promptVersion: "test", latencyMs: 0 });
    const jev = { chooseDiscard: async (_state: unknown, candidates: any[]) => {
      offered = candidates.map((candidate) => candidate.actionId);
      assert.equal(candidates.find((candidate) => candidate.actionId === "discard_W")?.closedWaitScore, report);
      assert.equal(candidates.find((candidate) => candidate.actionId === "discard_3m")?.closedWaitScore, undefined);
      return choice("discard_W");
    }, chooseDeclaration: async (_state: unknown, actions: any[]) => {
      assert.deepEqual(actions.map((action) => action.id), ["discard_W", "riichi_discard_W"]);
      return choice(actionId);
    } } as unknown as JevClient;
    const result = await decide(live, { mode: "force-auto", jev, riichiScorer: async () => report });
    assert.ok(offered.includes("discard_W"));
    assert.ok(offered.includes("discard_3m"));
    assert.equal(result.selectedAction.id, actionId);
    assert.equal(result.declarationComparison?.status, "selected");
  }
  let observedAbort = false;
  let jevCalled = false;
  const slowScorer: typeof import("../src/evaluation/closedWaitScorer.js").scoreClosedWaits = async (_state, _discard, _waits, options) => {
    options?.signal?.addEventListener("abort", () => { observedAbort = true; }, { once: true });
    return new Promise(() => {});
  };
  const safeJev = { chooseDiscard: async (_state: unknown, candidates: any[]) => {
    jevCalled = true;
    assert.equal(candidates.find((candidate) => candidate.actionId === "discard_W")?.closedWaitScore, undefined);
    return { actionId: "discard_3m", confidence: 1, probabilities: { discard_3m: 1 }, model: "test", promptVersion: "test", latencyMs: 0 };
  } } as unknown as JevClient;
  const started = performance.now();
  const fallback = await decide(live, { mode: "force-auto", jev: safeJev, riichiScorer: slowScorer });
  assert.ok(performance.now() - started < 1500, "slow scorer must not block discard decision");
  assert.equal(jevCalled, true);
  assert.equal(observedAbort, true);
  assert.equal(fallback.selectedAction.id, "discard_3m");
  let scorerCalls = 0;
  const hangingScorer: typeof slowScorer = async () => { scorerCalls++; return new Promise(() => {}); };
  const riichiJev = { chooseDiscard: async () => ({ actionId: "discard_W", confidence: 1,
    probabilities: { discard_W: 1 }, model: "test", promptVersion: "test", latencyMs: 0 }),
    chooseDeclaration: async () => { throw new Error("must not compare without scoring"); } } as unknown as JevClient;
  const retryStarted = performance.now();
  const retryFallback = await decide(live, { mode: "force-auto", jev: riichiJev, riichiScorer: hangingScorer });
  assert.ok(performance.now() - retryStarted < 1500, "timed-out scoring must not be retried after tile selection");
  assert.equal(scorerCalls, 1);
  assert.equal(retryFallback.selectedAction.id, "riichi_discard_W");
  assert.equal(retryFallback.declarationComparison?.status, "fallback");
  let lateCalls = 0;
  let declarationCalled = false;
  const lateScorer: typeof slowScorer = async () => {
    lateCalls++;
    await new Promise((resolve) => setTimeout(resolve, 250));
    return report;
  };
  const delayedJev = { chooseDiscard: async () => {
    await new Promise((resolve) => setTimeout(resolve, 150));
    return { actionId: "discard_W", confidence: 1, probabilities: { discard_W: 1 }, model: "test", promptVersion: "test", latencyMs: 0 };
  }, chooseDeclaration: async () => { declarationCalled = true; throw new Error("late result used"); } } as unknown as JevClient;
  const lateFallback = await decide(live, { mode: "force-auto", jev: delayedJev, riichiScorer: lateScorer });
  assert.equal(lateCalls, 1);
  assert.equal(declarationCalled, false);
  assert.equal(lateFallback.declarationComparison?.status, "fallback");
});

test("reaction policy certifies a strict-improvement yakuhai pon", async () => {
  const callable = parseGameState({
    phase: "reaction", seat: "south",
    hand: ["P", "P", "3s", "8p", "3p", "3s", "5s", "7s", "7m", "2p", "3p", "5m", "E"],
    pendingDiscard: { tile: "P", fromSeat: "east" }, availableUiActions: ["pon", "pass"], turn: 5,
  });
  const result = await decide(callable, { mode: "advisor" });
  assert.equal(result.selectedAction.action, "pon");
  assert.equal(result.callAssessments?.[0]?.approved, true);
  assert.deepEqual(result.callAssessments?.[0]?.confirmedYaku, ["yakuhai:P"]);
  assert.equal(result.handPlan.phase, "early_efficiency");
  assert.ok(result.handPlan.primaryTarget.length > 0);
});

test("Jev pass cannot override a certified strict-improvement call", async () => {
  const callable = parseGameState({
    phase: "reaction", seat: "south",
    hand: ["P", "P", "3s", "8p", "3p", "3s", "5s", "7s", "7m", "2p", "3p", "5m", "E"],
    pendingDiscard: { tile: "P", fromSeat: "east" }, availableUiActions: ["pon", "pass"], turn: 5,
  });
  const jev = { chooseReaction: async (_state: unknown, actions: any[]) => ({
    actionId: actions.find((action) => action.action === "pass").id, confidence: 0.9,
    probabilities: Object.fromEntries(actions.map((action) => [action.id, action.action === "pass" ? 0.9 : 0.1])),
    model: "fake", promptVersion: "test", latencyMs: 1,
  }) } as any;
  const result = await decide(callable, { mode: "advisor", jev });
  assert.equal(result.selectedAction.action, "pon");
  assert.equal(result.callAssessments?.[0]?.approved, true);
  assert.equal(result.source, "jev");
});

test("Jev cannot override call certification and late top placement folds", async () => {
  const state = parseGameState({
    phase: "reaction", round: "south_4", seat: "south", turn: 13,
    scores: { east: 18000, south: 41000, west: 22000, north: 19000 },
    hand: ["P", "P", "3s", "8p", "3p", "3s", "5s", "7s", "7m", "2p", "3p", "5m", "E"],
    pendingDiscard: { tile: "P", fromSeat: "east" }, availableUiActions: ["pon", "pass"],
  });
  const jev = { chooseReaction: async (_state: unknown, actions: any[]) => ({
    actionId: actions.find((action) => action.action === "pon").id, confidence: 0.9,
    probabilities: Object.fromEntries(actions.map((action) => [action.id, action.action === "pon" ? 0.9 : 0.1])),
    model: "fake", promptVersion: "test", latencyMs: 1,
  }) } as any;
  const result = await decide(state, { mode: "advisor", jev });
  assert.equal(result.selectedAction.action, "pass");
  assert.equal(result.handPlan.phase, "late_tenpai_defense");
  assert.equal(result.handPlan.placement.rank, 1);
  assert.ok(result.callAssessments?.[0]?.reasons.includes("hand_plan_disallows_calls"));
});

test("post-riichi local, remote and deadline fallbacks use only the drawn tile", async () => {
  const live = parseGameState({ riichiDeclared: true, seat: "south",
    hand: ["1m", "1m", "1m", "5m", "6m", "7m", "3p", "4p", "4s", "4s", "0s", "5s", "5s"],
    draw: "6s",
  });
  const assertDraw = (result: Awaited<ReturnType<typeof decide>>) => {
    assert.deepEqual(result.selectedAction, { id: "discard_6s", action: "discard", tile: "6s" });
    assert.deepEqual(result.candidates.map(c => c.tile), ["6s"]);
  };
  assertDraw(await decideForceAutoWithJevDeadline(live, { deadlineMs: 1000 }));
  for (const returnedId of ["discard_6s", "discard_4p"]) {
    let offered: string[] | undefined;
    const jev = { chooseDiscard: async (_state: unknown, candidates: Array<{ tile: string }>) => {
      offered = candidates.map(c => c.tile);
      return { actionId: returnedId, confidence: 1, probabilities: { [returnedId]: 1 },
        model: "test", promptVersion: "test", latencyMs: 0 };
    } } as unknown as JevClient;
    const result = await decideForceAutoWithJevDeadline(live, { jev, deadlineMs: 1000 });
    assertDraw(result);
    assert.deepEqual(offered, ["6s"]);
    assert.equal(result.arbitration?.selectedSource, returnedId === "discard_6s" ? "jev" : "local");
  }
  const slow = { chooseDiscard: async () => new Promise(() => {}) } as unknown as JevClient;
  assertDraw(await decideForceAutoWithJevDeadline(live, { jev: slow, deadlineMs: 100 }));
});
