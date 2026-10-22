import type { GameState } from "../game/state.js";
import { TILE_NAMES, isTerminalOrHonor, normalizeTile, tileIndex, toCounts, type Tile } from "../game/tiles.js";
import { standardWinningShapes, type WinningShape } from "../game/winningShapes.js";
import type { DiscardEvaluation } from "../game/ukeire.js";

export interface OpenGroup {
  type: "sequence" | "triplet";
  tiles: Tile[];
  concealed: boolean;
  kan: boolean;
}
type Group = OpenGroup;
export interface OpenWinningWait {
  tile: Tile;
  // Supplied by the candidate evaluation; not additional tile recognition.
  remaining: number;
  // Existence witnesses across decompositions, not a simultaneous scoring
  // combination. Never add these names to calculate han or expected points.
  ronYaku: string[];
  tsumoYaku: string[];
}
export interface OpenTenpaiYaku {
  scope: "ordinary_open_hand_without_situational_yaku";
  waits: OpenWinningWait[];
  knownDiscardFuriten: boolean;
  ronUkeire: number;
  tsumoUkeire: number;
}

export function knownOpenGroups(state: GameState): Group[] | undefined {
  if (state.openMelds === 0 || state.melds.length !== state.openMelds
    || state.melds.every(meld => meld.type === "ankan") || !/^(east|south|west|north)_[1-4]$/.test(state.round)) return;
  const groups: Group[] = [];
  for (const meld of state.melds) {
    if (meld.tiles.length < 3 || meld.tiles.length > 4) return;
    const tiles = meld.tiles.map(normalizeTile).sort((a, b) => tileIndex(a) - tileIndex(b));
    const start = tileIndex(tiles[0]!);
    const sequence = meld.type === "chi";
    const kan = !["chi", "pon"].includes(meld.type);
    if (sequence ? tiles.length !== 3 || start >= 27 || start % 9 > 6
      || tileIndex(tiles[1]!) !== start + 1 || tileIndex(tiles[2]!) !== start + 2
      : tiles.length !== (kan ? 4 : 3) || !tiles.every(tile => tile === tiles[0])) return;
    groups.push({ type: sequence ? "sequence" : "triplet", tiles, concealed: meld.type === "ankan", kan });
  }
  return groups;
}

export function ordinaryOpenShapeYaku(shape: WinningShape, exposed: Group[], winner: Tile, state: GameState,
  tsumo: boolean, winningGroupIndex?: number): string[] {
  const groups: Group[] = [...exposed, ...shape.groups.map(group => ({ ...group, concealed: true, kan: false }))];
  const tiles = [shape.pair, shape.pair, ...groups.flatMap(group => group.tiles)];
  const yaku = new Set<string>();
  const trips = groups.filter(group => group.type === "triplet");
  const sequences = groups.filter(group => group.type === "sequence");
  const winds = { east: "E", south: "S", west: "W", north: "N" } as const;
  const roundWind = winds[state.round.split("_")[0] as keyof typeof winds];
  const valueHonors = new Set<string>(["P", "F", "C", winds[state.seat], roundWind]);
  for (const group of trips) if (valueHonors.has(group.tiles[0]!)) yaku.add(`yakuhai:${group.tiles[0]}`);
  if (tiles.every(tile => !isTerminalOrHonor(tileIndex(tile)))) yaku.add("tanyao");
  if (sequences.length === 0) yaku.add("toitoi");
  if (tiles.every(tile => isTerminalOrHonor(tileIndex(tile)))
    && tiles.some(tile => tileIndex(tile) < 27) && tiles.some(tile => tileIndex(tile) >= 27)) yaku.add("honroutou");
  const suits = new Set(tiles.filter(tile => tileIndex(tile) < 27).map(tile => tile[1]));
  const honors = tiles.some(tile => tileIndex(tile) >= 27);
  if (suits.size === 1) yaku.add(honors ? "honitsu" : "chinitsu");
  if (tiles.every(tile => ["2s", "3s", "4s", "6s", "8s", "F"].includes(tile))) yaku.add("ryuuiisou");
  if (sequences.length && isTerminalOrHonor(tileIndex(shape.pair))
    && groups.every(group => group.tiles.some(tile => isTerminalOrHonor(tileIndex(tile))))) {
    yaku.add(honors ? "chanta" : "junchan");
  }
  for (let start = 0; start <= 6; start++) {
    if ([0, 9, 18].every(suit => sequences.some(group => tileIndex(group.tiles[0]!) === suit + start))) yaku.add("sanshoku_doujun");
  }
  for (let rank = 0; rank < 9; rank++) {
    if ([0, 9, 18].every(suit => trips.some(group => tileIndex(group.tiles[0]!) === suit + rank))) yaku.add("sanshoku_doukou");
  }
  for (const suit of [0, 9, 18]) {
    if ([0, 3, 6].every(start => sequences.some(group => tileIndex(group.tiles[0]!) === suit + start))) yaku.add("ittsuu");
  }
  if (["P", "F", "C"].includes(shape.pair)
    && trips.filter(group => ["P", "F", "C"].includes(group.tiles[0]!)).length >= 2) yaku.add("shousangen");
  if (groups.filter(group => group.kan).length === 3) yaku.add("sankantsu");
  // A ron-completed triplet is not concealed for sanankou. If the winning
  // tile can instead be assigned to a sequence/pair in this decomposition,
  // the triplet can remain concealed; all decompositions are considered.
  const alternative = shape.pair === winner || shape.groups.some(group => group.type === "sequence" && group.tiles.includes(winner));
  const concealedTriplets = groups.filter((group, index) => group.type === "triplet" && group.concealed
    && (group.kan || tsumo || (winningGroupIndex === undefined
      ? alternative || !group.tiles.includes(winner) : index !== winningGroupIndex))).length;
  if (concealedTriplets >= 3) yaku.add("sanankou");
  return [...yaku];
}

/** Exact ordinary open-hand yaku existence, not a full score or win forecast.
 * Dora never creates yaku. Haitei/houtei/rinshan/chankan are deliberately absent.
 * Incomplete meld/wind evidence returns unknown rather than certifying no yaku.
 */
export function openTenpaiYaku(candidate: DiscardEvaluation, state: GameState): OpenTenpaiYaku | undefined {
  if (candidate.shanten !== 0) return;
  const exposed = knownOpenGroups(state);
  if (!exposed) return;
  const concealed = [...state.hand, ...(state.draw ? [state.draw] : [])].map(normalizeTile);
  const discardIndex = concealed.indexOf(normalizeTile(candidate.tile));
  if (discardIndex < 0) return;
  concealed.splice(discardIndex, 1);
  if (concealed.length !== 13 - state.openMelds * 3) return;
  let counts: number[];
  try { counts = toCounts([...concealed, ...exposed.flatMap(group => group.tiles)]); }
  catch { return; }
  const waits: OpenWinningWait[] = [];
  for (const tile of TILE_NAMES) {
    if (counts[tileIndex(tile)]! >= 4) continue;
    const shapes = standardWinningShapes([...concealed, tile], state.openMelds);
    if (!shapes.length) continue;
    waits.push({ tile, remaining: candidate.effectiveTiles.find(wait => wait.tile === tile)?.remaining ?? 0,
      ronYaku: [...new Set(shapes.flatMap(shape => ordinaryOpenShapeYaku(shape, exposed, tile, state, false)))],
      tsumoYaku: [...new Set(shapes.flatMap(shape => ordinaryOpenShapeYaku(shape, exposed, tile, state, true)))] });
  }
  // Only represented own discards establish this flag. Missing called-discard
  // history is not certified unfuriten; UI ron legality remains authoritative.
  const discarded = new Set([...state.ownDiscards, candidate.tile].map(normalizeTile));
  const knownDiscardFuriten = waits.some(wait => discarded.has(wait.tile));
  return { scope: "ordinary_open_hand_without_situational_yaku", waits, knownDiscardFuriten,
    ronUkeire: knownDiscardFuriten ? 0 : waits.reduce((sum, wait) => sum + (wait.ronYaku.length ? wait.remaining : 0), 0),
    tsumoUkeire: waits.reduce((sum, wait) => sum + (wait.tsumoYaku.length ? wait.remaining : 0), 0) };
}
