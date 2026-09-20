import type { GameState } from "../game/state.js";
import { deterministicAdvice, type AdvisorResult } from "../evaluation/advisor.js";
import { JevClient, type JevDecision } from "../jev/client.js";
import { generateLegalActions, type LegalAction } from "../game/actions.js";
import { calculateShanten } from "../game/shanten.js";
import { evaluateDiscards } from "../game/ukeire.js";

export type AgentMode = "observer" | "advisor" | "auto";

export interface DecisionResult extends AdvisorResult {
  mode: AgentMode;
  selectedActionId: string;
  jev?: JevDecision;
  executable: boolean;
  selectedAction: LegalAction;
  legalActions: LegalAction[];
}

export interface DecisionOptions {
  mode: AgentMode;
  jev?: JevClient;
  minJevConfidence?: number;
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
      jev = await options.jev.chooseDiscard(state, base.candidates);
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
    executable: options.mode === "auto" && safety.allowed,
  };
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
    executable: options.mode === "auto" && safety.allowed,
  };
}

function removeSafetyReason(reasons: string[], reason: string): void {
  for (let index = reasons.indexOf(reason); index >= 0; index = reasons.indexOf(reason)) reasons.splice(index, 1);
}

type CallAction = LegalAction & { action: "chi" | "pon" | "minkan"; consumedTiles: string[] };

function callImprovement(state: GameState, action: CallAction): number {
  const remaining = [...state.hand];
  for (const tile of action.consumedTiles) {
    const index = remaining.findIndex((value) => value === tile || (value[1] === tile[1] && (value[0] === "0" ? "5" : value[0]) === (tile[0] === "0" ? "5" : tile[0])));
    if (index < 0) return Number.NEGATIVE_INFINITY;
    remaining.splice(index, 1);
  }
  if (action.action === "minkan") return calculateShanten(remaining, state.openMelds + 1).shanten;
  const candidates = evaluateDiscards(remaining, [], state.openMelds + 1);
  return candidates[0]?.shanten ?? Number.POSITIVE_INFINITY;
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
  let selectedAction: LegalAction = initialAction;

  if (selectedAction.action !== "ron" && !state.opponents.some((opponent) => opponent.riichi)) {
    const currentShanten = calculateShanten(state.hand, state.openMelds).shanten;
    const calls = legalActions.filter((action): action is CallAction =>
      action.action === "chi" || action.action === "pon" || action.action === "minkan");
    const improved = calls
      .map((action) => ({ action, shanten: callImprovement(state, action) }))
      .filter((candidate) => candidate.shanten < currentShanten)
      .sort((left, right) => left.shanten - right.shanten || (left.action.action === "pon" ? -1 : 1));
    if (improved[0]) selectedAction = improved[0].action;
  }

  const sameButton = legalActions.filter((action) => action.action === selectedAction.action);
  if ((selectedAction.action === "chi" || selectedAction.action === "pon" || selectedAction.action === "minkan") && sameButton.length > 1) {
    safetyReasons.push("ambiguous_call_variant");
  }
  const confidence = selectedAction.action === "ron" ? 1 : selectedAction.action === "pass" ? 0.9 : 0.75;
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
    executable: options.mode === "auto" && safety.allowed,
  };
}
