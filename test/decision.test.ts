import assert from "node:assert/strict";
import test from "node:test";
import { decide, decideForceAutoWithJevDeadline } from "../src/agent/decision.js";
import { parseGameState } from "../src/game/state.js";
import { readFile } from "node:fs/promises";
import type { ClosedWaitReport } from "../src/evaluation/closedWaitScorer.js";
import type { JevClient } from "../src/jev/client.js";

const state = parseGameState({
  hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"],
  draw: "6p",
  recognitionConfidence: 1,
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
  assert.equal(failed.declarationComparison?.reason, "scorer unavailable");
  const invalid = { ...jev, chooseDeclaration: async () => choice("discard_1m") } as unknown as JevClient;
  const rejected = await decide(live, { mode: "advisor", jev: invalid, riichiScorer: async () => report });
  assert.equal(rejected.selectedAction.action, "riichi");
  assert.equal(rejected.declarationComparison?.status, "fallback");
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

test("force-auto adopts a valid Jev decision before its deadline", async () => {
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

test("force-auto falls back locally when Jev exceeds its deadline", async () => {
  const jev = { chooseDiscard: async (_state: unknown, _candidates: any[], signal: AbortSignal) => (
    new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true }))
  ) } as any;

  const result = await decideForceAutoWithJevDeadline(state, { jev, deadlineMs: 5 });

  assert.equal(result.source, "deterministic");
  assert.equal(result.arbitration?.selectedSource, "local");
  assert.equal(result.arbitration?.fallbackReason, "deadline_exceeded");
});

test("force-auto falls back locally when Jev fails", async () => {
  const jev = { chooseDiscard: async () => { throw new Error("offline"); } } as any;

  const result = await decideForceAutoWithJevDeadline(state, { jev, deadlineMs: 1_000 });

  assert.equal(result.source, "deterministic");
  assert.equal(result.arbitration?.selectedSource, "local");
  assert.equal(result.arbitration?.fallbackReason, "jev_error");
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
  assert.ok(offered.every((candidate) => (candidate.danger ?? 1) <= safest + 0.02));
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
