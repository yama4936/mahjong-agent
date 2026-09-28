import assert from "node:assert/strict";
import test from "node:test";
import { cachedPublicStatePatch, type CachedPublicObservation } from "../src/agent/publicCache.js";
import { knownTiles, parseGameState } from "../src/game/state.js";

test("cached public observations add dora, rivers, riichi and meld counts", () => {
  const observation: CachedPublicObservation = {
    doraIndicators: ["4m"], ownDiscards: ["1p"], ownRiichiDeclared: false, ownMelds: [],
    opponentDiscards: [
      { seat: "south", discards: ["E"], riichiDeclared: true, melds: [] },
      { seat: "west", discards: ["2s"], melds: [{ type: "pon", tiles: ["P", "P", "P"], confidence: 0.9 }] },
      { seat: "north", discards: [], melds: [] },
    ],
    ownMeldTiles: [], allMeldTiles: ["P", "P", "P"], otherVisibleTiles: ["E", "2s", "P", "P", "P"],
    acceptedTiles: 6, detectedCandidates: 6, complete: false,
    capturedAt: new Date().toISOString(), recognizedAt: new Date().toISOString(), recognitionLatencyMs: 350,
    configuredRegions: ["doraIndicators", "ownDiscards", "rightDiscards"],
  };

  const result = cachedPublicStatePatch(observation, ["1m", "2m"]);

  assert.deepEqual(result.patch.doraIndicators, ["4m"]);
  assert.deepEqual(result.patch.ownDiscards, ["1p"]);
  assert.equal((result.patch.opponents as any[])[0].riichi, true);
  assert.equal((result.patch.opponents as any[])[1].openMelds, 1);
  assert.deepEqual(result.patch.visibleTiles, []);
  assert.deepEqual((result.patch.opponents as any[])[1].melds[0].tiles, ["P", "P", "P"]);
  assert.equal((result.patch.opponents as any[])[1].openMeldsObserved, false);
  assert.equal(result.rejectedTiles, 0);
});

test("cached melds reject impossible groups atomically and keep unknown evidence explicit", () => {
  const observation = {
    doraIndicators: [], ownDiscards: [], opponentDiscards: [
      { seat: "south", discards: [], meldsObserved: true, melds: [{ type: "pon", tiles: ["P", "P", "P"] }] },
      { seat: "west", discards: [], meldsObserved: false, melds: [] },
    ], ownMeldTiles: [],
  } as unknown as CachedPublicObservation;
  const rejected = cachedPublicStatePatch(observation, ["P", "P"]);
  const opponent = (rejected.patch.opponents as any[])[0];
  assert.deepEqual(opponent.melds, []);
  assert.equal(opponent.openMelds, 1);
  assert.equal(opponent.openMeldsObserved, false);
  assert.equal(rejected.rejectedTiles, 3);
  const accepted = cachedPublicStatePatch(observation, []);
  assert.equal((accepted.patch.opponents as any[])[0].openMeldsObserved, true);
  assert.equal((accepted.patch.opponents as any[])[0].melds.length, 1);
  assert.equal((accepted.patch.opponents as any[])[1].openMeldsObserved, false);
});

test("cached public observations discard impossible fifth visible copies", () => {
  const observation = {
    doraIndicators: ["1m"], ownDiscards: ["1m", "1m", "1m", "1m"], opponentDiscards: [],
    ownMeldTiles: [], otherVisibleTiles: [], acceptedTiles: 5, detectedCandidates: 5, complete: false,
    capturedAt: new Date().toISOString(), recognizedAt: new Date().toISOString(), recognitionLatencyMs: 350,
    configuredRegions: ["doraIndicators", "ownDiscards"],
  } as CachedPublicObservation;

  const result = cachedPublicStatePatch(observation, []);

  assert.deepEqual(result.patch.doraIndicators, ["1m"]);
  assert.deepEqual(result.patch.ownDiscards, ["1m", "1m", "1m"]);
  assert.equal(result.rejectedTiles, 1);
});

test("complete own pon reaches typed game state without duplicate visible tiles", () => {
  const observation = { doraIndicators: ["1p"], ownDiscards: [], opponentDiscards: [],
    ownMelds: [{ type: "pon", tiles: ["F", "F", "F"], confidence: 0.98675 }],
    ownMeldTiles: ["F", "F", "F"] } as unknown as CachedPublicObservation;
  const concealed = ["1m", "2m", "3m", "3s", "4s", "6s", "6s", "6s", "S", "S", "2p"];
  const result = cachedPublicStatePatch(observation, concealed, [], 1);
  const state = parseGameState({ ...result.patch, openMelds: 1, hand: concealed.slice(0, -1), draw: concealed.at(-1) });
  assert.deepEqual(state.melds, [{ type: "pon", tiles: ["F", "F", "F"] }]);
  assert.deepEqual(state.visibleTiles, []);
  assert.equal(knownTiles(state).filter(tile => tile === "F").length, 3);
  assert.equal(result.rejectedTiles, 0);
  for (const count of [0, 2]) {
    assert.deepEqual(cachedPublicStatePatch(observation, concealed, [], count).patch.melds, []);
  }
  const partial = { ...observation, ownMeldTiles: ["F", "F"] } as CachedPublicObservation;
  assert.deepEqual(cachedPublicStatePatch(partial, concealed, [], 1).patch.melds, []);
  const conflict = cachedPublicStatePatch(observation, [...concealed, "F", "F"], [], 1);
  assert.deepEqual(conflict.patch.melds, []);
  assert.equal(conflict.rejectedTiles, 1);
});
