import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { decide } from "../src/agent/decision.js";
import { parseGameState } from "../src/game/state.js";
import { appendDecisionLog, attachActualResult, readDecisionDataset, readDecisionLog } from "../src/logging/replay.js";
import { summarizeBenchmark } from "../src/logging/benchmark.js";

test("decision logs round-trip through JSONL", async () => {
  const directory = await mkdtemp(path.join(tmpdir(), "jantama-replay-"));
  const state = parseGameState({
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"],
    draw: "6p",
  });
  const decision = await decide(state, { mode: "advisor" });
  const written = await appendDecisionLog(directory, state, decision, "frame.png");
  const records = await readDecisionLog(path.join(directory, "decisions.jsonl"));
  assert.equal(records.length, 1);
  assert.equal(records[0]!.id, written.id);
  assert.equal(records[0]!.decision.tile, "E");
  assert.match(await readFile(path.join(directory, `${written.id}.json`), "utf8"), /frame\.png/);
});

test("actual outcomes can be attached and benchmarked", async () => {
  const directory = await mkdtemp(path.join(tmpdir(), "jantama-outcome-"));
  const state = parseGameState({
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"],
    draw: "6p",
  });
  const decision = await decide(state, { mode: "advisor" });
  const record = await appendDecisionLog(directory, state, decision);
  await attachActualResult(path.join(directory, `${record.id}.json`), { won: true, dealIn: false, pointsDelta: 5200, finalRank: 1 });
  const summary = summarizeBenchmark(await readDecisionDataset(directory));
  assert.equal(summary.overall.decisions, 1);
  assert.equal(summary.overall.winRate, 1);
  assert.equal(summary.overall.dealInRate, 0);
  assert.equal(summary.overall.averagePointsDelta, 5200);
  assert.equal(summary.overall.averageFinalRank, 1);
});
