import { test } from "node:test";
import assert from "node:assert/strict";
import { inspectSanmaKitaReplacementShapes } from "../src/game/sanmaKitaShapeExperiment.js";

const hand = ["1p","2p","3p","4p","5p","6p","1s","2s","3s","4s","5s","E","E","N"];
const input = { hand, knownOutsideHand: [], ownMelds: [] };

test("north extraction branches retain a completed replacement shape without recommending a discard", () => {
  const result = inspectSanmaKitaReplacementShapes(input);
  assert.equal(result.operationAuthorized, false);
  const win = result.outcomes.find(row => row.replacement === "6s")!;
  assert.equal(win.completedShape, true);
  assert.equal(win.bestShantenAfterDiscard, 0);
  assert.equal(win.unaccountedCopies, 4);
  assert.equal(result.outcomes.find(row => row.replacement === "N")?.unaccountedCopies, 3);
  assert.ok(result.outcomes.every(row => !/^[2-8]m$/.test(row.replacement)));
});

test("visible copies, including previously extracted north, reduce branch inventory", () => {
  const result = inspectSanmaKitaReplacementShapes({ ...input, knownOutsideHand: ["N", "6s", "6s", "6s", "6s"] });
  assert.equal(result.outcomes.find(row => row.replacement === "N")?.unaccountedCopies, 2);
  assert.equal(result.outcomes.some(row => row.replacement === "6s"), false);
});

test("red and ordinary fives produce identical shape classes", () => {
  const result = inspectSanmaKitaReplacementShapes({ ...input, hand: hand.map(t => t === "5p" ? "0p" : t) });
  assert.equal(result.outcomes.filter(row => row.replacement === "5p").length, 1);
  assert.deepEqual(result.outcomes, inspectSanmaKitaReplacementShapes(input).outcomes);
});

test("invalid or physically impossible inventories fail closed", () => {
  assert.throws(() => inspectSanmaKitaReplacementShapes({ ...input, hand: hand.map(t => t === "N" ? "2m" : t) }), /unavailable/);
  assert.throws(() => inspectSanmaKitaReplacementShapes({ ...input, hand: hand.map(t => t === "N" ? "S" : t) }), /north/);
  assert.throws(() => inspectSanmaKitaReplacementShapes({ ...input, knownOutsideHand: ["N", "N", "N", "N"] }));
  assert.throws(() => inspectSanmaKitaReplacementShapes({ ...input, hand: hand.slice(1) }), /inventory/);
});

test("open meld inventory reduces the number of concealed tiles and observed copies", () => {
  const result = inspectSanmaKitaReplacementShapes({
    hand: ["1p", "2p", "3p", "1s", "2s", "3s", "4s", "5s", "E", "E", "N"],
    knownOutsideHand: [], ownMelds: [["7s", "7s", "7s"]],
  });
  assert.equal(result.outcomes.find(row => row.replacement === "6s")?.completedShape, true);
  assert.equal(result.outcomes.find(row => row.replacement === "7s")?.unaccountedCopies, 1);
});


test("missing, malformed and double-counted own melds are rejected", () => {
  const reducedHand = ["1p", "2p", "3p", "1s", "2s", "3s", "4s", "5s", "E", "E", "N"];
  assert.throws(() => inspectSanmaKitaReplacementShapes({ hand: reducedHand, knownOutsideHand: [], ownMelds: [] }), /inventory/);
  assert.throws(() => inspectSanmaKitaReplacementShapes({ hand: reducedHand, knownOutsideHand: [], ownMelds: [["7s", "8s", "9s"]] }), /meld/);
  assert.throws(() => inspectSanmaKitaReplacementShapes({ hand: reducedHand, knownOutsideHand: ["7s", "7s"], ownMelds: [["7s", "7s", "7s"]] }));
  assert.equal(inspectSanmaKitaReplacementShapes(input).inventoryCompleteness, "unverified");
});
