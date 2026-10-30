import { parseGameState } from "./state.js";
import { calculateShanten } from "./shanten.js";
import { normalizeTile, tileFromIndex, tileIndex, toCounts, type GameTile, type Tile } from "./tiles.js";

const uiNames = ["kita", "tsumo", "ron", "pon", "kan", "pass"] as const;
type UiName = typeof uiNames[number];
export type SanmaCandidate =
  | { action: "discard"; tile: GameTile }
  | { action: "kita" | "tsumo" | "ron" | "pass" }
  | { action: "pon" | "minkan" | "ankan" | "kakan"; tile: Tile };

/**
 * Offline, incomplete structural candidates, never permission to operate UI.
 * Caller must have independently established pre-riichi status and a complete,
 * unambiguous UI snapshot. Calls do not specify physical red tile consumption.
 * Remaining wall/kan limits and reaction source legality are delegated to the
 * independently verified game UI. No assumption about post-riichi rules.
 */
export function sanmaStructuralCandidates(input: {
  state: unknown; riichiStatus: "not_declared"; ui: { status: "confirmed"; actions: readonly UiName[] };
}): SanmaCandidate[] {
  if (!input || input.riichiStatus !== "not_declared" || input.ui?.status !== "confirmed" || !Array.isArray(input.ui.actions)) {
    throw new Error("Confirmed pre-riichi and UI evidence required");
  }
  const names = input.ui.actions;
  if (new Set(names).size !== names.length || names.some(name => !uiNames.includes(name))) throw new Error("Ambiguous or unsupported UI action");
  if (!input.state || typeof input.state !== "object" || Array.isArray(input.state)) throw new Error("Sanma state required");
  const raw = input.state as Record<string, unknown>;
  if (raw.rules !== "sanma" || raw.riichiDeclared !== false || raw.availableUiActions !== undefined || raw.available_ui_actions !== undefined) {
    throw new Error("Explicit sanma pre-riichi state and separate UI evidence required");
  }
  const state = parseGameState(raw);
  const ui = new Set(names);
  if (state.phase === "self_turn" && (ui.has("ron") || ui.has("pon"))) throw new Error("Reaction UI on self turn");
  if (state.phase === "reaction" && (ui.has("kita") || ui.has("tsumo"))) throw new Error("Self-turn UI on reaction");
  const result: SanmaCandidate[] = [];
  if (state.phase === "self_turn") {
    const hand = [...state.hand, ...(state.draw ? [state.draw] : [])];
    for (const tile of new Set(hand)) result.push({ action: "discard", tile });
    if (ui.has("kita")) {
      if (!hand.includes("N")) throw new Error("Kita UI without a north tile");
      result.push({ action: "kita" });
    }
    if (ui.has("tsumo")) {
      if (calculateShanten(hand, state.openMelds).shanten !== -1) throw new Error("Tsumo UI without a complete hand");
      result.push({ action: "tsumo" });
    }
    if (ui.has("kan")) {
      const choices: SanmaCandidate[] = [];
      const counts = toCounts(hand);
      counts.forEach((count, index) => { if (count === 4) choices.push({ action: "ankan", tile: tileFromIndex(index) }); });
      for (const meld of state.melds.filter(meld => meld.type === "pon")) {
        const tile = normalizeTile(meld.tiles[0]!);
        if (meld.tiles.every(value => normalizeTile(value) === tile) && counts[tileIndex(tile)]! > 0) choices.push({ action: "kakan", tile });
      }
      if (choices.length !== 1) throw new Error("Kan selection is ambiguous or unsupported");
      result.push(choices[0]!);
    }
  } else {
    const pending = state.pendingDiscard!;
    if (pending.fromSeat === state.seat) throw new Error("Cannot react to own discard");
    const tile = normalizeTile(pending.tile);
    const count = toCounts(state.hand)[tileIndex(tile)]!;
    if (ui.has("ron")) {
      if (calculateShanten([...state.hand, tile], state.openMelds).shanten !== -1) throw new Error("Ron UI without a complete hand");
      result.push({ action: "ron" });
    }
    if (ui.has("pon")) {
      if (count < 2) throw new Error("Pon UI without matching tiles");
      result.push({ action: "pon", tile });
    }
    if (ui.has("kan")) {
      if (count < 3) throw new Error("Kan UI without matching tiles");
      result.push({ action: "minkan", tile });
    }
  }
  if (ui.has("pass")) result.push({ action: "pass" });
  return result;
}
