import { z } from "zod";
import { parseGameTile, toCounts, type GameTile } from "./tiles.js";

const tileSchema = z.string().transform(parseGameTile);
const seatSchema = z.enum(["east", "south", "west", "north"]);
const uiActionSchema = z.enum(["riichi", "tsumo", "ron", "chi", "pon", "kan", "kyuushu", "pass"]);
const meldSchema = z.object({
  type: z.enum(["chi", "pon", "minkan", "ankan", "kakan"]),
  tiles: z.array(tileSchema).min(3).max(4),
  fromSeat: seatSchema.optional(),
});

const gameStateObjectSchema = z.object({
  round: z.string().default("unknown"),
  honba: z.number().int().nonnegative().default(0),
  riichiSticks: z.number().int().nonnegative().default(0),
  seat: seatSchema.default("east"),
  scores: z.record(z.string(), z.number().int()).default({}),
  hand: z.array(tileSchema),
  draw: tileSchema.optional(),
  doraIndicators: z.array(tileSchema).default([]),
  ownDiscards: z.array(tileSchema).default([]),
  melds: z.array(meldSchema).max(4).default([]),
  visibleTiles: z.array(tileSchema).default([]),
  openMelds: z.number().int().min(0).max(4).default(0),
  turn: z.number().int().nonnegative().default(0),
  remainingTiles: z.number().int().min(0).max(70).optional(),
  phase: z.enum(["self_turn", "reaction"]).default("self_turn"),
  pendingDiscard: z.object({ tile: tileSchema, fromSeat: seatSchema }).optional(),
  recognitionConfidence: z.number().min(0).max(1).default(1),
  publicStateConfidence: z.number().min(0).max(1).default(0),
  riichiDeclared: z.boolean().default(false),
  availableUiActions: z.array(uiActionSchema).default([]),
  opponents: z.array(z.object({
    seat: seatSchema,
    discards: z.array(tileSchema).default([]),
    riichi: z.boolean().default(false),
    openMelds: z.number().int().min(0).max(4).default(0),
  })).default([]),
});

function normalizeStateInput(value: unknown): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  const source = value as Record<string, unknown>;
  return {
    ...source,
    riichiSticks: source.riichiSticks ?? source.riichi_sticks,
    doraIndicators: source.doraIndicators ?? source.dora_indicators,
    ownDiscards: source.ownDiscards ?? source.own_discards,
    melds: source.melds,
    visibleTiles: source.visibleTiles ?? source.visible_tiles,
    openMelds: source.openMelds ?? source.open_melds ?? (Array.isArray(source.melds) ? source.melds.length : undefined),
    remainingTiles: source.remainingTiles ?? source.remaining_tiles,
    recognitionConfidence: source.recognitionConfidence ?? source.recognition_confidence,
    publicStateConfidence: source.publicStateConfidence ?? source.public_state_confidence,
    riichiDeclared: source.riichiDeclared ?? source.riichi_declared,
    availableUiActions: source.availableUiActions ?? source.available_ui_actions,
    pendingDiscard: source.pendingDiscard ?? source.pending_discard,
  };
}

export const gameStateSchema = z.preprocess(normalizeStateInput, gameStateObjectSchema);

export const publicGameStateSchema = z.preprocess(
  normalizeStateInput,
  gameStateObjectSchema.omit({ hand: true, draw: true, recognitionConfidence: true }),
);

export type GameState = z.infer<typeof gameStateSchema>;
export type PublicGameState = z.infer<typeof publicGameStateSchema>;

function assertHighConfidencePublicState(state: PublicGameState): void {
  if (state.publicStateConfidence < 0.98) return;
  const seats = ["east", "south", "west", "north"] as const;
  const reasons: string[] = [];
  if (state.round === "unknown") reasons.push("round");
  if (state.doraIndicators.length === 0) reasons.push("doraIndicators");
  if (state.remainingTiles === undefined) reasons.push("remainingTiles");
  if (seats.some((seat) => state.scores[seat] === undefined)) reasons.push("scores");
  const opponents = state.opponents.map((opponent) => opponent.seat);
  if (opponents.length !== 3 || new Set(opponents).size !== 3 || opponents.includes(state.seat)) reasons.push("opponents");
  if (reasons.length) throw new Error(`publicStateConfidence >= 0.98 requires complete evidence: ${reasons.join(", ")}`);
}

/**
 * Returns every physically known tile exactly once. `visibleTiles` is reserved
 * for known tiles that are not already represented by another state field
 * (for example, called meld tiles once meld recognition is added).
 */
export function knownTiles(state: GameState): GameTile[] {
  return [
    ...state.hand,
    ...(state.draw ? [state.draw] : []),
    ...state.doraIndicators,
    ...state.ownDiscards,
    ...state.melds.flatMap((meld) => meld.tiles),
    ...state.visibleTiles,
    ...state.opponents.flatMap((opponent) => opponent.discards),
    ...(state.pendingDiscard ? [state.pendingDiscard.tile] : []),
  ];
}

export function knownTilesOutsideHand(state: GameState): GameTile[] {
  return [
    ...state.doraIndicators,
    ...state.ownDiscards,
    ...state.melds.flatMap((meld) => meld.tiles),
    ...state.visibleTiles,
    ...state.opponents.flatMap((opponent) => opponent.discards),
    ...(state.pendingDiscard ? [state.pendingDiscard.tile] : []),
  ];
}

export function parseGameState(input: unknown): GameState {
  const state = gameStateSchema.parse(input);
  assertHighConfidencePublicState(state);
  const tiles = state.draw ? [...state.hand, state.draw] : state.hand;
  if (state.phase === "reaction" && state.draw) throw new Error("Reaction state must not include a draw tile");
  if (state.phase === "reaction" && !state.pendingDiscard) throw new Error("Reaction state requires pendingDiscard");
  if (state.melds.length > 0 && state.melds.length !== state.openMelds) throw new Error("melds length must equal openMelds");
  const expected = (state.phase === "self_turn" ? 14 : 13) - state.openMelds * 3;
  if (tiles.length !== expected) {
    throw new Error(`Expected ${expected} concealed tiles before discard, got ${tiles.length}`);
  }
  // Reject impossible recognition/state combinations before they can reach a
  // recommendation or an automatic click.
  toCounts(knownTiles(state));
  return state;
}

export function parsePublicGameState(input: unknown): PublicGameState {
  const state = publicGameStateSchema.parse(input);
  assertHighConfidencePublicState(state);
  if (state.phase === "reaction" && !state.pendingDiscard) throw new Error("Reaction state requires pendingDiscard");
  if (state.melds.length > 0 && state.melds.length !== state.openMelds) throw new Error("melds length must equal openMelds");
  // Publicly represented tiles still have to obey the four-copy invariant,
  // independently of the concealed hand that will be recognized later.
  toCounts([
    ...state.doraIndicators,
    ...state.ownDiscards,
    ...state.melds.flatMap((meld) => meld.tiles),
    ...state.visibleTiles,
    ...state.opponents.flatMap((opponent) => opponent.discards),
    ...(state.pendingDiscard ? [state.pendingDiscard.tile] : []),
  ]);
  return state;
}
