import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { generateReactionActions, generateSelfTurnActions } from "../src/game/actions.js";
import { parseGameState } from "../src/game/state.js";
import { deterministicAdvice } from "../src/evaluation/advisor.js";
import { buildJevReactionRequest } from "../src/jev/client.js";

async function fixture() { return JSON.parse(await readFile("test/fixtures/red-call-physical-identity-20261022.json", "utf8")); }

test("native36 forced red pon survives generated action, prompt and ordinary point evaluation", async () => {
  const f = await fixture(), state = parseGameState(f.reactionState);
  const actions = generateReactionActions(state);
  const pon = actions.find(a => a.action === "pon")!;
  assert.equal(pon.id, "pon_5p");
  assert.ok("consumedTiles" in pon);
  if (!("consumedTiles" in pon)) return;
  assert.deepEqual(pon.consumedTiles, ["0p", "5p"]);
  assert.equal(pon.consumedTileChoices, undefined);
  const request = buildJevReactionRequest(state, actions, "test");
  assert.match(JSON.stringify(request), /0p/);
  const before = deterministicAdvice(parseGameState(f.postCallState));
  const corrected = parseGameState({ ...f.postCallState, melds: [{ type: "pon", tiles: [...pon.consumedTiles, pon.tile] }] });
  const after = deterministicAdvice(corrected);
  assert.equal(before.candidates.find(c => c.tile === "5s")!.estimatedValue, 5800);
  assert.equal(after.candidates.find(c => c.tile === "5s")!.estimatedValue, 11600);
  assert.equal(before.candidates.find(c => c.tile === "0s")!.estimatedValue, 2900);
  assert.equal(after.candidates.find(c => c.tile === "0s")!.estimatedValue, 5800);
  for (const old of before.candidates) {
    const next = after.candidates.find(c => c.tile === old.tile)!;
    assert.equal(next.shanten, old.shanten);
    assert.equal(next.ukeire, old.ukeire);
    assert.equal(next.danger, old.danger);
  }
});

test("called red five and forced red chi keep physical identity with stable structural IDs", async () => {
  const base = { ...(await fixture()).reactionState, ownDiscards: [], opponents: [], doraIndicators: [] };
  const redCalled = generateReactionActions(parseGameState({ ...base,
    hand: ["2m","3m","4m","5p","5p","6p","7p","8p","2s","3s","4s","P","P"],
    pendingDiscard: { tile: "0p", fromSeat: "south" }, availableUiActions: ["pon","pass"] }));
  const pon = redCalled.find(a => a.action === "pon")!;
  assert.deepEqual(pon, { id: "pon_5p", action: "pon", tile: "0p", consumedTiles: ["5p","5p"] });
  const chi = generateReactionActions(parseGameState({ ...base,
    hand: ["2m","2m","2m","3m","4m","6m","7m","8m","4p","0p","2s","3s","4s"],
    pendingDiscard: { tile: "3p", fromSeat: "north" }, availableUiActions: ["chi","pass"] })).find(a => a.action === "chi")!;
  assert.deepEqual(chi, { id: "chi_3p_4p_5p", action: "chi", tile: "3p", consumedTiles: ["4p","0p"] });
});

test("ambiguous red consumption exposes alternatives without adding structural pon/chi selectors", async () => {
  const base = { ...(await fixture()).reactionState, ownDiscards: [], opponents: [], doraIndicators: [] };
  for (const [action, called, hand, fromSeat] of [
    ["pon","5p",["0p","5p","5p","1m","2m","3m","4m","5m","6m","7s","8s","9s","P"],"south"],
    ["chi","3p",["4p","0p","5p","1m","2m","3m","4m","5m","6m","7s","8s","9s","P"],"north"],
  ] as const) {
    const actions = generateReactionActions(parseGameState({ ...base, hand,
      pendingDiscard: { tile: called, fromSeat }, availableUiActions: [action,"pass"] }));
    const calls = actions.filter(a => a.action === action);
    assert.equal(calls.length, 1);
    assert.ok("consumedTileChoices" in calls[0]!);
    if ("consumedTileChoices" in calls[0]!) assert.equal(calls[0]!.consumedTileChoices!.length, 2);
    assert.match(JSON.stringify(buildJevReactionRequest(parseGameState({ ...base, hand,
      pendingDiscard: { tile: called, fromSeat }, availableUiActions: [action,"pass"] }), actions, "test")), /consumedTileChoices/);
  }
});

test("open closed and added kan preserve red consumed and called tiles", async () => {
  const base = { ...(await fixture()).reactionState, ownDiscards: [], opponents: [], doraIndicators: [] };
  const hand = ["0p","5p","5p","1m","2m","3m","4m","5m","6m","7s","8s","9s","P"];
  const open = generateReactionActions(parseGameState({ ...base, hand,
    pendingDiscard: { tile: "5p", fromSeat: "south" }, availableUiActions: ["kan","pass"] })).find(a => a.action === "minkan")!;
  assert.ok("consumedTiles" in open);
  if ("consumedTiles" in open) assert.deepEqual(open.consumedTiles, ["0p","5p","5p"]);
  const closed = generateSelfTurnActions(parseGameState({ ...base, phase: "self_turn", pendingDiscard: undefined, hand,
    draw: "5p", availableUiActions: ["kan"] })).find(a => a.action === "ankan")!;
  assert.ok("consumedTiles" in closed);
  if ("consumedTiles" in closed) assert.deepEqual(closed.consumedTiles, ["0p","5p","5p","5p"]);
  const added = generateSelfTurnActions(parseGameState({ ...base, phase: "self_turn", pendingDiscard: undefined, hand: hand.filter(t => t !== "0p" && t !== "5p"),
    draw: "0p", melds: [{ type: "pon", tiles: ["5p","5p","5p"] }], openMelds: 1,
    availableUiActions: ["kan"] })).find(a => a.action === "kakan")!;
  assert.ok("consumedTiles" in added);
  if ("consumedTiles" in added) assert.deepEqual(added.consumedTiles, ["0p"]);
});
