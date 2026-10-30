import { assertYonmaEvaluation } from "../game/state.js";
import { knownTiles, type GameState } from "../game/state.js";
import { doraFromIndicator, isRedTile, isTerminalOrHonor, normalizeTile, parseGameTile, tileIndex, toCounts,
  type GameTile, type Tile } from "../game/tiles.js";
import { standardWinningShapes, type WinningShape } from "../game/winningShapes.js";
import type { DiscardEvaluation } from "../game/ukeire.js";
import { knownOpenGroups, openTenpaiYaku, ordinaryOpenShapeYaku, type OpenGroup } from "./openTenpaiYaku.js";

export interface OpenWinningScore {
  han: number;
  fu: number;
  yakuman: number;
  doraHan: number;
  yaku: string[];
  main: number;
  additional: number;
  total: number;
}
export interface OpenScoredWait {
  tile: GameTile;
  remaining: number;
  ron?: OpenWinningScore;
  tsumo?: OpenWinningScore;
}
export interface OpenTenpaiScore {
  scope: "ordinary_open_hand_without_situational_yaku_honba_or_deposits";
  redFivesPerSuit: 1;
  knownDiscardFuriten: boolean;
  waits: OpenScoredWait[];
  ronUkeire: number;
  tsumoUkeire: number;
  winningUkeire: number;
  // Mean over unseen winning tile copies, using the smaller total payment
  // when both winning modes score. This is not a calibrated outcome EV.
  conditionalConservativePoints: number;
}

const WIND = { east: "E", south: "S", west: "W", north: "N" } as const;
const HAN: Record<string, number> = { tanyao: 1, toitoi: 2, honroutou: 2, honitsu: 2, chinitsu: 5,
  chanta: 1, junchan: 2, sanshoku_doujun: 1, sanshoku_doukou: 2, ittsuu: 1,
  shousangen: 2, sankantsu: 2, sanankou: 2 };
const roundWind = (state: GameState) => WIND[state.round.split("_")[0] as keyof typeof WIND];
const terminal = (tile: Tile) => isTerminalOrHonor(tileIndex(tile));

function payments(basic: number, dealer: boolean, tsumo: boolean) {
  const up = (value: number) => Math.ceil(value / 100) * 100;
  const main = up(basic * (tsumo ? 2 : dealer ? 6 : 4));
  const additional = tsumo ? up(basic * (dealer ? 2 : 1)) : 0;
  return { main, additional, total: tsumo ? main + additional * 2 : main };
}

function scoreAssignment(shape: WinningShape, exposed: OpenGroup[], winningGroup: number,
  winner: GameTile, physical: GameTile[], state: GameState, tsumo: boolean): OpenWinningScore | undefined {
  const face = normalizeTile(winner);
  const groups: OpenGroup[] = [...exposed, ...shape.groups.map(group => ({ ...group, concealed: true, kan: false }))];
  const tiles = physical.map(normalizeTile);
  const trips = groups.filter(group => group.type === "triplet");
  const tripFaces = trips.map(group => group.tiles[0]!);
  const yakumanYaku: string[] = [];
  if (["P", "F", "C"].every(tile => tripFaces.includes(tile as Tile))) yakumanYaku.push("daisangen");
  const windTriplets = tripFaces.filter(tile => ["E", "S", "W", "N"].includes(tile)).length;
  if (windTriplets === 4) yakumanYaku.push("daisuushi", "daisuushi_double");
  else if (windTriplets === 3 && ["E", "S", "W", "N"].includes(shape.pair)) yakumanYaku.push("shousuushi");
  if (tiles.every(tile => tileIndex(tile) >= 27)) yakumanYaku.push("tsuuiisou");
  if (tiles.every(tile => tileIndex(tile) < 27 && terminal(tile))) yakumanYaku.push("chinroutou");
  if (tiles.every(tile => ["2s", "3s", "4s", "6s", "8s", "F"].includes(tile))) yakumanYaku.push("ryuuiisou");
  if (groups.filter(group => group.kan).length === 4) yakumanYaku.push("suukantsu");
  const yaku = ordinaryOpenShapeYaku(shape, exposed, face, state, tsumo, winningGroup);
  let han = yaku.reduce((sum, name) => sum + (name.startsWith("yakuhai:")
    ? Number(name.slice(8) === WIND[state.seat]) + Number(name.slice(8) === roundWind(state))
      + Number(["P", "F", "C"].includes(name.slice(8))) : HAN[name] ?? 0), 0);
  const yakuman = yakumanYaku.length;
  if (!yakuman && han === 0) return;
  const indicators = state.doraIndicators.map((indicator) => doraFromIndicator(indicator, state.rules));
  const doraHan = yakuman ? 0 : physical.reduce((sum, tile) => sum + Number(isRedTile(tile))
    + indicators.filter(indicator => indicator === normalizeTile(tile)).length, 0);
  han = yakuman ? yakuman * 13 : han + doraHan;
  let fu = 20 + Number(tsumo) * 2;
  if (["P", "F", "C"].includes(shape.pair)) fu += 2;
  if (shape.pair === WIND[state.seat]) fu += 2;
  if (shape.pair === roundWind(state)) fu += 2;
  groups.forEach((group, index) => {
    if (group.type !== "triplet") return;
    const concealed = group.concealed && (tsumo || group.kan || index !== winningGroup);
    fu += (group.kan ? 8 : 2) * (concealed ? 2 : 1) * (terminal(group.tiles[0]!) ? 2 : 1);
  });
  if (winningGroup === -1) fu += 2;
  else {
    const group = groups[winningGroup]!;
    const start = tileIndex(group.tiles[0]!);
    const win = tileIndex(face);
    if (group.type === "sequence" && (win === start + 1
      || start % 9 === 0 && win === start + 2 || start % 9 === 6 && win === start)) fu += 2;
  }
  fu = Math.max(30, Math.ceil(fu / 10) * 10);
  const basic = yakuman ? 8000 * yakuman : han >= 13 ? 8000 : han >= 11 ? 6000
    : han >= 8 ? 4000 : han >= 6 ? 3000 : han >= 5 ? 2000 : Math.min(2000, fu * 2 ** (han + 2));
  return { han, fu, yakuman, doraHan, yaku: yakuman ? yakumanYaku : yaku,
    ...payments(basic, state.seat === "east", tsumo) };
}

/** Score one explicitly specified physical winning tile. Open hands only;
 * no situational yaku, ura, honba, deposits, pao or payment responsibility.
 * Double daisuushi and capped counted yakuman match the standard game setup.
 */
export function scoreOpenWinningTile(concealed: readonly GameTile[], winner: GameTile,
  state: GameState, tsumo: boolean): OpenWinningScore | undefined {
  assertYonmaEvaluation(state);
  const exposed = knownOpenGroups(state);
  if (!exposed || concealed.length !== 13 - state.openMelds * 3) return;
  const physical = [...concealed, winner, ...state.melds.flatMap(meld => meld.tiles)];
  try { toCounts(physical); } catch { return; }
  for (const suit of ["m", "p", "s"]) {
    if (physical.filter(tile => tile === `0${suit}`).length > 1
      || physical.filter(tile => tile === `5${suit}`).length > 3) return;
  }
  const scores: OpenWinningScore[] = [];
  for (const shape of standardWinningShapes([...concealed, winner], state.openMelds)) {
    const positions = shape.pair === normalizeTile(winner) ? [-1] : [];
    shape.groups.forEach((group, index) => {
      if (group.tiles.includes(normalizeTile(winner))) positions.push(exposed.length + index);
    });
    for (const position of positions) {
      const score = scoreAssignment(shape, exposed, position, winner, physical, state, tsumo);
      if (score) scores.push(score);
    }
  }
  return scores.sort((a, b) => b.total - a.total || b.han - a.han || b.fu - a.fu)[0];
}

export function scoreOpenTenpai(candidate: DiscardEvaluation, state: GameState): OpenTenpaiScore | undefined {
  assertYonmaEvaluation(state);
  const existence = openTenpaiYaku(candidate, state);
  if (!existence) return;
  const concealed = [...state.hand, ...(state.draw ? [state.draw] : [])].map(parseGameTile);
  const index = concealed.indexOf(candidate.tile);
  if (index < 0) return;
  concealed.splice(index, 1);
  let seen: GameTile[];
  try { seen = knownTiles(state); } catch { return; }
  for (const suit of ["m", "p", "s"]) {
    if (seen.filter(tile => tile === `0${suit}`).length > 1
      || seen.filter(tile => tile === `5${suit}`).length > 3) return;
  }
  const waits: OpenScoredWait[] = [];
  for (const wait of existence.waits) {
    let variants: Array<{ tile: GameTile; remaining: number }> = [{ tile: wait.tile, remaining: wait.remaining }];
    if (wait.tile.startsWith("5")) {
      const red = `0${wait.tile[1]}` as GameTile;
      const normalRemaining = 3 - seen.filter(tile => tile === wait.tile).length;
      const redRemaining = 1 - seen.filter(tile => tile === red).length;
      if (normalRemaining < 0 || redRemaining < 0 || normalRemaining + redRemaining !== wait.remaining) return;
      variants = [{ tile: wait.tile, remaining: normalRemaining }, { tile: red, remaining: redRemaining }];
    }
    for (const variant of variants) {
      const ron = scoreOpenWinningTile(concealed, variant.tile, state, false);
      const tsumo = scoreOpenWinningTile(concealed, variant.tile, state, true);
      waits.push({ ...variant, ...(ron ? { ron } : {}), ...(tsumo ? { tsumo } : {}) });
    }
  }
  const ronUkeire = existence.knownDiscardFuriten ? 0 : waits.reduce((sum, wait) => sum + (wait.ron ? wait.remaining : 0), 0);
  const tsumoUkeire = waits.reduce((sum, wait) => sum + (wait.tsumo ? wait.remaining : 0), 0);
  let weighted = 0, winningUkeire = 0;
  for (const wait of waits) {
    const points = [existence.knownDiscardFuriten ? undefined : wait.ron?.total, wait.tsumo?.total]
      .filter((value): value is number => value !== undefined);
    if (points.length && wait.remaining > 0 && (!existence.knownDiscardFuriten && wait.ron || wait.tsumo)) {
      weighted += Math.min(...points) * wait.remaining;
      winningUkeire += wait.remaining;
    }
  }
  return { scope: "ordinary_open_hand_without_situational_yaku_honba_or_deposits", redFivesPerSuit: 1,
    knownDiscardFuriten: existence.knownDiscardFuriten, waits, ronUkeire, tsumoUkeire, winningUkeire,
    conditionalConservativePoints: winningUkeire ? Math.round(weighted / winningUkeire) : 0 };
}
