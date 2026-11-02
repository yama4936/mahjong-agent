import { test } from "node:test";
import assert from "node:assert/strict";
import { sanmaPhysicalCallCandidates } from "../src/game/sanmaPhysicalCandidates.js";
import { generateLegalActions } from "../src/game/actions.js";
import { parseGameState } from "../src/game/state.js";

const hand = ["0p", "5p", "5p", "1p", "2p", "3p", "1s", "2s", "3s", "4s", "6s", "W", "W"];
const reaction = { rules: "sanma", riichiDeclared: false, phase: "reaction", hand,
  pendingDiscard: { tile: "5p", fromSeat: "south" } };
const input = { state: reaction, riichiStatus: "not_declared" as const,
  ui: { status: "confirmed" as const, actions: ["pon"] as const } };

test("pon preserves normal and red physical consumption alternatives and the called tile", () => {
  const result = sanmaPhysicalCallCandidates(input);
  assert.equal(result.operationAuthorized, false);
  assert.equal(result.candidates.length, 1);
  const row = result.candidates[0]!;
  assert.equal(row.calledTile, "5p");
  assert.deepEqual(row.consumedTileChoices?.map(x => [...x].sort().join(",")).sort(), ["0p,5p", "5p,5p"]);
  assert.throws(() => generateLegalActions(parseGameState(reaction)), /not implemented/);
});

test("minkan and ankan preserve four exact physical identities", () => {
  const open = sanmaPhysicalCallCandidates({ ...input, ui: { status: "confirmed", actions: ["kan"] } });
  assert.deepEqual(open.candidates[0]?.consumedTiles.sort(), ["0p", "5p", "5p"]);
  assert.equal(open.candidates[0]?.calledTile, "5p");
  const self = { rules: "sanma", riichiDeclared: false, hand, draw: "5p" };
  const closed = sanmaPhysicalCallCandidates({ ...input, state: self, ui: { status: "confirmed", actions: ["kan"] } });
  assert.deepEqual(closed.candidates[0]?.consumedTiles.sort(), ["0p", "5p", "5p", "5p"]);
  assert.equal(closed.candidates[0]?.calledTile, undefined);
});

test("unconfirmed prompts, unavailable tiles and own reaction fail closed", () => {
  assert.throws(() => sanmaPhysicalCallCandidates({ ...input, ui: { status: "ambiguous", actions: ["pon"] } } as unknown as typeof input), /evidence/);
  assert.throws(() => sanmaPhysicalCallCandidates({ ...input, state: { ...reaction, hand: ["2m", ...hand.slice(1)] } }), /unavailable/);
  assert.throws(() => sanmaPhysicalCallCandidates({ ...input, state: { ...reaction, pendingDiscard: { tile: "5p", fromSeat: "east" } } }), /own discard/);
});

test("red called tile and kakan retain distinct physical identities", () => {
  const redCalled = { ...reaction, hand: ["5p", "5p", "5p", ...hand.slice(3)], pendingDiscard: { tile: "0p", fromSeat: "south" } };
  const pon = sanmaPhysicalCallCandidates({ ...input, state: redCalled }).candidates[0]!;
  assert.equal(pon.calledTile, "0p");
  assert.deepEqual(pon.consumedTiles, ["5p", "5p"]);
  const kakan = { rules: "sanma", riichiDeclared: false,
    hand: ["0p", "1p", "2p", "3p", "1s", "2s", "3s", "4s", "6s", "W"], draw: "W",
    melds: [{ type: "pon", tiles: ["5p", "5p", "5p"], fromSeat: "south" }] };
  const added = sanmaPhysicalCallCandidates({ ...input, state: kakan, ui: { status: "confirmed", actions: ["kan"] } }).candidates[0]!;
  assert.equal(added.action, "kakan");
  assert.deepEqual(added.consumedTiles, ["0p"]);
  assert.equal(added.calledTile, undefined);
});
