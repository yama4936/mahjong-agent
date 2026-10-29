import { decideForceAutoWithJevDeadline } from "../agent/decision.js";
import type { GameState } from "../game/state.js";
import type { JevClient, JevHandPlan } from "../jev/client.js";

// This precedes the first gesture; its IPC/pixel work is separate from the
// time Python still needs to observe and activate the raised tile afterwards.
const ipcAndPixelReserveMs = 350;
const discardSelectionReserveMs = 650;

export interface SelfTurnBudgetInput {
  clickBudgetMs: number;
  captureAgeBeforeDecisionMs: number;
  forceAutoDeadlineMs: number;
  processingElapsedMs: number;
  actionDeadlineRemainingMs?: number | undefined;
  actionBudgetRemainingMs?: number | undefined;
  discardSelectionReserveMs?: number | undefined;
}

export function selfTurnDecisionBudget(input: SelfTurnBudgetInput) {
  const bounded = input.discardSelectionReserveMs !== undefined;
  if (bounded && input.discardSelectionReserveMs !== discardSelectionReserveMs) {
    throw new Error("invalid force-auto discard selection reserve");
  }
  if (bounded && (!Number.isFinite(input.actionBudgetRemainingMs)
      || !Number.isFinite(input.actionDeadlineRemainingMs))) {
    throw new Error("force-auto self turn requires original action and deadline remaining time");
  }
  if (!Number.isFinite(input.processingElapsedMs) || input.processingElapsedMs < 0
      || !Number.isFinite(input.captureAgeBeforeDecisionMs) || input.captureAgeBeforeDecisionMs < 0) {
    throw new Error("invalid force-auto self-turn elapsed time");
  }
  const selectionReserve = bounded ? discardSelectionReserveMs : 0;
  const totalReserveMs = ipcAndPixelReserveMs + selectionReserve;
  const imageRemainingMs = input.clickBudgetMs - input.captureAgeBeforeDecisionMs;
  // Old resident clients retain their original request semantics. Explicit
  // bounded requests pay every millisecond of resident preprocessing, too.
  const actionBudgetRemainingMs = bounded
    ? input.actionBudgetRemainingMs! - input.processingElapsedMs : undefined;
  const actionDeadlineRemainingMs = Number.isFinite(input.actionDeadlineRemainingMs)
    ? input.actionDeadlineRemainingMs! - (bounded ? input.processingElapsedMs : 0) : undefined;
  const remainingMs = Math.min(imageRemainingMs,
    actionBudgetRemainingMs ?? Infinity, actionDeadlineRemainingMs ?? Infinity);
  const availableMs = Math.floor(remainingMs - totalReserveMs);
  const decisionBudgetMs = bounded
    ? Math.max(0, Math.min(input.forceAutoDeadlineMs, availableMs))
    : Math.min(input.forceAutoDeadlineMs, Math.max(1, availableMs));
  return {
    preClickReserveMs: ipcAndPixelReserveMs,
    discardSelectionReserveMs: selectionReserve,
    totalReserveMs, imageRemainingMs, actionBudgetRemainingMs, actionDeadlineRemainingMs,
    remainingMs, decisionBudgetMs,
    remoteDecisionAllowed: !bounded || decisionBudgetMs > 0,
  };
}

export async function decideSelfTurnWithinBudget(
  state: GameState, budget: ReturnType<typeof selfTurnDecisionBudget>,
  options: { jev?: JevClient; handPlan?: JevHandPlan },
) {
  // A one-millisecond *remote* retry must not be lent to an expired window.
  // Local analysis stays available (including immediate ron/tsumo), and the
  // unchanged Python click guards remain authoritative before any input.
  return decideForceAutoWithJevDeadline(state, {
    ...(budget.remoteDecisionAllowed && options.jev ? { jev: options.jev } : {}),
    ...(options.handPlan ? { handPlan: options.handPlan } : {}),
    deadlineMs: budget.decisionBudgetMs > 0 ? budget.decisionBudgetMs : 1,
  });
}
