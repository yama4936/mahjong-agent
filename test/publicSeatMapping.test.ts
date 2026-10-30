import { test } from "node:test";
import assert from "node:assert/strict";
import { mapPublicOpponentPositions } from "../src/recognition/publicSeatMapping.js";

test("three observed sanma winds map the two occupied positions", () => {
  const positions = { opposite: "upper", left: "left" };
  assert.deepEqual(mapPublicOpponentPositions("west", positions, "sanma"), { east: "upper", south: "left" });
  assert.deepEqual(mapPublicOpponentPositions("south", positions, "sanma"), { west: "upper", east: "left" });
  assert.deepEqual(mapPublicOpponentPositions("east", positions, "sanma"), { south: "upper", west: "left" });
});

test("default yonma retains clockwise right/opposite/left assignment", () => {
  const positions = { right: 1, opposite: 2, left: 3 };
  assert.deepEqual(mapPublicOpponentPositions("west", positions), { north: 1, east: 2, south: 3 });
  assert.deepEqual(mapPublicOpponentPositions("west", positions, "yonma"), { north: 1, east: 2, south: 3 });
});

test("sanma rejects nonexistent right, invalid own seat and missing evidence", () => {
  assert.throws(() => mapPublicOpponentPositions("east", { right: 3, opposite: 1, left: 2 }, "sanma"));
  assert.throws(() => mapPublicOpponentPositions("east", { right: undefined, opposite: 1, left: 2 }, "sanma"));
  assert.throws(() => mapPublicOpponentPositions("north", { opposite: 1, left: 2 }, "sanma"));
  assert.throws(() => mapPublicOpponentPositions("east", { left: 2 }, "sanma"));
  assert.throws(() => mapPublicOpponentPositions("east", { right: 1, left: 2 }));
});
