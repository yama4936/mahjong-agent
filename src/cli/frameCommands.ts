import { readFile } from "node:fs/promises";
import { parseGameState, parsePublicGameState } from "../game/state.js";
import { normalizeTile } from "../game/tiles.js";
import { JevClient } from "../jev/client.js";
import { layoutSchema } from "../recognition/layout.js";
import { measureSlotPresence, recognizeHand, recognizeTileSlots } from "../recognition/templateMatcher.js";
import { recognizeConfiguredPublicTilesWithVit, toPublicTileObservation, opponentStatesFromObservation } from "../recognition/publicTileRecognizer.js";
import { layoutFromHandProposal, proposeHandLayout } from "../recognition/handLayoutProposal.js";
import { decide, decideForceAutoWithJevDeadline } from "../agent/decision.js";
import { fingerprintTemplateDirectory } from "../recognition/templateValidator.js";
import { assertTemplateSetMatchesCalibration } from "../agent/controller.js";
import { availableUiActions, recognizeActionButtons } from "../recognition/actionButtonRecognizer.js";
import { modelRecognizer } from "./modelRecognizer.js";
import type { CliArguments, CliCommand } from "./arguments.js";

async function evaluateFrame(args: CliArguments): Promise<void> {
  const screenshot = args.values[0];
  const layoutPath = args.values[1];
  const templates = args.values[2];
  const stateArgument = args.option("--state");
  const modeArgument = args.option("--mode") ?? "advisor";
  const actionTemplatesArgument = args.option("--action-templates");
  const pendingDiscardArgument = args.option("--pending-discard");
  const publicObservationArgument = args.option("--public-observation");
  const recognitionArgument = args.option("--recognition-file");
  const availableUiActionsArgument = args.option("--available-ui-actions");
  if (!screenshot || !layoutPath || !templates || !stateArgument) {
    throw new Error("Usage: evaluate-frame <screenshot.png> <layout.json> <templates> --state=public-state.json [--mode=advisor|auto|force-auto]");
  }
  if (modeArgument !== "advisor" && modeArgument !== "auto" && modeArgument !== "force-auto") throw new Error("evaluate-frame mode must be advisor, auto, or force-auto");
  const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
  const rawPublicState = JSON.parse(await readFile(stateArgument, "utf8"));
  delete rawPublicState.hand;
  delete rawPublicState.draw;
  delete rawPublicState.recognitionConfidence;
  delete rawPublicState.recognition_confidence;
  const observedBoard = publicObservationArgument ? JSON.parse(await readFile(publicObservationArgument, "utf8")) : undefined;
  const observedPatch = observedBoard ? {
    doraIndicators: observedBoard.doraIndicators,
    ownDiscards: observedBoard.ownDiscards,
    turn: observedBoard.ownDiscards?.length ?? rawPublicState.turn,
    melds: observedBoard.ownMelds,
    openMelds: observedBoard.ownMelds?.length ?? rawPublicState.openMelds,
    opponents: opponentStatesFromObservation(observedBoard, rawPublicState.opponents),
  } : {};
  const suppliedPublicState = parsePublicGameState({ ...rawPublicState, ...observedPatch });
  const pendingParts = pendingDiscardArgument?.split(",");
  const publicState = pendingParts?.length === 2
    ? parsePublicGameState({ ...suppliedPublicState, phase: "reaction", pendingDiscard: {
        tile: pendingParts[0], fromSeat: pendingParts[1],
        inRiver: Boolean(observedBoard?.opponentDiscards?.some((opponent: any) =>
          opponent.seat === pendingParts[1] && opponent.discards?.at(-1) === pendingParts[0])),
      } })
    : suppliedPublicState;
  const actionMatches = actionTemplatesArgument
    ? await recognizeActionButtons(screenshot, layout, actionTemplatesArgument, modeArgument === "force-auto" ? 0 : 0.98)
    : [];
  const detectedActions = availableUiActions(actionMatches);
  let recognition = recognitionArgument
    ? JSON.parse(await readFile(recognitionArgument, "utf8"))
    : publicState.phase === "reaction"
      ? await recognizeTileSlots(screenshot, layout.handSlots, layout, templates)
      : await recognizeHand(screenshot, layout, templates);
  const reactionPrompt = detectedActions.includes("pass")
    && detectedActions.some((action) => action === "chi" || action === "pon" || action === "kan" || action === "ron");
  if (reactionPrompt && (!recognition.safe || recognition.tiles.length !== 14)) {
    recognition = await recognizeTileSlots(screenshot, layout.handSlots, layout, templates);
  }
  const expectedTiles = publicState.phase === "reaction" ? 13 : 14;
  if (reactionPrompt && publicState.phase !== "reaction" && (recognition.safe || modeArgument === "force-auto") && recognition.tiles.length === 13) {
    const passButton = actionMatches.find((match) => match.action === "pass" && match.present);
    const actionTemplateSetFingerprint = passButton && actionTemplatesArgument
      ? await fingerprintTemplateDirectory(actionTemplatesArgument)
      : undefined;
    console.log(JSON.stringify({
      schemaVersion: 1,
      status: "reaction_prompt",
      recognition: {
        backend: "template",
        tiles: recognition.tiles,
        confidence: recognition.confidence,
        ambiguityMargin: recognition.ambiguityMargin,
        safe: recognition.safe,
        turnReady: true,
      },
      availableUiActions: detectedActions,
      ...(passButton ? { actionButton: { ...passButton, templateSetFingerprint: actionTemplateSetFingerprint } } : {}),
    }));
    return;
  }
  if ((modeArgument !== "force-auto" && !recognition.safe) || recognition.tiles.length !== expectedTiles) {
    console.log(JSON.stringify({
      schemaVersion: 1,
      status: "not_ready",
      recognition: {
        tiles: recognition.tiles,
        confidence: recognition.confidence,
        ambiguityMargin: recognition.ambiguityMargin,
        safe: recognition.safe,
        turnReady: recognition.tiles.length === expectedTiles,
      },
    }));
    return;
  }
  const state = parseGameState({
    ...publicState,
    hand: recognition.tiles.slice(0, 13),
    ...(publicState.phase === "self_turn" ? { draw: recognition.tiles[13] } : {}),
    availableUiActions: actionMatches.length ? detectedActions
      : availableUiActionsArgument ? availableUiActionsArgument.split(",").filter(Boolean)
        : publicState.availableUiActions,
    recognitionConfidence: recognition.confidence,
  });
  const apiKey = process.env.TYPESAFE_API_KEY;
  if (modeArgument === "auto" && !apiKey) throw new Error("TYPESAFE_API_KEY is required in Auto mode");
  if (modeArgument === "auto") {
    if (!layout.autoOperation) throw new Error("Auto operation is not enabled by a passing template calibration");
    await assertTemplateSetMatchesCalibration(layout, templates);
  }
  const decision = modeArgument === "force-auto"
    ? await decideForceAutoWithJevDeadline(state, {
        ...(apiKey ? { jev: new JevClient(apiKey) } : {}),
        deadlineMs: Number(process.env.JEV_FORCE_AUTO_DEADLINE_MS ?? 2_300),
      })
    : await decide(state, {
        mode: modeArgument,
        ...(apiKey ? { jev: new JevClient(apiKey) } : {}),
      });
  const clickIndex = decision.selectedAction.action === "discard" || decision.selectedAction.action === "riichi"
    ? [...state.hand, ...(state.draw ? [state.draw] : [])].map(String).lastIndexOf(decision.selectedAction.tile)
    : undefined;
  const actionButtonName = decision.selectedAction.action === "minkan" || decision.selectedAction.action === "ankan" || decision.selectedAction.action === "kakan"
    ? "kan"
    : decision.selectedAction.action;
  const actionButton = actionMatches.find((match) => match.action === actionButtonName && match.present);
  const actionTemplateSetFingerprint = actionButton && actionTemplatesArgument
    ? await fingerprintTemplateDirectory(actionTemplatesArgument)
    : undefined;
  console.log(JSON.stringify({
    schemaVersion: 1,
    status: "decision",
    state,
    recognition: {
      backend: "template",
      tiles: recognition.tiles,
      confidence: recognition.confidence,
      ambiguityMargin: recognition.ambiguityMargin,
      safe: recognition.safe,
    },
    decision,
    ...(clickIndex !== undefined ? { clickIndex } : {}),
    ...(actionButton ? { actionButton: { ...actionButton, templateSetFingerprint: actionTemplateSetFingerprint } } : {}),
  }));
}

async function verifyDiscardFrame(args: CliArguments): Promise<void> {
  const screenshot = args.values[0];
  const layoutPath = args.values[1];
  const templates = args.values[2];
  const beforeArgument = args.option("--before");
  const clickIndex = Number(args.option("--click-index"));
  const force = args.has("--force");
  if (!screenshot || !layoutPath || !templates || !beforeArgument || !Number.isInteger(clickIndex)) {
    throw new Error("Usage: verify-discard-frame <screenshot.png> <layout.json> <templates> --before=t1,...,t14 --click-index=N");
  }
  const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
  const before = beforeArgument.split(",");
  if (before.length !== 14 || clickIndex < 0 || clickIndex >= before.length) throw new Error("Invalid pre-discard hand or click index");
  const expected = before.filter((_, index) => index !== clickIndex).sort();
  const recognition = await recognizeTileSlots(screenshot, layout.handSlots, layout, templates);
  const actual = recognition.tiles.map(String).sort();
  // The red-five gate can classify the same physical tile as either 0x or
  // 5x on adjacent frames. That distinction matters to strategy, but it
  // must not turn a successful discard into a false post-click failure.
  const normalizedExpected = expected.map(normalizeTile).sort();
  const normalizedActual = actual.map(normalizeTile).sort();
  const drawPresence = layout.drawSlot ? (await measureSlotPresence(screenshot, [layout.drawSlot]))[0]! : 0;
  const drawSlotEmpty = drawPresence < layout.minimumTilePresence;
  // force-auto deliberately ignores score calibration, but still requires
  // the expected 13-tile multiset (apart from red-five classification) and
  // an empty draw slot.
  const verified = (force || recognition.safe) && drawSlotEmpty
    && JSON.stringify(normalizedActual) === JSON.stringify(normalizedExpected);
  console.log(JSON.stringify({
    schemaVersion: 1, verified, force, expected, actual,
    normalizedExpected, normalizedActual, drawPresence, drawSlotEmpty, recognition,
  }));
}

async function analyzeScreenshot(args: CliArguments): Promise<void> {
  const screenshot = args.values[0];
  if (!screenshot || screenshot.startsWith("--")) throw new Error("Usage: analyze-screenshot <screenshot.png> [--state=public-state.json] [--jev]");
  const statePath = args.option("--state");
  const rawPublicState = statePath ? JSON.parse(await readFile(statePath, "utf8")) : {};
  delete rawPublicState.hand;
  delete rawPublicState.draw;
  delete rawPublicState.recognitionConfidence;
  delete rawPublicState.recognition_confidence;
  const publicState = parsePublicGameState({ ...rawPublicState, phase: "self_turn" });
  const proposal = await proposeHandLayout(screenshot);
  const layout = layoutFromHandProposal(proposal);
  const recognizerValue = args.option("--recognizer") ?? "hybrid";
  const recognizer = modelRecognizer(recognizerValue);
  if (!recognizer) throw new Error("analyze-screenshot requires --recognizer=hybrid or --recognizer=vit");
  try {
    const recognition = await recognizer.recognizeHand(screenshot, layout);
    if (!recognition.turnReady || recognition.tiles.length !== 14) {
      throw new Error(`Screenshot does not contain a complete self-turn hand (recognized ${recognition.tiles.length} tiles)`);
    }
    const publicRecognition = await recognizeConfiguredPublicTilesWithVit(screenshot, layout, recognizer);
    const publicObservation = toPublicTileObservation(publicRecognition);
    const usePublicObservation = args.has("--use-public-observation");
    let publicObservationApplied = usePublicObservation;
    let state;
    try {
      state = parseGameState({
        ...publicState,
        ...(usePublicObservation && publicState.doraIndicators.length === 0 ? { doraIndicators: publicObservation.doraIndicators } : {}),
        ...(usePublicObservation && publicState.ownDiscards.length === 0 ? { ownDiscards: publicObservation.ownDiscards } : {}),
        ...(usePublicObservation && publicState.visibleTiles.length === 0 && !publicState.opponents.some((opponent) => opponent.discards.length > 0)
          ? { visibleTiles: publicObservation.otherVisibleTiles }
          : {}),
        hand: recognition.tiles.slice(0, 13),
        draw: recognition.tiles[13],
        recognitionConfidence: recognition.confidence,
      });
    } catch {
      publicObservationApplied = false;
      state = parseGameState({
        ...publicState,
        hand: recognition.tiles.slice(0, 13),
        draw: recognition.tiles[13],
        recognitionConfidence: recognition.confidence,
      });
    }
    const apiKey = args.has("--jev") ? process.env.TYPESAFE_API_KEY : undefined;
    if (args.has("--jev") && !apiKey) throw new Error("TYPESAFE_API_KEY is required with --jev");
    const decision = await decide(state, { mode: "advisor", ...(apiKey ? { jev: new JevClient(apiKey) } : {}) });
    if (args.has("--compact")) {
      console.log(JSON.stringify({ recommended_action: decision.recommendedAction, tile: decision.tile }, null, 2));
      return;
    }
    console.log(JSON.stringify({
      recommended_action: decision.recommendedAction,
      tile: decision.tile,
      confidence: decision.confidence,
      source: decision.source,
      recognition: {
        backend: recognizer.backend,
        tiles: recognition.tiles,
        confidence: recognition.confidence,
        ambiguityMargin: recognition.ambiguityMargin,
        safe: recognition.safe,
        redFiveClassification: recognition.redFiveClassification,
      },
      layout: { confidence: proposal.confidence, evidence: proposal.evidence },
      publicObservation: { ...publicObservation, applied: publicObservationApplied },
      candidates: decision.candidates,
      safety: decision.safety,
    }, null, 2));
  } finally {
    await recognizer.close();
  }
}

export const commands: Record<string, CliCommand> = {
  "evaluate-frame": evaluateFrame,
  "verify-discard-frame": verifyDiscardFrame,
  "analyze-screenshot": analyzeScreenshot,
};
