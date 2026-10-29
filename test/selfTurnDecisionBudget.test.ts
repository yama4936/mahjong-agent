import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { parseGameState } from "../src/game/state.js";
import type { JevClient } from "../src/jev/client.js";
import { decideSelfTurnWithinBudget, selfTurnDecisionBudget } from "../src/recognition/selfTurnDecisionBudget.js";

const fixture = JSON.parse(await readFile("test/fixtures/self-turn-reserve-overrun-20261030.json", "utf8"));
const normal = {
  clickBudgetMs: 2600, captureAgeBeforeDecisionMs: 1378, forceAutoDeadlineMs: 2300,
  processingElapsedMs: 0, actionBudgetRemainingMs: 5000, actionDeadlineRemainingMs: 290000,
  discardSelectionReserveMs: 650,
};

test("raw overruns retain IPC350 and gesture650, rather than lending Jev the gesture time", () => {
  for (const row of fixture.cases) {
    const legacy = selfTurnDecisionBudget({ ...normal, captureAgeBeforeDecisionMs: row.captureAgeBeforeDecisionMs,
      discardSelectionReserveMs: undefined });
    assert.ok(Math.abs(legacy.decisionBudgetMs - row.legacyDecisionBudgetMs) <= 1);
    const bounded = selfTurnDecisionBudget({ ...normal, captureAgeBeforeDecisionMs: row.captureAgeBeforeDecisionMs });
    assert.equal(bounded.totalReserveMs, 1000);
    assert.equal(bounded.preClickReserveMs, 350);
    assert.equal(bounded.discardSelectionReserveMs, 650);
    assert.equal(bounded.decisionBudgetMs, 1600 - row.captureAgeBeforeDecisionMs);
  }
  const first = fixture.cases[0];
  const reducedWait = first.legacyDecisionBudgetMs - selfTurnDecisionBudget(normal).decisionBudgetMs;
  assert.equal(reducedWait, 650);
  assert.equal(first.remainingBeforeClickMs + reducedWait, 893);
  assert.ok(first.remainingBeforeClickMs + reducedWait >= 650);
});

test("image, original action and global deadline each limit the same decision", () => {
  assert.equal(selfTurnDecisionBudget(normal).decisionBudgetMs, 222);
  assert.equal(selfTurnDecisionBudget({ ...normal, captureAgeBeforeDecisionMs: 100,
    actionBudgetRemainingMs: 1300 }).decisionBudgetMs, 300);
  for (const globalDeadline of [2500, 5000]) {
    const elapsedBeforeRequest = globalDeadline - 1400;
    const budget = selfTurnDecisionBudget({ ...normal, captureAgeBeforeDecisionMs: 100,
      actionDeadlineRemainingMs: globalDeadline - elapsedBeforeRequest });
    assert.equal(budget.decisionBudgetMs, 400);
  }
});

test("resident preprocessing consumes both original action and global remaining snapshots", () => {
  const budget = selfTurnDecisionBudget({ ...normal, captureAgeBeforeDecisionMs: 100,
    actionBudgetRemainingMs: 1800, actionDeadlineRemainingMs: 1500, processingElapsedMs: 250 });
  assert.equal(budget.actionBudgetRemainingMs, 1550);
  assert.equal(budget.actionDeadlineRemainingMs, 1250);
  assert.equal(budget.decisionBudgetMs, 250);
});

test("insufficient or expired original windows never start the actual Jev client path", async () => {
  const state = parseGameState(fixture.state);
  let called = 0;
  const jev = { chooseDiscard: async () => { called += 1; throw new Error("remote must not start"); } } as unknown as JevClient;
  for (const remaining of [-100, 0, 1, 649, 650, 999, 1000]) {
    const budget = selfTurnDecisionBudget({ ...normal, captureAgeBeforeDecisionMs: 100,
      actionBudgetRemainingMs: remaining });
    assert.equal(budget.decisionBudgetMs, 0);
    assert.equal(budget.remoteDecisionAllowed, false);
    const decision = await decideSelfTurnWithinBudget(state, budget, { jev });
    assert.equal(decision.arbitration?.selectedSource, "local");
    assert.equal(decision.selectedAction.action, "discard");
    assert.equal(decision.selectedAction.tile, "1s");
  }
  assert.equal(called, 0);
});

test("immediate local tsumo and ron remain available without remote waiting", async () => {
  const hand = ["1m", "2m", "3m", "4m", "5m", "6m", "1p", "2p", "3p", "7s", "8s", "9s", "E"];
  const budget = selfTurnDecisionBudget({ ...normal, actionBudgetRemainingMs: 600 });
  const jev = { chooseDiscard: async () => { throw new Error("no remote"); },
    chooseReaction: async () => { throw new Error("no remote"); } } as unknown as JevClient;
  const tsumo = parseGameState({ hand, draw: "E", availableUiActions: ["tsumo"] });
  assert.equal((await decideSelfTurnWithinBudget(tsumo, budget, { jev })).selectedAction.action, "tsumo");
  const ron = parseGameState({ hand, seat: "south", phase: "reaction",
    pendingDiscard: { tile: "E", fromSeat: "east" }, availableUiActions: ["ron", "pass"] });
  assert.equal((await decideSelfTurnWithinBudget(ron, budget, { jev })).selectedAction.action, "ron");
});

test("a valid original window still allows Jev, and the environment cap remains binding", async (t) => {
  t.mock.method(performance, "now", () => 0);
  const budget = selfTurnDecisionBudget({ ...normal, forceAutoDeadlineMs: 100 });
  assert.equal(budget.decisionBudgetMs, 100);
  let called = 0;
  const jev = { chooseDiscard: async (_state: unknown, candidates: Array<{ actionId: string }>) => {
    called += 1;
    return { actionId: candidates[0]!.actionId, confidence: .95,
      probabilities: { [candidates[0]!.actionId]: 1 }, model: "fake", promptVersion: "test", latencyMs: 1 };
  } } as unknown as JevClient;
  await decideSelfTurnWithinBudget(parseGameState(fixture.state), budget, { jev });
  assert.equal(called, 1);
  const fractional = await decideSelfTurnWithinBudget(parseGameState(fixture.state),
    selfTurnDecisionBudget({ ...normal, forceAutoDeadlineMs: .5 }), { jev });
  assert.equal(fractional.arbitration?.deadlineMs, .5);
  assert.equal(called, 2);
});

test("unknown invalid bounded timing is rejected, while legacy requests keep 350ms semantics", () => {
  for (const invalid of [NaN, Infinity, undefined]) {
    assert.throws(() => selfTurnDecisionBudget({ ...normal, actionBudgetRemainingMs: invalid }));
    assert.throws(() => selfTurnDecisionBudget({ ...normal, actionDeadlineRemainingMs: invalid }));
  }
  assert.throws(() => selfTurnDecisionBudget({ ...normal, discardSelectionReserveMs: 649 }));
  assert.throws(() => selfTurnDecisionBudget({ ...normal, processingElapsedMs: -1 }));
  const legacy = selfTurnDecisionBudget({ ...normal, discardSelectionReserveMs: undefined,
    actionBudgetRemainingMs: undefined, captureAgeBeforeDecisionMs: 5000 });
  assert.equal(legacy.preClickReserveMs, 350);
  assert.equal(legacy.totalReserveMs, 350);
  assert.equal(legacy.decisionBudgetMs, 1);
  assert.equal(legacy.remoteDecisionAllowed, true);
  assert.equal(selfTurnDecisionBudget({ ...normal, forceAutoDeadlineMs: .5,
    discardSelectionReserveMs: undefined }).decisionBudgetMs, .5);
  assert.equal(selfTurnDecisionBudget({ ...normal, forceAutoDeadlineMs: .5 }).decisionBudgetMs, .5);
});

test("resident server wires explicit gesture/original budgets but preserves ordinary staging", { timeout: 60000 }, async () => {
  const child = spawn(process.execPath, ["--import", "tsx", "src/recognition/recognitionServer.ts",
    "config/layout.json", "templates/bootstrap", "examples/public-unknown.json"], {
    stdio: ["pipe", "pipe", "pipe"], env: { ...process.env, TYPESAFE_API_KEY: "",
      FORCE_AUTO_CLICK_BUDGET_MS: "2600", JEV_FORCE_AUTO_DEADLINE_MS: "2300" },
  });
  const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  const read = async () => JSON.parse((await lines.next()).value!);
  const screenshot = "artifacts/live/cached-hand-drift-20260928.jpg";
  try {
    assert.equal((await read()).ready, true);
    child.stdin.write(JSON.stringify({ id: 1, screenshot, stageForceAutoRecognition: true }) + "\n");
    const first = await read();
    assert.equal(typeof first.result.recognitionId, "string");
    child.stdin.write(JSON.stringify({ id: 2, screenshot, evaluateForceAuto: true,
      forceAutoRecognitionId: first.result.recognitionId, frameCapturedAtMs: Date.now(),
      discardSelectionReserveMs: 650, actionBudgetRemainingMs: 650, actionDeadlineRemainingMs: 5000 }) + "\n");
    const response = await read();
    assert.equal(response.error, undefined);
    assert.equal(response.result.turnTiming.totalReserveMs, 1000);
    assert.equal(response.result.turnTiming.decisionBudgetMs, 0);
    assert.equal(response.result.turnTiming.remoteDecisionAllowed, false);
    assert.ok(response.result.turnTiming.actionBudgetRemainingMs < 650);
    assert.ok(response.result.turnTiming.actionDeadlineRemainingMs < 5000);
    assert.equal(response.result.decision.arbitration.selectedSource, "local");
    child.stdin.write(JSON.stringify({ id: 3, screenshot, stageForceAutoRecognition: true,
      discardSelectionReserveMs: 650 }) + "\n");
    assert.equal(typeof (await read()).result.recognitionId, "string");
  } finally {
    child.stdin.end();
    child.kill();
  }
});
