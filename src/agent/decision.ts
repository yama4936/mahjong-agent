import type { GameState } from "../game/state.js";
import { deterministicAdvice, type AdvisorResult } from "../evaluation/advisor.js";
import { JevClient, type JevDecision, type JevHandPlan } from "../jev/client.js";
import { generateLegalActions, type LegalAction } from "../game/actions.js";
import { calculateShanten } from "../game/shanten.js";
import { evaluateDiscards } from "../game/ukeire.js";
import { isTerminalOrHonor, normalizeTile, tileIndex } from "../game/tiles.js";

export type AgentMode = "observer" | "advisor" | "auto" | "force-auto";

export interface DecisionResult extends AdvisorResult {
  mode: AgentMode;
  selectedActionId: string;
  jev?: JevDecision;
  executable: boolean;
  selectedAction: LegalAction;
  legalActions: LegalAction[];
  arbitration?: ForceAutoArbitration;
  handPlan: StrategyHandPlan;
  callAssessments?: CallAssessment[];
}

export interface StrategyHandPlan {
  primaryTarget: string;
  secondaryTarget?: string;
  callsAllowed: boolean;
  requiredTiles: string[];
  estimatedPoints: number;
  phase: "early_efficiency" | "middle_balance" | "late_tenpai_defense";
  placement: { rank: number; scoreGapToLeader?: number; allLast: boolean };
  changeReason: string;
}

export interface CallAssessment {
  actionId: string;
  action: "chi" | "pon" | "minkan";
  currentShanten: number;
  resultingShanten: number;
  shantenImprovement: number;
  ukeire: number;
  confirmedYaku: string[];
  candidateYaku: string[];
  estimatedPoints: number;
  defenseLoss: number;
  approved: boolean;
  reasons: string[];
}

export interface DecisionOptions {
  mode: AgentMode;
  jev?: JevClient;
  minJevConfidence?: number;
  signal?: AbortSignal;
  handPlan?: JevHandPlan;
}

export interface ForceAutoArbitration {
  strategy: "jev_deadline_with_local_fallback";
  deadlineMs: number;
  selectedSource: "jev" | "local";
  elapsedMs: number;
  fallbackReason?: "jev_unavailable" | "deadline_exceeded" | "jev_error" | "local_immediate_action";
}

function placementContext(state: GameState): StrategyHandPlan["placement"] {
  const own = state.scores[state.seat];
  const known = Object.values(state.scores);
  const sorted = [...known].sort((a, b) => b - a);
  const rank = own === undefined || sorted.length < 4 ? 2 : sorted.indexOf(own) + 1;
  const leader = sorted[0];
  return {
    rank,
    ...(own !== undefined && leader !== undefined ? { scoreGapToLeader: leader - own } : {}),
    allLast: /^(south|west|north)_4$/i.test(state.round),
  };
}

function strategyPhase(turn: number): StrategyHandPlan["phase"] {
  if (turn <= 6) return "early_efficiency";
  if (turn <= 11) return "middle_balance";
  return "late_tenpai_defense";
}

function valueHonors(state: GameState): Set<string> {
  const roundWind = state.round.match(/^(east|south|west|north)/i)?.[1]?.[0]?.toUpperCase();
  return new Set(["P", "F", "C", state.seat[0]!.toUpperCase(), ...(roundWind ? [roundWind] : [])]);
}

function inferPlanTargets(state: GameState): Array<{ id: string; score: number }> {
  const tiles = [...state.hand, ...(state.draw ? [state.draw] : [])].map(normalizeTile);
  const counts = new Map<string, number>();
  for (const tile of tiles) counts.set(tile, (counts.get(tile) ?? 0) + 1);
  const honors = tiles.filter((tile) => tile.length === 1);
  const terminals = tiles.filter((tile) => tile.length > 1 && isTerminalOrHonor(tileIndex(tile)));
  const pairs = [...counts.values()].filter((count) => count >= 2).length;
  const plans = [{ id: state.openMelds === 0 ? "riichi/efficient_standard" : "efficient_standard", score: 10 }];
  if (honors.length + terminals.length <= 3) plans.push({ id: "tanyao", score: 15 - honors.length - terminals.length });
  const yakuhaiPairs = [...valueHonors(state)].filter((tile) => (counts.get(tile) ?? 0) >= 2);
  if (yakuhaiPairs.length) plans.push({ id: `yakuhai:${yakuhaiPairs.join(",")}`, score: 18 + yakuhaiPairs.length });
  if (pairs >= 5 && state.openMelds === 0) plans.push({ id: "chiitoitsu", score: 12 + pairs });
  if (pairs >= 4) plans.push({ id: "toitoi", score: 10 + pairs });
  for (const suit of ["m", "p", "s"]) {
    const suited = tiles.filter((tile) => tile.endsWith(suit)).length;
    if (suited + honors.length >= tiles.length - 2) plans.push({ id: `honitsu_${suit}`, score: suited + honors.length });
  }
  return plans.sort((left, right) => right.score - left.score);
}

export function buildStrategyHandPlan(state: GameState): StrategyHandPlan {
  const phase = strategyPhase(state.turn);
  const placement = placementContext(state);
  const targets = inferPlanTargets(state);
  const evaluated = state.phase === "self_turn"
    ? evaluateDiscards([...state.hand, ...(state.draw ? [state.draw] : [])], [], state.openMelds)
    : [];
  const requiredTiles = [...new Set((evaluated[0]?.effectiveTiles ?? []).map(({ tile }) => tile))].slice(0, 8);
  const primary = targets[0]?.id ?? "efficient_standard";
  const callsAllowed = !state.riichiDeclared && !(phase === "late_tenpai_defense" && placement.rank === 1);
  return {
    primaryTarget: primary,
    ...(targets[1] ? { secondaryTarget: targets[1].id } : {}),
    callsAllowed,
    requiredTiles,
    estimatedPoints: primary.startsWith("honitsu") ? 3900 : primary.startsWith("yakuhai") ? 2000 : state.openMelds === 0 ? 2600 : 1000,
    phase,
    placement,
    changeReason: phase === "early_efficiency"
      ? "1-6巡目はシャンテンと受入枚数を優先"
      : phase === "middle_balance" ? "7-11巡目は速度・打点・安全度を均衡"
        : placement.allLast && placement.rank === 4 ? "オーラスのラス目なのでテンパイ到達を優先"
          : placement.rank === 1 ? "終盤のトップ目なので放銃回避を強化" : "終盤なのでテンパイ価値と守備を強化",
  };
}

function publicStateSafetyReasons(state: GameState): string[] {
  const reasons: string[] = [];
  if (state.round === "unknown") reasons.push("round_not_recognized");
  if (state.doraIndicators.length === 0) reasons.push("dora_not_recognized");
  if (state.remainingTiles === undefined) reasons.push("remaining_tiles_not_recognized");
  const seats = ["east", "south", "west", "north"] as const;
  if (seats.some((seat) => state.scores[seat] === undefined)) reasons.push("scores_incomplete");
  const opponentSeats = state.opponents.map((opponent) => opponent.seat);
  if (opponentSeats.length !== 3 || new Set(opponentSeats).size !== 3 || opponentSeats.includes(state.seat)) {
    reasons.push("opponents_incomplete_or_inconsistent");
  }
  return reasons;
}

export async function decide(state: GameState, options: DecisionOptions): Promise<DecisionResult> {
  const legalActions = generateLegalActions(state);
  if (state.phase === "reaction") return decideReaction(state, legalActions, options);

  const base = deterministicAdvice(state);
  const immediateWin = legalActions.find((action) => action.action === "tsumo");
  if (immediateWin) return decideImmediateSelfAction(state, base, legalActions, immediateWin, options);
  const kan = legalActions.find((action): action is LegalAction & { action: "ankan" | "kakan"; consumedTiles: string[] } =>
    action.action === "ankan" || action.action === "kakan");
  if (kan && shouldRecommendKan(state, kan)) return decideImmediateSelfAction(state, base, legalActions, kan, options);
  const minJevConfidence = options.minJevConfidence ?? 0.55;
  let selected = base.candidates[0]!;
  let confidence = base.confidence;
  let source: "deterministic" | "jev" = "deterministic";
  let jev: JevDecision | undefined;
  const safetyReasons = [...base.safety.reasons];

  if (options.mode === "auto" && state.publicStateConfidence < 0.98) {
    safetyReasons.push("public_state_confidence_below_threshold");
  }
  if (options.mode === "auto") safetyReasons.push(...publicStateSafetyReasons(state));

  if (options.jev) {
    try {
      const underThreat = state.opponents.some((opponent) => opponent.riichi || opponent.openMelds >= 2);
      const minimumShanten = base.candidates[0]?.shanten;
      const defensible = underThreat && minimumShanten !== undefined
        ? base.candidates.filter((candidate) => candidate.shanten <= minimumShanten + 1)
        : [];
      const safestDanger = Math.min(...defensible.map((candidate) => candidate.danger ?? 1));
      const jevCandidates = underThreat && defensible.length
        ? defensible.filter((candidate) => (candidate.danger ?? 1) <= safestDanger + 0.02)
        : options.mode === "force-auto" && minimumShanten !== undefined
          ? base.candidates.filter((candidate) => candidate.shanten === minimumShanten)
          : base.candidates;
      jev = await options.jev.chooseDiscard(state, jevCandidates, options.signal, options.handPlan);
      const candidate = base.candidates.find((item) => item.actionId === jev!.actionId);
      if (!candidate) throw new Error("Jev selected an unknown candidate");
      selected = candidate;
      confidence = jev.confidence;
      source = "jev";
      if (jev.confidence < minJevConfidence) safetyReasons.push("jev_confidence_below_threshold");
    } catch (error) {
      safetyReasons.push(`jev_error:${error instanceof Error ? error.message : String(error)}`);
    }
  } else if (options.mode === "auto") {
    safetyReasons.push("jev_required_for_auto_mode");
  }

  let selectedAction: LegalAction = legalActions.find((action) => action.id === selected.actionId)
    ?? { id: selected.actionId, action: "discard", tile: selected.tile };
  const winAction = legalActions.find((action) => action.action === "tsumo");
  if (winAction) {
    selectedAction = winAction;
    selected = { ...selected, actionId: winAction.id };
    confidence = 1;
    source = "deterministic";
    removeSafetyReason(safetyReasons, "jev_required_for_auto_mode");
    removeSafetyReason(safetyReasons, "jev_confidence_below_threshold");
  } else {
    const riichi = legalActions.find((action) => action.action === "riichi" && action.tile === selected.tile);
    if (riichi && (state.remainingTiles === undefined || state.remainingTiles >= 4)) selectedAction = riichi;
  }

  const safety = { allowed: safetyReasons.length === 0, reasons: safetyReasons };
  return {
    ...base,
    tile: selected.tile,
    confidence,
    source,
    safety,
    mode: options.mode,
    selectedActionId: selectedAction.id,
    selectedAction,
    legalActions,
    ...(jev ? { jev } : {}),
    executable: options.mode === "force-auto" || (options.mode === "auto" && safety.allowed),
    handPlan: buildStrategyHandPlan(state),
  };
}

/**
 * Keep a complete deterministic force-auto decision ready while Jev gets a
 * short opportunity to replace it. A slow or failed remote request must never
 * consume the rest of a Mahjong Soul turn clock.
 */
export async function decideForceAutoWithJevDeadline(
  state: GameState,
  options: { jev?: JevClient; deadlineMs?: number; handPlan?: JevHandPlan },
): Promise<DecisionResult> {
  const deadlineMs = options.deadlineMs ?? 2_300;
  if (!Number.isFinite(deadlineMs) || deadlineMs <= 0) throw new Error("Jev deadline must be positive");
  const startedAt = performance.now();
  const local = await decide(state, { mode: "force-auto" });
  const withArbitration = (
    decision: DecisionResult,
    selectedSource: "jev" | "local",
    fallbackReason?: ForceAutoArbitration["fallbackReason"],
  ): DecisionResult => ({
    ...decision,
    arbitration: {
      strategy: "jev_deadline_with_local_fallback",
      deadlineMs,
      selectedSource,
      elapsedMs: Math.max(0, Math.round(performance.now() - startedAt)),
      ...(fallbackReason ? { fallbackReason } : {}),
    },
  });

  if (!options.jev) return withArbitration(local, "local", "jev_unavailable");
  if (local.selectedAction.action === "tsumo" || local.selectedAction.action === "ron") {
    return withArbitration(local, "local", "local_immediate_action");
  }

  const remainingMs = deadlineMs - (performance.now() - startedAt);
  if (remainingMs <= 0) return withArbitration(local, "local", "deadline_exceeded");

  const controller = new AbortController();
  let timeout: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<{ kind: "timeout" }>((resolve) => {
    timeout = setTimeout(() => resolve({ kind: "timeout" }), remainingMs);
  });
  const remote = decide(state, {
    mode: "force-auto", jev: options.jev, signal: controller.signal,
    ...(options.handPlan ? { handPlan: options.handPlan } : {}),
  });
  const outcome = await Promise.race([
    remote.then((decision) => ({ kind: "decision" as const, decision })),
    deadline,
  ]);
  if (timeout) clearTimeout(timeout);
  if (outcome.kind === "timeout") {
    controller.abort();
    return withArbitration(local, "local", "deadline_exceeded");
  }
  if (outcome.decision.source !== "jev" || !outcome.decision.jev) {
    return withArbitration(local, "local", "jev_error");
  }
  return withArbitration(outcome.decision, "jev");
}

function shouldRecommendKan(state: GameState, action: LegalAction & { action: "ankan" | "kakan"; consumedTiles: string[] }): boolean {
  if (state.riichiDeclared) return false;
  const concealed = [...state.hand, ...(state.draw ? [state.draw] : [])];
  for (const tile of action.consumedTiles) {
    const index = concealed.findIndex((candidate) => candidate === tile || (candidate[1] === tile[1] && (candidate[0] === "0" ? "5" : candidate[0]) === (tile[0] === "0" ? "5" : tile[0])));
    if (index < 0) return false;
    concealed.splice(index, 1);
  }
  const before = calculateShanten([...state.hand, ...(state.draw ? [state.draw] : [])], state.openMelds).shanten;
  const after = calculateShanten(concealed, state.openMelds + (action.action === "ankan" ? 1 : 0)).shanten;
  return after <= before;
}

function decideImmediateSelfAction(
  state: GameState,
  base: AdvisorResult,
  legalActions: LegalAction[],
  selectedAction: LegalAction,
  options: DecisionOptions,
): DecisionResult {
  const safetyReasons = [...base.safety.reasons];
  if (options.mode === "auto" && state.publicStateConfidence < 0.98) safetyReasons.push("public_state_confidence_below_threshold");
  if (options.mode === "auto") safetyReasons.push(...publicStateSafetyReasons(state));
  const safety = { allowed: safetyReasons.length === 0, reasons: safetyReasons };
  return {
    ...base,
    recommendedAction: selectedAction.action,
    confidence: 1,
    source: "deterministic",
    safety,
    mode: options.mode,
    selectedActionId: selectedAction.id,
    selectedAction,
    legalActions,
    executable: options.mode === "force-auto" || (options.mode === "auto" && safety.allowed),
    handPlan: buildStrategyHandPlan(state),
  };
}

function removeSafetyReason(reasons: string[], reason: string): void {
  for (let index = reasons.indexOf(reason); index >= 0; index = reasons.indexOf(reason)) reasons.splice(index, 1);
}

type CallAction = LegalAction & { action: "chi" | "pon" | "minkan"; consumedTiles: string[] };

function callPostDiscard(state: GameState, action: CallAction) {
  const remaining = [...state.hand];
  for (const tile of action.consumedTiles) {
    const normalized = normalizeTile(tile);
    const index = remaining.findIndex((value) => normalizeTile(value) === normalized);
    if (index < 0) return undefined;
    remaining.splice(index, 1);
  }
  if (action.action === "minkan") {
    return { shanten: calculateShanten(remaining, state.openMelds + 1).shanten, ukeire: 0, effectiveTiles: [] as string[] };
  }
  const best = evaluateDiscards(remaining, [], state.openMelds + 1)[0];
  return best && { shanten: best.shanten, ukeire: best.ukeire, effectiveTiles: best.effectiveTiles.map(({ tile }) => tile) };
}

function yakuForCall(state: GameState, action: CallAction): { confirmed: string[]; candidates: string[] } {
  const honors = valueHonors(state);
  const confirmed: string[] = [];
  const candidates: string[] = [];
  const called = normalizeTile(action.tile);
  if ((action.action === "pon" || action.action === "minkan") && honors.has(called)) confirmed.push(`yakuhai:${called}`);
  for (const meld of state.melds) {
    const tile = normalizeTile(meld.tiles[0]!);
    if (meld.type !== "chi" && honors.has(tile)) confirmed.push(`yakuhai:${tile}`);
  }
  const after = [...state.hand.filter((tile) => !action.consumedTiles.some((used) => normalizeTile(used) === normalizeTile(tile))), action.tile];
  if (after.every((tile) => !isTerminalOrHonor(tileIndex(normalizeTile(tile))))
    && state.melds.every((meld) => meld.tiles.every((tile) => !isTerminalOrHonor(tileIndex(normalizeTile(tile)))))) {
    candidates.push("tanyao");
  }
  const counts = new Map<string, number>();
  for (const tile of state.hand.map(normalizeTile)) counts.set(tile, (counts.get(tile) ?? 0) + 1);
  if ([...honors].some((tile) => (counts.get(tile) ?? 0) >= 2)) candidates.push("yakuhai");
  if (state.melds.every((meld) => meld.type !== "chi") && action.action !== "chi") candidates.push("toitoi");
  return { confirmed: [...new Set(confirmed)], candidates: [...new Set(candidates)] };
}

export function assessReactionCalls(state: GameState, legalActions: readonly LegalAction[]): CallAssessment[] {
  const currentShanten = calculateShanten(state.hand, state.openMelds).shanten;
  const plan = buildStrategyHandPlan(state);
  const threat = state.opponents.some((opponent) => opponent.riichi || opponent.openMelds >= 2);
  return legalActions.filter((action): action is CallAction =>
    action.action === "chi" || action.action === "pon" || action.action === "minkan")
    .map((action) => {
      const post = callPostDiscard(state, action);
      const resultingShanten = post?.shanten ?? Number.POSITIVE_INFINITY;
      const improvement = currentShanten - resultingShanten;
      const yaku = yakuForCall(state, action);
      const estimatedPoints = yaku.confirmed.length ? 2000 : yaku.candidates.includes("tanyao") ? 1000 : 0;
      const defenseLoss = Math.min(1, 0.12 + (threat ? 0.35 : 0) + (plan.phase === "late_tenpai_defense" ? 0.2 : 0)
        + (plan.placement.rank === 1 ? 0.18 : 0) - (plan.placement.allLast && plan.placement.rank === 4 ? 0.22 : 0));
      const reasons: string[] = [];
      if (improvement <= 0) reasons.push("no_strict_shanten_improvement");
      if (!yaku.confirmed.length && !yaku.candidates.length) reasons.push("no_viable_yaku_path");
      if (!yaku.confirmed.length && yaku.candidates.length > 0
        && state.openMelds === 0 && state.round === "unknown") {
        reasons.push("unverified_first_call_yaku");
      }
      if (!plan.callsAllowed) reasons.push("hand_plan_disallows_calls");
      if (plan.phase === "late_tenpai_defense" && resultingShanten > 0) reasons.push("late_call_does_not_reach_tenpai");
      const placementUrgency = plan.placement.allLast && plan.placement.rank === 4;
      if (threat && !placementUrgency && (resultingShanten > 0 || !yaku.confirmed.length)) reasons.push("defense_loss_under_pressure");
      return {
        actionId: action.id, action: action.action, currentShanten, resultingShanten,
        shantenImprovement: improvement, ukeire: post?.ukeire ?? 0,
        confirmedYaku: yaku.confirmed, candidateYaku: yaku.candidates,
        estimatedPoints, defenseLoss, approved: reasons.length === 0, reasons,
      };
    });
}

function reactionAdvisorShape(state: GameState): AdvisorResult {
  const fallbackTile = state.hand[0]!;
  return {
    recommendedAction: "discard",
    tile: fallbackTile,
    confidence: 0.8,
    source: "deterministic",
    candidates: [],
    safety: { allowed: state.recognitionConfidence >= 0.98, reasons: state.recognitionConfidence >= 0.98 ? [] : ["recognition_confidence_below_threshold"] },
  };
}

async function decideReaction(state: GameState, legalActions: LegalAction[], options: DecisionOptions): Promise<DecisionResult> {
  const base = reactionAdvisorShape(state);
  const safetyReasons = [...base.safety.reasons];
  if (options.mode === "auto" && state.publicStateConfidence < 0.98) safetyReasons.push("public_state_confidence_below_threshold");
  if (options.mode === "auto") safetyReasons.push(...publicStateSafetyReasons(state));

  const initialAction = legalActions.find((action) => action.action === "ron")
    ?? legalActions.find((action) => action.action === "pass")
    ?? legalActions[0];
  if (!initialAction) throw new Error("No legal reaction action");
  if (initialAction.action === "ron") {
    return decideImmediateSelfAction(state, base, legalActions, initialAction, options);
  }
  let selectedAction: LegalAction = initialAction;
  let jev: JevDecision | undefined;
  const callAssessments = assessReactionCalls(state, legalActions);

  if (!state.opponents.some((opponent) => opponent.riichi)) {
    const certified = callAssessments.filter((assessment) => assessment.approved)
      .sort((left, right) => left.resultingShanten - right.resultingShanten
        || right.ukeire - left.ukeire || right.estimatedPoints - left.estimatedPoints
        || left.defenseLoss - right.defenseLoss);
    if (certified[0]) selectedAction = legalActions.find((action) => action.id === certified[0]!.actionId)!;
  }

  if (options.jev) {
    try {
      jev = await options.jev.chooseReaction(state, legalActions, options.signal);
      const choice = legalActions.find((action) => action.id === jev!.actionId);
      if (!choice) throw new Error("Jev selected an unknown reaction");
      const callAssessment = callAssessments.find((assessment) => assessment.actionId === choice.id);
      selectedAction = callAssessment && !callAssessment.approved
        ? legalActions.find((action) => action.action === "pass") ?? initialAction
        : choice;
      if (jev.confidence < (options.minJevConfidence ?? 0.55)) safetyReasons.push("jev_confidence_below_threshold");
    } catch (error) {
      safetyReasons.push(`jev_error:${error instanceof Error ? error.message : String(error)}`);
    }
  } else if (options.mode === "auto") {
    safetyReasons.push("jev_required_for_auto_mode");
  }

  const sameButton = legalActions.filter((action) => action.action === selectedAction.action);
  if ((selectedAction.action === "chi" || selectedAction.action === "pon" || selectedAction.action === "minkan") && sameButton.length > 1) {
    safetyReasons.push("ambiguous_call_variant");
  }
  const confidence = jev?.confidence ?? (selectedAction.action === "ron" ? 1 : selectedAction.action === "pass" ? 0.9 : 0.75);
  const safety = { allowed: safetyReasons.length === 0, reasons: safetyReasons };
  return {
    ...base,
    recommendedAction: selectedAction.action,
    confidence,
    safety,
    mode: options.mode,
    selectedActionId: selectedAction.id,
    selectedAction,
    legalActions,
    ...(jev ? { jev, source: "jev" as const } : {}),
    executable: options.mode === "force-auto" || (options.mode === "auto" && safety.allowed),
    handPlan: buildStrategyHandPlan(state),
    callAssessments,
  };
}
