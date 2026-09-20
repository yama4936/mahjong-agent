import assert from "node:assert/strict";
import test from "node:test";
import { cachedPublicStatePatch, type CachedPublicObservation } from "../src/agent/publicCache.js";

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
  assert.deepEqual(result.patch.visibleTiles, ["P", "P", "P"]);
  assert.equal(result.rejectedTiles, 0);
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
