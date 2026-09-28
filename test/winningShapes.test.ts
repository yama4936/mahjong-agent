import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { standardWinningShapes, standardWaitShapes } from "../src/game/winningShapes.js";

test("live south-four nobetan waits complete only the pair", async () => {
  const replay = JSON.parse(await readFile("artifacts/live/south4-riichi-replay-20260928.json", "utf8"));
  const hand = [...replay.state.hand, replay.state.draw];
  hand.splice(hand.indexOf("5m"), 1);
  for (const winner of ["6m", "9m"]) {
    assert.deepEqual(standardWaitShapes(hand, winner), ["tanki"]);
    const shapes = standardWinningShapes([...hand, winner]);
    assert.equal(shapes.length, 1);
    assert.equal(shapes[0]?.pair, winner);
    assert.ok(shapes[0]?.groups.every((group) => group.type === "sequence"));
  }
});

test("standard decomposition keeps ambiguous triplet and sequence alternatives", () => {
  const shapes = standardWinningShapes(["1m", "1m", "1m", "2m", "2m", "2m", "3m", "3m", "3m", "4p", "5p", "6p", "E", "E"]);
  assert.equal(shapes.length, 2);
  assert.equal(standardWinningShapes(["1m", "2m"]).length, 0);
  assert.equal(standardWinningShapes(["1p", "2p", "3p", "4s", "0s", "6s", "E", "E"], 2).length, 1);
  assert.throws(() => standardWinningShapes([], 5), /Invalid/);
});

test("standard waits distinguish two-sided, edge, closed and paired-triplet shapes", () => {
  const base = ["1m", "2m", "3m", "E", "E"];
  assert.deepEqual(standardWaitShapes([...base, "4p", "5p"], "6p", 2), ["ryanmen"]);
  assert.deepEqual(standardWaitShapes([...base, "1p", "2p"], "3p", 2), ["penchan"]);
  assert.deepEqual(standardWaitShapes([...base, "7p", "9p"], "8p", 2), ["kanchan"]);
  assert.deepEqual(standardWaitShapes(["1m", "2m", "3m", "E", "E", "S", "S"], "E", 2), ["shanpon"]);
});
