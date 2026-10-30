import { knownTilesOutsideHand, type GameState } from "./state.js";
import { calculateShanten } from "./shanten.js";
import { evaluateDiscards } from "./ukeire.js";
import { isTerminalOrHonor, normalizeTile, suitRank, tileFromIndex, tileIndex, toCounts, type GameTile, type Tile } from "./tiles.js";

export type LegalAction =
  | { id: string; action: "discard"; tile: string }
  | { id: string; action: "riichi"; tile: string }
  | { id: "tsumo"; action: "tsumo" }
  | { id: "ron"; action: "ron" }
  | { id: "kyuushu"; action: "kyuushu" }
  | { id: string; action: "chi"; tile: GameTile; consumedTiles: GameTile[]; consumedTileChoices?: GameTile[][] }
  | { id: string; action: "pon"; tile: GameTile; consumedTiles: GameTile[]; consumedTileChoices?: GameTile[][] }
  | { id: string; action: "minkan" | "ankan" | "kakan"; tile: GameTile; consumedTiles: GameTile[]; consumedTileChoices?: GameTile[][] }
  | { id: "pass"; action: "pass" };

/** Preserve forced physical tiles; expose red/normal alternatives without
 * pretending the UI confirmed which copy it consumed. Structural action IDs
 * remain unchanged, including the order of the chi selectors. */
function physicalConsumption(hand: readonly GameTile[], required: readonly Tile[]) {
  const choices = new Map<string, GameTile[]>();
  function visit(remaining: GameTile[], selected: GameTile[]): void {
    if (selected.length === required.length) {
      const key = [...selected].sort().join("_");
      if (!choices.has(key)) choices.set(key, selected);
      return;
    }
    const tried = new Set<GameTile>();
    remaining.forEach((tile, index) => {
      if (normalizeTile(tile) !== required[selected.length] || tried.has(tile)) return;
      tried.add(tile);
      visit([...remaining.slice(0, index), ...remaining.slice(index + 1)], [...selected, tile]);
    });
  }
  visit([...hand], []);
  const alternatives = [...choices.values()];
  if (!alternatives.length) throw new Error("Call consumption is not present in concealed hand");
  return { consumedTiles: alternatives[0]!,
    ...(alternatives.length > 1 ? { consumedTileChoices: alternatives } : {}) };
}

export function generateSelfTurnActions(state: GameState): LegalAction[] {
  if (state.rules === "sanma") throw new Error("Sanma automatic actions are not implemented");
  if (state.phase !== "self_turn") throw new Error("Self-turn actions require phase=self_turn");
  const hand = state.draw ? [...state.hand, state.draw] : state.hand;
  const discards = evaluateDiscards(hand, knownTilesOutsideHand(state), state.openMelds);
  // Once riichi is established the concealed hand is locked. Keep the exact
  // physical draw identity here (a red five is not an interchangeable five).
  const legalDiscards = state.riichiDeclared ? discards.filter((candidate) => candidate.tile === state.draw) : discards;
  const actions: LegalAction[] = legalDiscards.map((candidate) => ({ id: candidate.actionId, action: "discard", tile: candidate.tile }));
  const ui = new Set(state.availableUiActions);

  if (ui.has("riichi") && state.openMelds === 0 && !state.riichiDeclared && (state.scores[state.seat] ?? 0) >= 1000) {
    for (const candidate of discards.filter((item) => item.shanten === 0)) {
      actions.push({ id: `riichi_${candidate.actionId}`, action: "riichi", tile: candidate.tile });
    }
  }
  if (ui.has("tsumo") && calculateShanten(hand, state.openMelds).shanten === -1) actions.push({ id: "tsumo", action: "tsumo" });
  if (ui.has("kyuushu") && state.turn <= 1) {
    const uniqueTerminalsAndHonors = new Set(hand.map(tileIndex).filter(isTerminalOrHonor));
    if (uniqueTerminalsAndHonors.size >= 9) actions.push({ id: "kyuushu", action: "kyuushu" });
  }
  if (ui.has("kan")) {
    const counts = toCounts(hand);
    for (let index = 0; index < counts.length; index += 1) {
      if (counts[index] === 4) {
        const tile = tileFromIndex(index);
        actions.push({ id: `ankan_${tile}`, action: "ankan", tile, ...physicalConsumption(hand, [tile, tile, tile, tile]) });
      }
    }
    for (const meld of state.melds.filter((candidate) => candidate.type === "pon")) {
      const tile = normalizeTile(meld.tiles[0]!);
      const concealed = hand.find((candidate) => normalizeTile(candidate) === tile);
      if (concealed) actions.push({ id: `kakan_${tile}`, action: "kakan", tile: concealed, ...physicalConsumption(hand, [tile]) });
    }
  }
  if (ui.has("pass")) actions.push({ id: "pass", action: "pass" });
  return actions;
}

const SEATS = ["east", "south", "west", "north"] as const;

function canChiFrom(fromSeat: GameState["seat"], ownSeat: GameState["seat"]): boolean {
  return SEATS[(SEATS.indexOf(ownSeat) + 3) % 4] === fromSeat;
}

export function generateReactionActions(state: GameState): LegalAction[] {
  if (state.rules === "sanma") throw new Error("Sanma automatic actions are not implemented");
  if (state.phase !== "reaction" || !state.pendingDiscard) throw new Error("Reaction actions require a pending discard");
  const ui = new Set(state.availableUiActions);
  const tile = normalizeTile(state.pendingDiscard.tile);
  const hand = state.hand.map(normalizeTile);
  const counts = toCounts(hand);
  const index = tileIndex(tile);
  const actions: LegalAction[] = [];

  if (ui.has("ron") && calculateShanten([...hand, tile], state.openMelds).shanten === -1) {
    actions.push({ id: "ron", action: "ron" });
  }
  if (ui.has("pon") && counts[index]! >= 2) {
    actions.push({ id: `pon_${tile}`, action: "pon", tile: state.pendingDiscard.tile, ...physicalConsumption(state.hand, [tile, tile]) });
  }
  if (ui.has("kan") && counts[index]! >= 3) {
    actions.push({ id: `minkan_${tile}`, action: "minkan", tile: state.pendingDiscard.tile, ...physicalConsumption(state.hand, [tile, tile, tile]) });
  }
  if (ui.has("chi") && index < 27 && canChiFrom(state.pendingDiscard.fromSeat, state.seat)) {
    const rank = suitRank(index) + 1;
    const suitStart = Math.floor(index / 9) * 9;
    for (let start = rank - 2; start <= rank; start += 1) {
      if (start < 1 || start > 7) continue;
      const sequence = [start, start + 1, start + 2].map((value) => tileFromIndex(suitStart + value - 1));
      const consumed = sequence.filter((value) => value !== tile);
      if (consumed.length === 2 && consumed.every((value) => counts[tileIndex(value)]! >= consumed.filter((other) => other === value).length)) {
        actions.push({ id: `chi_${tile}_${consumed.join("_")}`, action: "chi", tile: state.pendingDiscard.tile, ...physicalConsumption(state.hand, consumed) });
      }
    }
  }
  if (ui.has("pass")) actions.push({ id: "pass", action: "pass" });
  return actions;
}

export function generateLegalActions(state: GameState): LegalAction[] {
  return state.phase === "reaction" ? generateReactionActions(state) : generateSelfTurnActions(state);
}
