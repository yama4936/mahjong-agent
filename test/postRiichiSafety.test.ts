import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { decide } from "../src/agent/decision.js";
import { evaluateTileDanger } from "../src/evaluation/defense.js";
import { knownTiles, parseGameState } from "../src/game/state.js";
import { opponentStatesFromObservation } from "../src/recognition/publicTileRecognizer.js";
import { buildJevRequest, buildJevReactionRequest, buildJevDeclarationRequest } from "../src/jev/client.js";
import type { ClosedWaitReport } from "../src/evaluation/closedWaitScorer.js";

async function liveStates() {
  const fixture = JSON.parse(await readFile("test/fixtures/post-riichi-passed-tile-20261021.json", "utf8"));
  const before = parseGameState(fixture.followingDecision.state);
  const marked = parseGameState({ ...before, opponents: before.opponents.map((opponent) =>
    opponent.seat === "south" ? { ...opponent, postRiichiSafeTiles: ["1s"] } : opponent) });
  return { before, marked };
}

test("post-riichi safety applies only to its riichi opponent and never adds physical tiles", async () => {
  const { before, marked } = await liveStates();
  assert.deepEqual(knownTiles(marked), knownTiles(before));
  const prior = evaluateTileDanger("1s", before);
  const after = evaluateTileDanger("1s", marked);
  assert.ok(prior.byOpponent.find((opponent) => opponent.seat === "south")!.probability > 0);
  assert.deepEqual(after.byOpponent.find((opponent) => opponent.seat === "south"),
    { seat: "south", probability: 0, reasons: ["post_riichi_passed"] });
  assert.deepEqual(after.byOpponent.filter((opponent) => opponent.seat !== "south"),
    prior.byOpponent.filter((opponent) => opponent.seat !== "south"));
  const notRiichi = parseGameState({ ...marked, opponents: marked.opponents.map((opponent) =>
    ({ ...opponent, riichi: false })) });
  assert.ok(evaluateTileDanger("1s", notRiichi).byOpponent.find((opponent) => opponent.seat === "south")!.probability > 0);
  const red = parseGameState({ ...marked, opponents: marked.opponents.map((opponent) =>
    opponent.seat === "south" ? { ...opponent, postRiichiSafeTiles: ["0p"] } : opponent) });
  for (const tile of ["0p", "5p"]) {
    assert.equal(evaluateTileDanger(tile, red).byOpponent.find((opponent) => opponent.seat === "south")!.probability, 0);
  }
});

test("actual passed1s history excludes the observed3m deal-in from the existing danger filter", async () => {
  const { before, marked } = await liveStates();
  let offered: string[] = [];
  const jev = { chooseDiscard: async (_state: unknown, candidates: Array<{ actionId: string }>) => {
    offered = candidates.map((candidate) => candidate.actionId);
    const selected = candidates.find((candidate) => candidate.actionId === "discard_3m") ?? candidates[0]!;
    return { actionId: selected.actionId, confidence: 0.9, probabilities: { [selected.actionId]: 1 },
      model: "fake", promptVersion: "test", latencyMs: 1 };
  } } as any;
  const prior = await decide(before, { mode: "force-auto", jev });
  assert.ok(offered.includes("discard_3m"));
  assert.equal(prior.tile, "3m");
  const corrected = await decide(marked, { mode: "force-auto", jev });
  assert.deepEqual(offered, ["discard_1s"]);
  assert.equal(corrected.tile, "1s");
  assert.equal(corrected.candidates.find((candidate) => candidate.tile === "1s")!.shanten, 2);
});

test("observation merge and all Jev contexts preserve passed safety without replacing the river", async () => {
  const { marked } = await liveStates();
  const observation = { opponentDiscards: marked.opponents.map((opponent) => ({
    seat: opponent.seat, discards: [...opponent.discards], riichiDeclared: opponent.riichi,
    melds: opponent.melds ?? [], meldsObserved: opponent.openMeldsObserved,
  })) } as any;
  const merged = parseGameState({ ...marked, opponents: opponentStatesFromObservation(observation, marked.opponents) });
  assert.deepEqual(merged.opponents.find((opponent) => opponent.seat === "south")!.postRiichiSafeTiles, ["1s"]);
  assert.deepEqual(knownTiles(merged), knownTiles(marked));
  const result = await decide(merged, { mode: "force-auto" });
  const report: ClosedWaitReport = { library: "mahjong==2.0.0", discard: "1s",
    scope: "closed_hand_scoring_not_policy_ev", assumptions: { furiten_not_checked: true }, rows: [] };
  for (const request of [
    buildJevRequest(merged, result.candidates, "test", "hierarchical-v3"),
    buildJevReactionRequest({ ...merged, pendingDiscard: { tile: "1s", fromSeat: "east" } },
      [{ id: "pass", action: "pass" }], "test"),
    buildJevDeclarationRequest(merged, [
      { id: "discard_1s", action: "discard", tile: "1s" },
      { id: "riichi_discard_1s", action: "riichi", tile: "1s" },
    ], report, "test"),
  ]) {
    const opponents = request.state.opponents as typeof merged.opponents;
    const opponent = opponents.find((item) => item.seat === "south")!;
    assert.deepEqual(opponent.postRiichiSafeTiles, ["1s"]);
    assert.deepEqual(opponent.discards, marked.opponents.find((item) => item.seat === "south")!.discards);
  }
});
