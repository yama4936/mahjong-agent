import assert from "node:assert/strict";
import test from "node:test";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { parseGameState } from "../src/game/state.js";
import { scoreClosedWaits } from "../src/evaluation/closedWaitScorer.js";

const python = path.resolve(".runtime/scoring-venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
async function liveState() {
  return parseGameState(JSON.parse(await readFile("artifacts/live/south4-riichi-replay-20260928.json", "utf8")).state);
}

test("bounded scoring bridge verifies live no-yaku dama without changing state", { skip: !existsSync(python) }, async () => {
  const state = await liveState();
  const original = JSON.stringify(state);
  const report = await scoreClosedWaits(state, "5m", ["6m", "9m"], { timeoutMs: 3000 });
  assert.equal(report.rows.length, 8);
  assert.equal(report.rows[0]?.error, "no_yaku");
  assert.equal(report.rows[3]?.cost?.total, 3000);
  assert.equal(JSON.stringify(state), original);
  await assert.rejects(scoreClosedWaits(state, "5m", ["6m"], { timeoutMs: 1 }), /deadline/);
});

test("scorer abort and missing runtime fail explicitly", async () => {
  const state = await liveState();
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(scoreClosedWaits(state, "5m", ["6m"], { signal: controller.signal }), /aborted/);
  await assert.rejects(scoreClosedWaits(state, "5m", ["6m"], { python: path.resolve(".runtime/missing-scorer.exe") }));
  assert.throws(() => scoreClosedWaits(state, "5m", ["6m", "6m"]), /Unique/);
});
