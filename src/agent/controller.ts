import path from "node:path";
import { mkdir, writeFile } from "node:fs/promises";
import type { Page } from "playwright";
import { decide, type AgentMode } from "./decision.js";
import { parseGameState, type PublicGameState } from "../game/state.js";
import { JevClient } from "../jev/client.js";
import { appendDecisionLog } from "../logging/replay.js";
import { captureViewport, guardedDiscard, guardedUiAction, hideAdvisorOverlay, showAdvisorOverlay, type ActionExecutionReceipt, type UiActionExecutionReceipt } from "../jantama/browser.js";
import type { ScreenLayout } from "../recognition/layout.js";
import { recognizeHand, recognizeTileSlots } from "../recognition/templateMatcher.js";
import { fingerprintTemplateDirectory } from "../recognition/templateValidator.js";
import { VitTileRecognizer } from "../recognition/vitRecognizer.js";
import { HybridTileRecognizer } from "../recognition/hybridTileRecognizer.js";
import { recognizeConfiguredPublicTilesWithVit, toPublicTileObservation, type PublicTileRecognitionRegion } from "../recognition/publicTileRecognizer.js";
import type { PublicTileRegionName } from "../recognition/layout.js";
import { availableUiActions, recognizeActionButtons, type ActionButtonMatch } from "../recognition/actionButtonRecognizer.js";
import { generateLegalActions } from "../game/actions.js";
import type { GameTile } from "../game/tiles.js";
import { layoutFromHandProposal, proposeHandLayout, proposeLiveHandLayout } from "../recognition/handLayoutProposal.js";

export interface TurnContext {
  page: Page;
  mode: AgentMode;
  layout: ScreenLayout;
  templateDirectory: string;
  actionTemplateDirectory?: string;
  artifactDirectory: string;
  publicState: PublicGameState;
  jev?: JevClient;
  vitRecognizer?: VitTileRecognizer;
  tileRecognizer?: VitTileRecognizer | HybridTileRecognizer;
  useUntrustedPublicObservation?: boolean;
}

export interface AgentLoopOptions {
  pollIntervalMs?: number;
  maxTurns?: number;
  rearmAfterUnsafeFrames?: number;
  signal?: AbortSignal;
  onStatus?: (status: { kind: "waiting" | "turn" | "error"; message: string }) => void;
}

export class TurnRearmGate {
  private armed = true;
  private unsafeFrames = 0;
  private processedSignature: string | undefined;
  private changedSignature: string | undefined;
  private changedSignatureFrames = 0;

  constructor(private readonly requiredUnsafeFrames = 3) {
    if (!Number.isInteger(requiredUnsafeFrames) || requiredUnsafeFrames < 1) throw new Error("requiredUnsafeFrames must be a positive integer");
  }

  observe(safe: boolean, signature?: string): { shouldProcess: boolean; rearmed: boolean } {
    if (!safe) {
      this.unsafeFrames += 1;
      this.changedSignature = undefined;
      this.changedSignatureFrames = 0;
      const rearmed = !this.armed && this.unsafeFrames >= this.requiredUnsafeFrames;
      if (rearmed) this.armed = true;
      return { shouldProcess: false, rearmed };
    }
    this.unsafeFrames = 0;
    if (!this.armed) {
      if (signature === undefined || signature === this.processedSignature) {
        this.changedSignature = undefined;
        this.changedSignatureFrames = 0;
        return { shouldProcess: false, rearmed: false };
      }
      if (signature !== this.changedSignature) {
        this.changedSignature = signature;
        this.changedSignatureFrames = 1;
        return { shouldProcess: false, rearmed: false };
      }
      this.changedSignatureFrames += 1;
      if (this.changedSignatureFrames < this.requiredUnsafeFrames) return { shouldProcess: false, rearmed: false };
      this.armed = true;
      this.changedSignature = undefined;
      this.changedSignatureFrames = 0;
      return { shouldProcess: false, rearmed: true };
    }
    this.armed = false;
    this.processedSignature = signature;
    this.changedSignature = undefined;
    this.changedSignatureFrames = 0;
    return { shouldProcess: true, rearmed: false };
  }

  retryCurrentFrame(): void {
    this.armed = true;
    this.unsafeFrames = 0;
    this.processedSignature = undefined;
    this.changedSignature = undefined;
    this.changedSignatureFrames = 0;
  }
}

type ModelTileRecognizer = VitTileRecognizer | HybridTileRecognizer;
type HandRecognition = Awaited<ReturnType<typeof recognizeHand>> | Awaited<ReturnType<typeof recognizeTileSlots>> | Awaited<ReturnType<ModelTileRecognizer["recognizeHand"]>>;

export function assertRecognizerAllowedForAuto(mode: AgentMode, recognition: HandRecognition): void {
  if (mode === "auto" && "backend" in recognition && (recognition.backend === "vit" || recognition.backend === "hybrid")) {
    throw new Error(`${recognition.backend} recognition is Advisor-only until an independent live holdout calibration passes`);
  }
}

export function assertPublicObservationAllowed(mode: AgentMode, useUntrustedPublicObservation: boolean): void {
  if (mode === "auto" && useUntrustedPublicObservation) {
    throw new Error("Uncalibrated public tile observations are forbidden in Auto mode");
  }
}

export async function assertTemplateSetMatchesCalibration(layout: ScreenLayout, templateDirectory: string): Promise<void> {
  if (!layout.autoOperation) return;
  if (layout.autoOperation.tileMatcher !== layout.tileMatcher || layout.autoOperation.matcherVersion !== "2") {
    throw new Error("Matcher does not match the passing calibration certificate");
  }
  const fingerprint = await fingerprintTemplateDirectory(templateDirectory);
  if (fingerprint !== layout.autoOperation.templateSetFingerprint) {
    throw new Error("Template set does not match the passing calibration certificate");
  }
}

type PublicRecognition = Partial<Record<PublicTileRegionName, PublicTileRecognitionRegion>>;

async function captureRecognition(context: TurnContext): Promise<{ image: Buffer; recognition: HandRecognition; publicRecognition?: PublicRecognition; actionMatches: ActionButtonMatch[] }> {
  const image = await captureViewport(context.page, context.layout);
  const modelRecognizer = context.tileRecognizer ?? context.vitRecognizer;
  let recognitionLayout = context.layout;
  if (modelRecognizer && context.mode === "advisor") {
    try {
      const proposal = await proposeLiveHandLayout(image);
      recognitionLayout = layoutFromHandProposal(proposal, context.layout);
    } catch {}
  }
  let recognition = modelRecognizer
    ? await modelRecognizer.recognizeHand(image, recognitionLayout)
    : context.publicState.phase === "reaction"
      ? await recognizeTileSlots(image, context.layout.handSlots, context.layout, context.templateDirectory)
      : await recognizeHand(image, context.layout, context.templateDirectory);
  if (!recognition.safe && recognitionLayout.drawSlot) {
    const reactionLayout = { ...recognitionLayout, drawSlot: undefined };
    const reactionRecognition = modelRecognizer
      ? await modelRecognizer.recognizeHand(image, reactionLayout)
      : await recognizeTileSlots(image, recognitionLayout.handSlots, reactionLayout, context.templateDirectory);
    if (reactionRecognition.safe) recognition = reactionRecognition;
  }
  if (!recognition.safe && modelRecognizer) {
    try {
      const proposal = await proposeHandLayout(image, [11, 8, 5, 2]);
      const compactLayout = layoutFromHandProposal(proposal, context.layout);
      const compactRecognition = await modelRecognizer.recognizeHand(image, compactLayout);
      if (compactRecognition.safe) recognition = compactRecognition;
    } catch {}
  }
  const actionMatches = context.actionTemplateDirectory
    ? await recognizeActionButtons(image, context.layout, context.actionTemplateDirectory)
    : [];
  const publicRecognition = modelRecognizer && context.layout.publicTileRegions
    ? await recognizeConfiguredPublicTilesWithVit(image, context.layout, modelRecognizer)
    : undefined;
  return { image, recognition, actionMatches, ...(publicRecognition ? { publicRecognition } : {}) };
}

async function completeTurn(context: TurnContext, image: Buffer, recognition: HandRecognition, publicRecognition?: PublicRecognition, actionMatches: ActionButtonMatch[] = []) {
  const stamp = new Date().toISOString().replaceAll(":", "-");
  const screenshotDirectory = path.join(context.artifactDirectory, "screenshots");
  await mkdir(screenshotDirectory, { recursive: true });
  const screenshot = path.join(screenshotDirectory, `${stamp}.png`);
  await writeFile(screenshot, image, { mode: 0o600 });
  if (!recognition.safe) {
    throw new Error(`Recognition safety gate rejected frame: confidence=${recognition.confidence.toFixed(4)}, ambiguityMargin=${recognition.ambiguityMargin.toFixed(4)}`);
  }
  assertRecognizerAllowedForAuto(context.mode, recognition);
  const observation = publicRecognition ? toPublicTileObservation(publicRecognition, context.publicState.seat) : undefined;
  assertPublicObservationAllowed(context.mode, Boolean(context.useUntrustedPublicObservation));
  const hasSuppliedOpponentDiscards = context.publicState.opponents.some((opponent) => opponent.discards.length > 0);
  const observedPatch = observation && context.useUntrustedPublicObservation ? {
    ...(context.publicState.doraIndicators.length === 0 ? { doraIndicators: observation.doraIndicators } : {}),
    ...(context.publicState.ownDiscards.length === 0 ? { ownDiscards: observation.ownDiscards } : {}),
    ...(!hasSuppliedOpponentDiscards
      ? {
          opponents: observation.opponentDiscards.map((observedOpponent) => {
            const suppliedOpponent = context.publicState.opponents.find(
              (opponent) => opponent.seat === observedOpponent.seat,
            );
            return {
              ...observedOpponent,
              riichi: Boolean(suppliedOpponent?.riichi || observedOpponent.riichiDeclared),
              openMelds: Math.max(suppliedOpponent?.openMelds ?? 0, observedOpponent.melds?.length ?? 0),
            };
          }),
        }
      : {}),
    ...(context.publicState.visibleTiles.length === 0 ? { visibleTiles: observation.allMeldTiles ?? observation.ownMeldTiles } : {}),
  } : {};
  let state;
  const concealedCount = 14 - context.publicState.openMelds * 3;
  try {
    state = parseGameState({
      ...context.publicState,
      ...observedPatch,
      ...(context.publicState.phase === "reaction"
        ? { hand: recognition.tiles.slice(0, 13), draw: undefined }
        : { hand: recognition.tiles.slice(0, concealedCount - 1), draw: recognition.tiles[concealedCount - 1] }),
      availableUiActions: actionMatches.length ? availableUiActions(actionMatches) : context.publicState.availableUiActions,
      recognitionConfidence: recognition.confidence,
    });
  } catch (error) {
    if (!observation) throw error;
    // A public classifier disagreement must not prevent hand-only Advisor
    // output. Fall back without promoting or trusting the observation.
    state = parseGameState({
      ...context.publicState,
      ...(context.publicState.phase === "reaction"
        ? { hand: recognition.tiles.slice(0, 13), draw: undefined }
        : { hand: recognition.tiles.slice(0, concealedCount - 1), draw: recognition.tiles[concealedCount - 1] }),
      availableUiActions: actionMatches.length ? availableUiActions(actionMatches) : context.publicState.availableUiActions,
      recognitionConfidence: recognition.confidence,
    });
  }
  const decision = await decide(state, { mode: context.mode, ...(context.jev ? { jev: context.jev } : {}) });

  if (context.mode !== "observer") await showAdvisorOverlay(context.page, decision);

  let execution: ActionExecutionReceipt | UiActionExecutionReceipt | { action: "riichi"; declaration: UiActionExecutionReceipt; discard: ActionExecutionReceipt } | undefined;
  let executionError: string | undefined;
  if (decision.executable) {
    try {
      const selected = decision.selectedAction;
      if (selected.action === "discard") {
        await assertTemplateSetMatchesCalibration(context.layout, context.templateDirectory);
        const tilePosition = [...state.hand, state.draw!].lastIndexOf(selected.tile as any);
        execution = await guardedDiscard(context.page, context.layout, tilePosition, {
          allowed: decision.safety.allowed && recognition.safe,
          recognitionConfidence: recognition.confidence,
          decisionConfidence: decision.confidence,
        });
      } else {
        const button = selected.action === "minkan" || selected.action === "ankan" || selected.action === "kakan" ? "kan" : selected.action;
        if (!context.actionTemplateDirectory) throw new Error("Action template directory is required for non-discard execution");
        const match = actionMatches.find((candidate) => candidate.action === button && candidate.present);
        if (!match) throw new Error(`Selected ${button} button is not present in the evaluated frame`);
        const actionFingerprint = await fingerprintTemplateDirectory(context.actionTemplateDirectory);
        const declaration = await guardedUiAction(context.page, context.layout, button, {
          allowed: decision.safety.allowed && recognition.safe,
          buttonConfidence: match.confidence,
          decisionConfidence: decision.confidence,
          templateSetFingerprint: actionFingerprint,
        });
        if (selected.action === "riichi") {
          await assertTemplateSetMatchesCalibration(context.layout, context.templateDirectory);
          const tilePosition = [...state.hand, state.draw!].lastIndexOf(selected.tile as any);
          const discard = await guardedDiscard(context.page, context.layout, tilePosition, {
            allowed: true,
            recognitionConfidence: recognition.confidence,
            decisionConfidence: decision.confidence,
          });
          execution = { action: "riichi", declaration, discard };
        } else execution = declaration;
      }
    } catch (error) {
      executionError = error instanceof Error ? error.message : String(error);
    }
  }
  const publicObservation = observation ? {
    ...observation,
    applied: Boolean(context.useUntrustedPublicObservation),
  } : undefined;
  const record = await appendDecisionLog(path.join(context.artifactDirectory, "replays"), state, decision, screenshot, {
    recognition: {
      backend: "backend" in recognition ? recognition.backend : "template",
      tiles: recognition.tiles,
      confidence: recognition.confidence,
      ambiguityMargin: recognition.ambiguityMargin,
      safe: recognition.safe,
    },
    ...(publicObservation ? { publicObservation } : {}),
    ...(execution ? { execution } : {}),
    ...(executionError ? { executionError } : {}),
  });
  if (executionError) throw new Error(executionError);
  return {
    recognition,
    ...(publicRecognition ? {
      publicRecognition,
      publicObservation,
    } : {}),
    ...(execution ? { execution } : {}),
    decision,
    record,
  };
}

export async function processTurn(context: TurnContext) {
  const { image, recognition, publicRecognition, actionMatches } = await captureRecognition(context);
  const inferredOpenMelds = [14, 11, 8, 5, 2].includes(recognition.tiles.length)
    ? (14 - recognition.tiles.length) / 3
    : context.publicState.openMelds;
  const activeContext = inferredOpenMelds === context.publicState.openMelds
    ? context
    : { ...context, publicState: { ...context.publicState, openMelds: inferredOpenMelds } };
  return completeTurn(activeContext, image, recognition, publicRecognition, actionMatches);
}

/**
 * Watches the page without producing duplicate decisions. After a recognized
 * turn is processed, the loop must observe at least one non-turn/unsafe frame
 * before it arms itself for the next decision.
 */
export async function runAgentLoop(context: TurnContext, options: AgentLoopOptions = {}) {
  const pollIntervalMs = options.pollIntervalMs ?? 100;
  const maxTurns = options.maxTurns ?? Number.POSITIVE_INFINITY;
  const gate = new TurnRearmGate(options.rearmAfterUnsafeFrames ?? 3);
  let previousPublicObservation: ReturnType<typeof toPublicTileObservation> | undefined;
  let pendingReaction: { tile: GameTile; fromSeat: "east" | "south" | "west" | "north" } | undefined;
  let pendingReactionExpiresAt = 0;
  if (!Number.isFinite(pollIntervalMs) || pollIntervalMs < 100) throw new Error("pollIntervalMs must be at least 100");
  if (!(maxTurns === Number.POSITIVE_INFINITY || (Number.isInteger(maxTurns) && maxTurns > 0))) throw new Error("maxTurns must be a positive integer");

  let turns = 0;
  while (!options.signal?.aborted && turns < maxTurns) {
    try {
      const { image, recognition, publicRecognition, actionMatches } = await captureRecognition(context);
      const publicObservation = publicRecognition
        ? toPublicTileObservation(publicRecognition, context.publicState.seat)
        : undefined;
      if (previousPublicObservation && publicObservation) {
        const additions = publicObservation.opponentDiscards.flatMap((opponent) => {
          const previous = previousPublicObservation!.opponentDiscards.find((item) => item.seat === opponent.seat);
          if (!previous || opponent.discards.length !== previous.discards.length + 1) return [];
          if (!previous.discards.every((tile, index) => opponent.discards[index] === tile)) return [];
          return [{ tile: opponent.discards.at(-1)!, fromSeat: opponent.seat }];
        });
        if (additions.length === 1) {
          pendingReaction = additions[0];
          pendingReactionExpiresAt = Date.now() + 5_000;
        }
      }
      if (publicObservation) previousPublicObservation = publicObservation;
      if (pendingReaction && Date.now() > pendingReactionExpiresAt) pendingReaction = undefined;
      if (recognition.safe && recognition.tiles.length === 14) pendingReaction = undefined;

      let activeContext = context;
      const inferredOpenMelds = [14, 11, 8, 5, 2].includes(recognition.tiles.length)
        ? (14 - recognition.tiles.length) / 3
        : context.publicState.openMelds;
      let actionable = recognition.safe && [14, 11, 8, 5, 2].includes(recognition.tiles.length);
      if (actionable) {
        activeContext = {
          ...context,
          publicState: {
            ...context.publicState,
            openMelds: inferredOpenMelds,
            availableUiActions: [...new Set([...context.publicState.availableUiActions, "kan" as const])],
          },
        };
      }
      if (recognition.safe && recognition.tiles.length === 13 && pendingReaction) {
        const reactionState = {
          ...context.publicState,
          phase: "reaction" as const,
          pendingDiscard: pendingReaction,
          availableUiActions: ["ron", "pon", "kan", "chi", "pass"] as PublicGameState["availableUiActions"],
        };
        try {
          const preview = parseGameState({
            ...reactionState,
            hand: recognition.tiles,
            draw: undefined,
            recognitionConfidence: recognition.confidence,
          });
          actionable = generateLegalActions(preview).some((action) => action.action !== "pass");
          if (actionable) activeContext = { ...context, publicState: reactionState };
        } catch {
          actionable = false;
        }
      }
      if (!actionable && context.mode !== "observer") await hideAdvisorOverlay(context.page);
      // Advisor recognition can occasionally keep reporting a safe 14-tile row
      // across the short transition after a discard.  In that mode, a stable
      // changed hand is also evidence that the previous decision has ended.
      // Auto mode retains the stricter unsafe-frame-only rearm rule.
      const handSignature = context.mode === "advisor" && actionable
        ? `${activeContext.publicState.phase}:${recognition.tiles.join(",")}`
        : undefined;
      const gateResult = gate.observe(actionable, handSignature);
      if (gateResult.rearmed) {
        if (context.mode !== "observer") await hideAdvisorOverlay(context.page);
        options.onStatus?.({ kind: "waiting", message: "Turn ended; armed for the next recognizable hand" });
      } else if (gateResult.shouldProcess) {
        const result = await completeTurn(activeContext, image, recognition, publicRecognition, actionMatches);
        turns += 1;
        options.onStatus?.({ kind: "turn", message: `Processed turn ${turns}: ${result.decision.selectedAction.action}${result.decision.tile ? ` ${result.decision.tile}` : ""}` });
      }
    } catch (error) {
      gate.retryCurrentFrame();
      options.onStatus?.({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    }
    if (!options.signal?.aborted && turns < maxTurns) await context.page.waitForTimeout(pollIntervalMs);
  }
  return { turns, aborted: options.signal?.aborted ?? false };
}
