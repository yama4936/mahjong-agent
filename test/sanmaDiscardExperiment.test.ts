import { test } from "node:test";
import assert from "node:assert/strict";
import { sanmaDiscardExperiment } from "../src/game/sanmaDiscardExperiment.js";
import { evaluateDiscards } from "../src/game/ukeire.js";
import { generateLegalActions } from "../src/game/actions.js";
import { parseGameState } from "../src/game/state.js";

// Hand pattern from native 16-05-55-331Z-before; synthetic no-prompt state
// for isolated arithmetic, not a claim the pictured kita prompt was handled.
const hand = ["1m", "9m", "9m", "4p", "0p", "5p", "6p", "8p", "2s", "6s", "S", "S", "N"];
const opponent = (seat: string) => ({ seat, discards: [], melds: [], openMelds: 0, kitaCount: 0 });
const state = { rules: "sanma", riichiDeclared: false, phase: "self_turn", hand, draw: "E",
  seat: "east", openMelds: 0, melds: [], visibleTiles: [], ownDiscards: [], doraIndicators: [], ownKitaCount: 0,
  opponents: [opponent("south"), opponent("west")] };
const input = { state, riichiStatus: "not_declared" as const, ui: { status: "confirmed" as const, actions: [] },
  turnContext: "ordinary_draw_confirmed" as const, handEvidence: "confirmed" as const, meldEvidence: "confirmed" as const, visibleEvidence: "confirmed_complete" as const };

test("sanma candidates restrict ukeire to available tiles", () => {
  const rows = sanmaDiscardExperiment(input);
  assert.ok(rows.length > 0);
  assert.ok(rows.every(row => row.effectiveTiles.every(({ tile }) => !/^[2-8]m$/.test(tile))));
  assert.ok(evaluateDiscards([...hand, "E"]).some(row => row.effectiveTiles.some(({ tile }) => /^[2-8]m$/.test(tile))));
  assert.throws(() => generateLegalActions(parseGameState(state)), /not implemented/);
});

test("priority prompts and missing evidence reject before discard", () => {
  for (const action of ["kita", "tsumo", "kan", "pass"] as const) {
    assert.throws(() => sanmaDiscardExperiment({ ...input, ui: { status: "confirmed", actions: [action] } }));
  }
  assert.throws(() => sanmaDiscardExperiment({ ...input, state: { ...state, openMelds: undefined } }));
  assert.throws(() => sanmaDiscardExperiment({ ...input, state: { ...state, draw: undefined } }));
  assert.throws(() => sanmaDiscardExperiment({ ...input, state: { ...state, ownKitaCount: undefined } }));
  assert.throws(() => sanmaDiscardExperiment({ ...input, state: { ...state, riichiDeclared: true } }));
  assert.throws(() => sanmaDiscardExperiment({ ...input, visibleEvidence: "unknown" } as unknown as typeof input));
});

test("visible extracted north is counted once in remaining copies", () => {
  const base = sanmaDiscardExperiment(input);
  const after = sanmaDiscardExperiment({ ...input, state: { ...state, ownKitaCount: 1 } });
  const beforeNorth = base.flatMap(row => row.effectiveTiles.filter(tile => tile.tile === "N"));
  const afterNorth = after.flatMap(row => row.effectiveTiles.filter(tile => tile.tile === "N"));
  assert.ok(beforeNorth.length > 0);
  assert.ok(beforeNorth.every((tile, i) => tile.remaining === afterNorth[i]!.remaining + 1));
});
