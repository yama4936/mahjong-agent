import assert from "node:assert/strict";
import test from "node:test";
import { generateReactionActions, generateSelfTurnActions } from "../src/game/actions.js";
import { parseGameState } from "../src/game/state.js";

test("riichi is generated only for tenpai discards exposed by the UI", () => {
  const state = parseGameState({
    seat: "east",
    scores: { east: 25000 },
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"],
    draw: "6p",
    availableUiActions: ["riichi"],
  });
  const actions = generateSelfTurnActions(state);
  assert.ok(actions.some((action) => action.action === "riichi" && action.tile === "E"));
});

test("reaction actions generate only structurally valid UI-exposed calls", () => {
  const state = parseGameState({
    phase: "reaction",
    seat: "south",
    hand: ["1m", "2m", "4m", "4m", "4m", "5p", "6p", "7p", "2s", "3s", "4s", "E", "E"],
    pendingDiscard: { tile: "3m", fromSeat: "east" },
    availableUiActions: ["chi", "pon", "kan", "pass"],
  });
  const actions = generateReactionActions(state);
  assert.ok(actions.some((action) => action.action === "chi" && action.id === "chi_3m_1m_2m"));
  assert.ok(!actions.some((action) => action.action === "pon"));
  assert.ok(!actions.some((action) => action.action === "minkan"));
  assert.ok(actions.some((action) => action.action === "pass"));
});

test("pon and open kan require two and three matching concealed tiles", () => {
  const state = parseGameState({
    phase: "reaction",
    seat: "west",
    hand: ["5m", "5m", "5m", "1p", "2p", "3p", "4p", "5p", "6p", "7s", "8s", "9s", "E"],
    pendingDiscard: { tile: "5m", fromSeat: "south" },
    availableUiActions: ["pon", "kan", "pass"],
  });
  const actions = generateReactionActions(state);
  assert.ok(actions.some((action) => action.action === "pon"));
  assert.ok(actions.some((action) => action.action === "minkan"));
});

test("closed and added kan are generated on a self turn", () => {
  const closed = parseGameState({
    hand: ["1m", "2m", "3m", "1p", "2p", "3p", "1s", "2s", "3s", "E", "E", "E", "E"],
    draw: "5m",
    availableUiActions: ["kan"],
  });
  assert.ok(generateSelfTurnActions(closed).some((action) => action.action === "ankan" && action.tile === "E"));

  const added = parseGameState({
    hand: ["1m", "2m", "3m", "1p", "2p", "3p", "1s", "2s", "3s", "E"],
    draw: "5m",
    melds: [{ type: "pon", tiles: ["E", "E", "E"] }],
    openMelds: 1,
    availableUiActions: ["kan"],
  });
  assert.ok(generateSelfTurnActions(added).some((action) => action.action === "kakan" && action.tile === "E"));
});

test("nine terminals abort is UI-gated and structurally checked", () => {
  const state = parseGameState({
    turn: 0,
    hand: ["1m", "9m", "1p", "9p", "1s", "9s", "E", "S", "W", "N", "P", "F", "2m"],
    draw: "3m",
    availableUiActions: ["kyuushu"],
  });
  assert.ok(generateSelfTurnActions(state).some((action) => action.action === "kyuushu"));
});

test("tsumo trusts the visible UI button but also requires a complete hand", () => {
  const state = parseGameState({
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "1p", "2p", "3p", "7s", "8s", "9s", "E"],
    draw: "E",
    availableUiActions: ["tsumo"],
  });
  assert.ok(generateSelfTurnActions(state).some((action) => action.action === "tsumo"));
});

test("declared riichi exposes only the physical draw (live 4p versus 6s regression)", () => {
  const state = parseGameState({
    seat: "south", riichiDeclared: true,
    hand: ["1m", "1m", "1m", "5m", "6m", "7m", "3p", "4p", "4s", "4s", "0s", "5s", "5s"],
    draw: "6s",
  });
  assert.deepEqual(generateSelfTurnActions(state), [{ id: "discard_6s", action: "discard", tile: "6s" }]);
  assert.ok(generateSelfTurnActions({ ...state, riichiDeclared: false }).some(a => a.action === "discard" && a.tile === "4p"));
});

test("declared riichi preserves red draw identity and rejects a missing draw", () => {
  const base = parseGameState({
    riichiDeclared: true,
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"],
    draw: "E",
  });
  for (const draw of ["0m", "5m"] as const) {
    assert.deepEqual(generateSelfTurnActions({ ...base, draw }).filter(a => a.action === "discard"),
      [{ id: `discard_${draw}`, action: "discard", tile: draw }]);
  }
  const { draw, ...withoutDraw } = base;
  assert.throws(() => parseGameState(withoutDraw), /Expected 14/);
  assert.deepEqual(generateSelfTurnActions(parseGameState({ ...withoutDraw, hand: [...base.hand, draw!] })), []);
});

test("declared riichi retains a valid tsumo and the UI kan/pass path", () => {
  const state = parseGameState({
    riichiDeclared: true,
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "1p", "2p", "3p", "7s", "8s", "9s", "E"],
    draw: "E", availableUiActions: ["tsumo"],
  });
  assert.deepEqual(generateSelfTurnActions(state).map(a => a.action), ["discard", "tsumo"]);
  const kan = parseGameState({ riichiDeclared: true,
    hand: ["1m", "2m", "3m", "1p", "2p", "3p", "1s", "2s", "3s", "E", "E", "E", "5m"],
    draw: "E", availableUiActions: ["kan", "pass"],
  });
  assert.deepEqual(generateSelfTurnActions(kan).map(a => a.action), ["discard", "ankan", "pass"]);
});
