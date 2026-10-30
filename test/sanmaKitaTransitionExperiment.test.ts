import { test } from "node:test";
import assert from "node:assert/strict";
import { inspectKitaTransition, type KitaObservation } from "../src/game/sanmaKitaTransitionExperiment.js";
const before: KitaObservation = { frameSha256: "a".repeat(64), atMs: 1, roundId: "E1", meldCount: 0, ownKitaCount: 0, wallRemaining: 52,
  hand: ["1m","9m","9m","4p","0p","5p","6p","8p","2s","6s","S","S","N","E"], drawn: "E" };
const after: KitaObservation = { ...before, frameSha256: "b".repeat(64), atMs: 3, ownKitaCount: 1, wallRemaining: 51,
  hand: ["1m","9m","9m","4p","0p","5p","6p","8p","2s","6s","E","S","S","4s"], drawn: "4s" };
test("manual E1 screen observations match extraction plus replacement", () => {
  const result = inspectKitaTransition(before, after, 2);
  assert.equal(result.status, "consistent_candidate");
  assert.equal(result.operationAuthorized, false);
});
test("replacement north can preserve hand multiset and keep kita button present", () => {
  const hand = ["2p","6p","7p","7p","8p","3s","6s","S","W","N","N","P","C","5p"];
  const b = { ...before, roundId: "E2-1", wallRemaining: 53, hand, drawn: "5p" };
  const a = { ...after, roundId: "E2-1", wallRemaining: 52, hand, drawn: "N" };
  assert.equal(inspectKitaTransition(b, a, 2).status, "consistent_candidate");
  assert.equal(inspectKitaTransition(b, { ...a, ownKitaCount: 0 }, 2).status, "unresolved");
});
test("missing north increment, wrong draw, stale or invalid observations are rejected", () => {
  for (const modified of [
    { ...after, ownKitaCount: 0 }, { ...after, wallRemaining: 52 }, { ...after, roundId: "E2" },
    { ...after, drawn: "S" }, { ...after, frameSha256: before.frameSha256 }, { ...after, atMs: 2 },
    { ...after, hand: [...after.hand.slice(0, -1), "2m"] }, { ...after, ownKitaCount: 5 },
  ]) assert.equal(inspectKitaTransition(before, modified, 2).status, "unresolved");
});
