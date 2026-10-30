import { test } from "node:test";
import assert from "node:assert/strict";
import { sanmaStructuralCandidates } from "../src/game/sanmaLegalExperiment.js";
import { generateLegalActions } from "../src/game/actions.js";
import { parseGameState } from "../src/game/state.js";

// Native actions/2026-10-30T16-05-55-331Z-before.png: north in hand,
// separately drawn east, and 北抜き/スキップ displayed.
const state = { rules: "sanma", riichiDeclared: false, hand: ["1m", "9m", "9m", "4p", "0p", "5p", "6p", "8p", "2s", "6s", "S", "S", "N"], draw: "E" };
const input = { state, riichiStatus: "not_declared" as const, ui: { status: "confirmed" as const, actions: ["kita", "pass"] as const } };

test("real north prompt produces structural kita and skip separately from physical discards", () => {
  const actions = sanmaStructuralCandidates(input);
  assert.ok(actions.some(a => a.action === "kita"));
  assert.ok(actions.some(a => a.action === "pass"));
  assert.ok(actions.some(a => a.action === "discard" && a.tile === "N"));
  assert.throws(() => generateLegalActions(parseGameState(state)), /not implemented/);
});

test("verified UI and state disagreement or unknown riichi reject", () => {
  assert.throws(() => sanmaStructuralCandidates({ ...input, state: { ...state, hand: state.hand.map(t => t === "N" ? "P" : t) } }), /without a north/);
  assert.throws(() => sanmaStructuralCandidates({ ...input, state: { ...state, hand: ["2m", ...state.hand.slice(1)] } }), /unavailable/);
  assert.throws(() => sanmaStructuralCandidates({ ...input, state: { ...state, riichiDeclared: true } }), /pre-riichi/);
  assert.throws(() => sanmaStructuralCandidates({ ...input, ui: { status: "ambiguous", actions: ["kita"] } } as unknown as typeof input), /evidence/);
  assert.throws(() => sanmaStructuralCandidates({ ...input, ui: { status: "confirmed", actions: ["kita", "kita"] } }), /Ambiguous/);
  assert.throws(() => sanmaStructuralCandidates({ ...input, ui: { status: "confirmed", actions: ["chi"] } } as unknown as typeof input), /unsupported/);
});

test("UI-gated completed wins and reaction calls are bounded by actual tiles", () => {
  const won = { ...state, hand: ["1p", "2p", "3p", "4p", "5p", "6p", "1s", "2s", "3s", "4s", "5s", "W", "W"], draw: "6s" };
  assert.ok(sanmaStructuralCandidates({ ...input, state: won, ui: { status: "confirmed", actions: ["tsumo"] } }).some(a => a.action === "tsumo"));
  const reaction = { ...won, draw: undefined, phase: "reaction", pendingDiscard: { tile: "6s", fromSeat: "south" } };
  assert.ok(sanmaStructuralCandidates({ ...input, state: reaction, ui: { status: "confirmed", actions: ["ron", "pass"] } }).some(a => a.action === "ron"));
  const pon = { ...reaction, hand: ["1p", "1p", "3p", "4p", "5p", "6p", "1s", "2s", "3s", "4s", "5s", "W", "W"], pendingDiscard: { tile: "1p", fromSeat: "south" } };
  assert.deepEqual(sanmaStructuralCandidates({ ...input, state: pon, ui: { status: "confirmed", actions: ["pon", "pass"] } }), [{ action: "pon", tile: "1p" }, { action: "pass" }]);
  const kan = { ...pon, hand: pon.hand.map((t, i) => i === 2 ? "1p" : t) };
  assert.ok(sanmaStructuralCandidates({ ...input, state: kan, ui: { status: "confirmed", actions: ["kan"] } }).some(a => a.action === "minkan"));
  assert.throws(() => sanmaStructuralCandidates({ ...input, state: pon, ui: { status: "confirmed", actions: ["kan"] } }), /matching/);
});

test("four concealed tiles permit exactly one unambiguous kan candidate", () => {
  const hand = ["1p", "1p", "1p", "1p", "2p", "3p", "4p", "1s", "2s", "3s", "4s", "W", "W"];
  const actions = sanmaStructuralCandidates({ ...input, state: { ...state, hand, draw: "5s" }, ui: { status: "confirmed", actions: ["kan"] } });
  assert.ok(actions.some(a => a.action === "ankan" && a.tile === "1p"));
});
