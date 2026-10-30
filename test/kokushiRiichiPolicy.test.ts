import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { decide, decideForceAutoWithJevDeadline } from "../src/agent/decision.js";
import { parseGameState, type GameState } from "../src/game/state.js";
import { calculateShanten } from "../src/game/shanten.js";
import { TILE_NAMES, isTerminalOrHonor } from "../src/game/tiles.js";
import type { JevClient } from "../src/jev/client.js";
import type { ClosedWaitReport } from "../src/evaluation/closedWaitScorer.js";

const fixture = JSON.parse(readFileSync("test/fixtures/kokushi-no-added-riichi-76a2864-20261030.json", "utf8"));
const live = parseGameState(fixture.state);
const report = fixture.original.declarationComparison.report as ClosedWaitReport;
const choice = (actionId: string, confidence = .99) => ({ actionId, confidence, probabilities: { [actionId]: 1 },
  model: "offline-test-stub", promptVersion: "test", latencyMs: 0 });

function quietJev(discard: string, onCandidates?: (candidates: any[]) => void) {
  let declarationCalls = 0;
  const jev = {
    chooseDiscard: async (_state: unknown, candidates: any[]) => {
      onCandidates?.(candidates);
      return choice(`discard_${discard}`);
    },
    chooseDeclaration: async () => { declarationCalls++; return choice(`riichi_discard_${discard}`, .14); },
  } as unknown as JevClient;
  return { jev, declarationCalls: () => declarationCalls };
}

test("actual 51 kokushi keeps selected 3p discard, legal riichi and explicit scoped policy evidence", async () => {
  assert.equal(fixture.sourceLine, 51);
  assert.equal(fixture.original.selectedAction.action, "riichi");
  assert.equal(fixture.original.declarationComparison.status, "fallback");
  assert.equal(fixture.original.declarationComparison.decision.confidence, .14);
  assert.deepEqual(report.rows.map(row => row.cost?.total), [32000, 32000, 32000, 32000]);
  const result = await decide(live, { mode: "force-auto" });
  assert.deepEqual(result.selectedAction, { id: "discard_3p", action: "discard", tile: "3p" });
  assert.ok(result.legalActions.some(action => action.id === "riichi_discard_3p"));
  assert.deepEqual(result.riichiAssessment?.reasons, ["kokushi_no_riichi_scoring_gain"]);
  assert.equal(result.riichiAssessment?.approved, false);
  assert.deepEqual(result.riichiAssessment?.kokushiPolicy, {
    scope: "natural_kokushi_scoring_only_not_ev_dominance",
    policy: "keep_same_tile_dama_without_riichi_scoring_gain", discardTile: "3p", postDiscardCount: 13,
    structuralWaits: ["9s"],
  });
  // Correcting the separate heuristic-value defect is deliberately out of scope.
  assert.equal(result.candidates.find(candidate => candidate.tile === "3p")?.estimatedValue, 2000);
  assert.equal(result.declarationComparison, undefined);
});

test("Jev still receives original preselection scoring; low-confidence declaration cannot restore riichi", async () => {
  let scorerCalls = 0;
  let offered: any[] = [];
  const stub = quietJev("3p", candidates => { offered = candidates; });
  const result = await decide(live, { mode: "force-auto", jev: stub.jev,
    riichiScorer: async () => { scorerCalls++; return report; } });
  assert.equal(result.source, "jev");
  assert.equal(result.selectedAction.id, "discard_3p");
  assert.equal(scorerCalls, 1);
  assert.equal(offered.find(candidate => candidate.tile === "3p")?.closedWaitScore, report);
  assert.deepEqual(offered.map(({ closedWaitScore: _report, ...candidate }) => candidate),
    result.candidates.filter(candidate => candidate.shanten === 0));
  assert.equal(stub.declarationCalls(), 0);
  assert.ok(result.riichiAssessment?.kokushiPolicy);
});

test("structural kokushi policy is independent of unavailable preselection scoring", async () => {
  const stub = quietJev("3p");
  let attempts = 0;
  const result = await decide(live, { mode: "force-auto", jev: stub.jev,
    riichiScorer: async () => { attempts++; throw new Error("scoring unavailable"); } });
  assert.equal(attempts, 1);
  assert.equal(result.selectedAction.id, "discard_3p");
  assert.equal(stub.declarationCalls(), 0);
  assert.equal(result.riichiAssessment?.kokushiPolicy?.structuralWaits[0], "9s");
});

test("local force-auto deadline fallback retains the same scoped kokushi policy", async () => {
  const result = await decideForceAutoWithJevDeadline(live, {});
  assert.equal(result.selectedAction.id, "discard_3p");
  assert.equal(result.arbitration?.selectedSource, "local");
  assert.ok(result.riichiAssessment?.reasons.includes("kokushi_no_riichi_scoring_gain"));
  let remoteCalls = 0;
  const expired = await decideForceAutoWithJevDeadline(live, { deadlineMs: .000001,
    jev: { chooseDiscard: async () => { remoteCalls++; throw new Error("should not start"); } } as unknown as JevClient });
  assert.equal(expired.arbitration?.fallbackReason, "deadline_exceeded");
  assert.equal(expired.selectedAction.id, "discard_3p");
  assert.equal(remoteCalls, 0);
});

test("thirteen-sided kokushi is structurally verified without assuming a double-yakuman rule", async () => {
  const orphans = TILE_NAMES.filter((_, index) => isTerminalOrHonor(index));
  for (const draw of ["3p", "0p"]) {
    const state = parseGameState({ ...live, hand: orphans, draw, ownDiscards: [], opponents: [],
      doraIndicators: [], turn: 4 });
    const result = await decide(state, { mode: "force-auto" });
    assert.equal(result.selectedAction.id, `discard_${draw}`);
    assert.equal(result.riichiAssessment?.kokushiPolicy?.discardTile, draw);
    assert.deepEqual(result.riichiAssessment?.kokushiPolicy?.structuralWaits, orphans);
    for (const tile of result.riichiAssessment!.kokushiPolicy!.structuralWaits) {
      assert.equal(calculateShanten([...orphans, tile]).kokushi, -1);
    }
  }
});

test("kokushi immediate tsumo and ron keep priority over declaration policy", async () => {
  const hand = [...live.hand, live.draw!];
  hand.splice(hand.indexOf("3p"), 1);
  const tsumo = await decide(parseGameState({ ...live, hand, draw: "9s" }), { mode: "force-auto" });
  assert.equal(tsumo.selectedAction.action, "tsumo");
  assert.equal(tsumo.riichiAssessment?.kokushiPolicy, undefined);
  const { draw: _draw, ...withoutDraw } = live;
  const ron = await decide(parseGameState({ ...withoutDraw, phase: "reaction", hand,
    pendingDiscard: { tile: "9s", fromSeat: "east" }, availableUiActions: ["ron", "pass"] }), { mode: "force-auto" });
  assert.equal(ron.selectedAction.action, "ron");
});

test("already-declared kokushi remains locked to the current draw, not converted to dama", async () => {
  const hand = [...live.hand, live.draw!];
  hand.splice(hand.indexOf("3p"), 1);
  const locked = await decide(parseGameState({ ...live, hand, draw: "0p", riichiDeclared: true }), { mode: "force-auto" });
  assert.equal(locked.selectedAction.id, "discard_0p");
  assert.equal(locked.riichiAssessment, undefined);
});

test("ordinary no-yaku dama and mangan hands preserve low-confidence/scorer-failure riichi fallback", async () => {
  const ordinary = parseGameState({ round: "east_2", seat: "north", scores: { north: 22500 }, turn: 5,
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "1p", "2p", "3p", "4s", "5s", "6s", "E"],
    draw: "9p", availableUiActions: ["riichi"], remainingTiles: 46, doraIndicators: [] });
  for (const scoring of (['failure', 'normal_mangan'] as const)) {
    const stub = quietJev("9p");
    const result = await decide(ordinary, { mode: "force-auto", jev: stub.jev,
      riichiScorer: async () => {
        if (scoring === "failure") throw new Error("unavailable");
        return { ...report, discard: "9p", rows: report.rows.map(row => ({ ...row,
          wait: "E", han: 4, fu: 40, yaku: ["Riichi", "Dora"], cost: { total: 8000 } })) };
      } });
    assert.equal(result.selectedAction.id, "riichi_discard_9p");
    assert.equal(result.riichiAssessment?.kokushiPolicy, undefined);
    assert.equal(result.declarationComparison?.status, "fallback");
  }
});

test("simple-tile, open and non-tenpai shapes cannot gain kokushi policy evidence", async () => {
  const cases: GameState[] = [
    parseGameState({ ...live, hand: live.hand.map(tile => tile === "F" ? "4p" : tile) }),
    parseGameState({ ...live, hand: live.hand.slice(0, 10), openMelds: 1,
      melds: [{ type: "chi", tiles: ["2m", "3m", "4m"] }] }),
    parseGameState({ ...live, hand: live.hand.slice(0, 10), openMelds: 1,
      melds: [{ type: "ankan", tiles: ["F", "F", "F", "F"] }] }),
  ];
  for (const state of cases) {
    const result = await decide(state, { mode: "force-auto" });
    assert.equal(result.riichiAssessment?.kokushiPolicy, undefined);
  }
});

test("wall/dead-wait restrictions and absent legal declaration are unchanged", async () => {
  const late = await decide(parseGameState({ ...live, remainingTiles: 3 }), { mode: "force-auto" });
  assert.equal(late.selectedAction.id, "discard_3p");
  assert.equal(late.riichiAssessment?.kokushiPolicy, undefined);
  assert.ok(late.riichiAssessment?.reasons.includes("insufficient_wall_for_riichi"));
  const dead = await decide(parseGameState({ ...live, visibleTiles: ["9s", "9s", "9s", "9s"] }), { mode: "force-auto" });
  assert.equal(dead.riichiAssessment?.kokushiPolicy, undefined);
  assert.ok(dead.riichiAssessment?.reasons.includes("no_remaining_winning_tiles"));
  const absent = await decide(parseGameState({ ...live, availableUiActions: [] }), { mode: "force-auto" });
  assert.equal(absent.riichiAssessment, undefined);
});
