import { test } from "node:test";
import assert from "node:assert/strict";
import { generateLegalActions } from "../src/game/actions.js";
import { knownTiles, knownTilesOutsideHand, parseGameState, parsePublicGameState } from "../src/game/state.js";
import { tileIndex, toCounts } from "../src/game/tiles.js";

const hand = ["1m", "9m", "1p", "2p", "3p", "4p", "5p", "6p", "1s", "2s", "3s", "E", "E", "N"];
const base = { rules: "sanma", hand, ownKitaCount: 1,
  opponents: [{ seat: "south", kitaCount: 1 }, { seat: "west", kitaCount: 1 }] };
const norths = (tiles: readonly string[]) => toCounts(tiles)[tileIndex("N")];

test("own and opponent extracted norths are counted once, outside hand and melds", () => {
  const state = parseGameState(base);
  assert.equal(state.ownKitaCount, 1);
  assert.equal(state.opponents[0]?.kitaCount, 1);
  assert.equal(state.opponents[1]?.kitaCount, 1);
  assert.equal(norths(knownTiles(state)), 4);
  assert.equal(norths(knownTilesOutsideHand(state)), 3);
  assert.equal(state.openMelds, 0);
  assert.throws(() => generateLegalActions(state), /not implemented/);
  const publicState = parsePublicGameState(base);
  assert.equal(publicState.ownKitaCount, 1);
  assert.equal(publicState.opponents[1]?.kitaCount, 1);
  const allExtracted = parseGameState({ ...base, hand: [...hand.slice(0, -1), "P"], ownKitaCount: 2 });
  assert.equal(norths(knownTiles(allExtracted)), 4);
});

test("extraction counts and all physical north locations share the four-copy limit", () => {
  assert.throws(() => parseGameState({ ...base, ownKitaCount: 2 }), /four copies/);
  assert.throws(() => parsePublicGameState({ ...base, ownKitaCount: 3 }), /four extracted/);
  assert.throws(() => parsePublicGameState({ ...base, doraIndicators: ["N", "N"] }), /four copies/);
  assert.throws(() => parsePublicGameState({ ...base, visibleTiles: ["N", "N"] }), /four copies/);
  assert.throws(() => parseGameState({ ...base, ownKitaCount: -1 }));
  assert.throws(() => parseGameState({ ...base, ownKitaCount: 1.5 }));
  assert.throws(() => parseGameState({ ...base, opponents: [{ seat: "south", kitaCount: 5 }] }));
});

test("yonma and unspecified rules reject explicitly supplied extraction counts", () => {
  for (const rules of ["yonma", undefined]) {
    assert.throws(() => parseGameState({ rules, hand, ownKitaCount: 0 }), /require explicitly/);
    assert.throws(() => parsePublicGameState({ rules, opponents: [{ seat: "south", kitaCount: 1 }] }), /require explicitly/);
    assert.equal(norths(knownTiles(parseGameState({ rules, hand }))), 1);
  }
});
