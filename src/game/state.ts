import { z } from "zod";
import { assertTilesAvailable, parseGameTile, toCounts, type GameTile } from "./tiles.js";

const tileSchema = z.string().transform(parseGameTile);
const seatSchema = z.enum(["east", "south", "west", "north"]);
const uiActionSchema = z.enum(["riichi", "tsumo", "ron", "chi", "pon", "kan", "kyuushu", "pass"]);
const meldSchema = z.object({
  type: z.enum(["chi", "pon", "minkan", "ankan", "kakan"]),
  tiles: z.array(tileSchema).min(3).max(4),
  fromSeat: seatSchema.optional(),
});

const gameStateObjectSchema = z.object({
  rules: z.enum(["yonma", "sanma"]).optional(),
  round: z.string().default("unknown"),
  matchLength: z.enum(["east", "south"]).optional(),
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
  pendingDiscard: z.object({ tile: tileSchema, fromSeat: seatSchema, inRiver: z.boolean().optional() }).optional(),
  recognitionConfidence: z.number().min(0).max(1).default(1),
  publicStateConfidence: z.number().min(0).max(1).default(0),
  riichiDeclared: z.boolean().default(false),
  availableUiActions: z.array(uiActionSchema).default([]),
  opponents: z.array(z.object({
    seat: seatSchema,
    discards: z.array(tileSchema).default([]),
    riichi: z.boolean().default(false),
    // Historical safety evidence, not additional physically visible tiles.
    postRiichiSafeTiles: z.array(tileSchema).max(34).optional(),
    openMelds: z.number().int().min(0).max(4).default(0),
    openMeldsObserved: z.boolean().optional(),
    melds: z.array(meldSchema).max(4).optional(),
  })).default([]),
});

function normalizeStateInput(value: unknown): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  const source = value as Record<string, unknown>;
  return {
    ...source,
    matchLength: source.matchLength ?? source.match_length,
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

/** Scheduled final hand or an extension; dealer continuation can still occur. */
export function isAllLastRound(state: Pick<PublicGameState, "round" | "matchLength" | "rules">): boolean {
  if (state.rules === "sanma" && /^(east|south|west|north)_4$/i.test(state.round)) throw new Error("Sanma has no fourth hand");
  const lastHand = state.rules === "sanma" ? "3" : "4";
  if (state.matchLength === undefined) return new RegExp(`^(south|west|north)_${lastHand}$`, "i").test(state.round);
  const round = /^(east|south|west|north)_([1-4])$/i.exec(state.round);
  if (!round) return false;
  const wind = ["east", "south", "west", "north"].indexOf(round[1]!.toLowerCase());
  const scheduledWind = state.matchLength === "east" ? 0 : 1;
  return wind > scheduledWind || wind === scheduledWind && round[2] === lastHand;
}

export function assertYonmaEvaluation(state: Pick<PublicGameState, "rules">): void {
  if (state.rules === "sanma") throw new Error("Sanma evaluation is not implemented");
}

function assertSanmaConsistency(state: PublicGameState): void {
  if (state.rules !== "sanma") return;
  if (/^(east|south|west|north)_4$/i.test(state.round)) throw new Error("Sanma has no fourth hand");
  if (state.seat === "north" || state.pendingDiscard?.fromSeat === "north"
    || state.opponents.some(opponent => opponent.seat === "north") || state.scores.north !== undefined
    || state.melds.some(meld => meld.fromSeat === "north")
    || state.opponents.some(opponent => opponent.melds?.some(meld => meld.fromSeat === "north"))) {
    throw new Error("Sanma has no north seat");
  }
  if (state.availableUiActions.includes("chi") || state.melds.some(meld => meld.type === "chi")
    || state.opponents.some(opponent => opponent.melds?.some(meld => meld.type === "chi"))) {
    throw new Error("Chi is unavailable in sanma");
  }
  const seats = state.opponents.map(opponent => opponent.seat);
  if (seats.length > 2 || new Set(seats).size !== seats.length || seats.includes(state.seat)) {
    throw new Error("Invalid sanma opponents");
  }
}

function assertHighConfidencePublicState(state: PublicGameState): void {
  if (state.publicStateConfidence < 0.98) return;
  const seats = state.rules === "sanma" ? ["east", "south", "west"] as const : ["east", "south", "west", "north"] as const;
  const reasons: string[] = [];
  if (state.round === "unknown") reasons.push("round");
  if (state.doraIndicators.length === 0) reasons.push("doraIndicators");
  if (state.remainingTiles === undefined) reasons.push("remainingTiles");
  if (seats.some((seat) => state.scores[seat] === undefined)) reasons.push("scores");
  const opponents = state.opponents.map((opponent) => opponent.seat);
  if (!seats.includes(state.seat as never) || opponents.length !== seats.length - 1 || new Set(opponents).size !== seats.length - 1 || opponents.includes(state.seat) || opponents.some((seat) => !seats.includes(seat as never))) reasons.push("opponents");
  if (reasons.length) throw new Error(`publicStateConfidence >= 0.98 requires complete evidence: ${reasons.join(", ")}`);
}

/**
 * Returns every physically known tile exactly once. `visibleTiles` is reserved
 * for known tiles that are not already represented by another state field
 * (for example, called meld tiles once meld recognition is added).
 */
function pendingTileOutsideRiver(state: Pick<GameState, "pendingDiscard" | "opponents">): GameTile[] {
  const pending = state.pendingDiscard;
  if (!pending) return [];
  if (!pending.inRiver) return [pending.tile];
  const rivers = state.opponents.filter((opponent) => opponent.seat === pending.fromSeat);
  if (rivers.length !== 1 || rivers[0]!.discards.at(-1) !== pending.tile)
    throw new Error("Pending discard marked inRiver must match its opponent river tail");
  return [];
}

export function knownTiles(state: GameState): GameTile[] {
  return [
    ...state.hand,
    ...(state.draw ? [state.draw] : []),
    ...state.doraIndicators,
    ...state.ownDiscards,
    ...state.melds.flatMap((meld) => meld.tiles),
    ...state.visibleTiles,
    ...state.opponents.flatMap((opponent) => opponent.discards),
    ...state.opponents.flatMap((opponent) => opponent.melds?.flatMap((meld) => meld.tiles) ?? []),
    ...pendingTileOutsideRiver(state),
  ];
}

export function knownTilesOutsideHand(state: GameState): GameTile[] {
  return [
    ...state.doraIndicators,
    ...state.ownDiscards,
    ...state.melds.flatMap((meld) => meld.tiles),
    ...state.visibleTiles,
    ...state.opponents.flatMap((opponent) => opponent.discards),
    ...state.opponents.flatMap((opponent) => opponent.melds?.flatMap((meld) => meld.tiles) ?? []),
    ...pendingTileOutsideRiver(state),
  ];
}

export function parseGameState(input: unknown): GameState {
  const state = gameStateSchema.parse(input);
  assertSanmaConsistency(state);
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
  assertTilesAvailable(knownTiles(state), state.rules);
  toCounts(knownTiles(state));
  return state;
}

export function parsePublicGameState(input: unknown): PublicGameState {
  const state = publicGameStateSchema.parse(input);
  assertSanmaConsistency(state);
  assertHighConfidencePublicState(state);
  if (state.phase === "reaction" && !state.pendingDiscard) throw new Error("Reaction state requires pendingDiscard");
  if (state.melds.length > 0 && state.melds.length !== state.openMelds) throw new Error("melds length must equal openMelds");
  // Publicly represented tiles still have to obey the four-copy invariant,
  // independently of the concealed hand that will be recognized later.
  const publicTiles = [
    ...state.doraIndicators,
    ...state.ownDiscards,
    ...state.melds.flatMap((meld) => meld.tiles),
    ...state.visibleTiles,
    ...state.opponents.flatMap((opponent) => opponent.discards),
    ...state.opponents.flatMap((opponent) => opponent.melds?.flatMap((meld) => meld.tiles) ?? []),
    ...pendingTileOutsideRiver(state),
  ];
  assertTilesAvailable(publicTiles, state.rules);
  toCounts(publicTiles);
  return state;
}
