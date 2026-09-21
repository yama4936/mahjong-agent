import { readFile, stat } from "node:fs/promises";
import { createInterface } from "node:readline";
import { decideForceAutoWithJevDeadline } from "../agent/decision.js";
import { cachedPublicStatePatch, type CachedPublicObservation } from "../agent/publicCache.js";
import { isHandPlanCompatible, JevClient } from "../jev/client.js";
import { parseGameState, parsePublicGameState } from "../game/state.js";
import { parseGameTile } from "../game/tiles.js";
import { proposeHandLayout, proposeLiveHandLayout } from "./handLayoutProposal.js";
import { layoutSchema } from "./layout.js";
import { recognizeHand, recognizeTileSlots, warmTemplateCache, type MatcherOptions } from "./templateMatcher.js";

const [layoutPath, templateDirectory, statePath] = process.argv.slice(2);
if (!layoutPath || !templateDirectory) {
  throw new Error("Usage: recognitionServer <layout.json> <templates>");
}

const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
const rawPublicState = statePath ? JSON.parse(await readFile(statePath, "utf8")) : undefined;
if (rawPublicState) {
  delete rawPublicState.hand;
  delete rawPublicState.draw;
  delete rawPublicState.recognitionConfidence;
  delete rawPublicState.recognition_confidence;
}
const publicState = rawPublicState ? parsePublicGameState(rawPublicState) : undefined;
const forceAutoDeadlineMs = Number(process.env.JEV_FORCE_AUTO_DEADLINE_MS ?? 2_300);
if (!Number.isFinite(forceAutoDeadlineMs) || forceAutoDeadlineMs <= 0) {
  throw new Error(`Invalid force-auto Jev deadline: ${process.env.JEV_FORCE_AUTO_DEADLINE_MS}`);
}
const forceAutoClickBudgetMs = Number(process.env.FORCE_AUTO_CLICK_BUDGET_MS ?? 2_600);
if (!Number.isFinite(forceAutoClickBudgetMs) || forceAutoClickBudgetMs <= 0) {
  throw new Error(`Invalid force-auto click budget: ${process.env.FORCE_AUTO_CLICK_BUDGET_MS}`);
}
const preClickReserveMs = 150;
const maximumPublicCacheAgeMs = Number(process.env.FORCE_AUTO_PUBLIC_CACHE_MAX_AGE_MS ?? 15_000);
if (!Number.isFinite(maximumPublicCacheAgeMs) || maximumPublicCacheAgeMs <= 0) {
  throw new Error(`Invalid force-auto public cache age: ${process.env.FORCE_AUTO_PUBLIC_CACHE_MAX_AGE_MS}`);
}
const jev = process.env.TYPESAFE_API_KEY ? new JevClient(process.env.TYPESAFE_API_KEY) : undefined;
const options: MatcherOptions = {
  normalizeFace: layout.tileMatcher !== "raw",
  allClasses: layout.tileMatcher === "face_all",
  rejectBlank: true,
};
await warmTemplateCache(templateDirectory, options);
process.stdout.write(`${JSON.stringify({ ready: true })}\n`);

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of lines) {
  if (!line.trim()) continue;
  let id: unknown;
  try {
    const request = JSON.parse(line) as {
      id: unknown;
      screenshot: string;
      concealedOnly?: boolean;
      drawOnly?: boolean;
      concealedTiles?: string[];
      evaluateForceAuto?: boolean;
      dynamicLayout?: boolean;
      openMelds?: number;
      publicObservation?: CachedPublicObservation;
      forceAutoActionButtons?: Array<{ x: number; y: number; width: number; height: number; center: { x: number; y: number } }>;
    };
    id = request.id;
    const processingStartedAt = performance.now();
    const frameCapturedAtMs = (await stat(request.screenshot)).mtimeMs;
    const activeLayout = request.dynamicLayout
      ? {
          ...layout,
          ...(request.openMelds !== undefined && request.openMelds > 0
            ? await proposeHandLayout(request.screenshot, [14 - request.openMelds * 3])
            : await proposeLiveHandLayout(request.screenshot)),
          tileMatcher: layout.tileMatcher,
          minimumTileConfidence: layout.minimumTileConfidence,
          minimumTilePresence: layout.minimumTilePresence,
        }
      : layout;
    let recognition = request.drawOnly
      ? activeLayout.drawSlot
        ? await recognizeTileSlots(request.screenshot, [activeLayout.drawSlot], activeLayout, templateDirectory)
        : (() => { throw new Error("layout has no draw slot"); })()
      : request.concealedOnly
        ? await recognizeTileSlots(request.screenshot, activeLayout.handSlots, activeLayout, templateDirectory)
        : await recognizeHand(request.screenshot, activeLayout, templateDirectory);
    if (request.concealedTiles && recognition.tiles.length === 1) {
      recognition = {
        ...recognition,
        tiles: [...request.concealedTiles.map(parseGameTile), recognition.tiles[0]!],
      };
    }
    let result: unknown = recognition;
    if (request.evaluateForceAuto) {
      if (!publicState) throw new Error("force-auto evaluation requires a state file");
      const inferredOpenMelds = request.openMelds ?? (14 - recognition.tiles.length) / 3;
      if (!Number.isInteger(inferredOpenMelds) || inferredOpenMelds < 0 || inferredOpenMelds > 4) {
        throw new Error(`force-auto evaluation requires 14/11/8/5/2 concealed tiles; got ${recognition.tiles.length}`);
      }
      const concealed = recognition.tiles;
      const handPlan = request.publicObservation?.handPlan;
      const compatibleHandPlan = handPlan && isHandPlanCompatible(handPlan, concealed, inferredOpenMelds)
        ? handPlan : undefined;
      const capturedAtMs = request.publicObservation ? Date.parse(request.publicObservation.capturedAt) : undefined;
      const cacheAgeMs = capturedAtMs !== undefined && Number.isFinite(capturedAtMs)
        ? Math.max(0, Date.now() - capturedAtMs)
        : undefined;
      const cachedPatch = request.publicObservation && cacheAgeMs !== undefined && cacheAgeMs <= maximumPublicCacheAgeMs
        ? cachedPublicStatePatch(request.publicObservation, concealed)
        : undefined;
      const cacheFreshnessIgnoredReason = request.publicObservation
        ? cacheAgeMs === undefined
          ? "invalid_capture_time"
          : cacheAgeMs > maximumPublicCacheAgeMs ? "stale" : undefined
        : undefined;
      let publicCacheIgnoredReason: string | undefined;
      let state;
      try {
        state = parseGameState({
          ...publicState,
          ...(cachedPatch?.patch ?? {}),
          ...(request.forceAutoActionButtons?.length === 1 ? {
            availableUiActions: ["riichi", "tsumo", "kan", "kyuushu"],
          } : {}),
          openMelds: inferredOpenMelds,
          melds: [],
          hand: recognition.tiles.slice(0, -1),
          draw: recognition.tiles.at(-1),
          recognitionConfidence: recognition.confidence,
        });
      } catch (error) {
        publicCacheIgnoredReason = error instanceof Error ? error.message : String(error);
        state = parseGameState({
          ...publicState,
          ...(request.forceAutoActionButtons?.length === 1 ? {
            availableUiActions: ["riichi", "tsumo", "kan", "kyuushu"],
          } : {}),
          openMelds: inferredOpenMelds,
          melds: [],
          hand: recognition.tiles.slice(0, -1),
          draw: recognition.tiles.at(-1),
          recognitionConfidence: recognition.confidence,
        });
      }
      const captureAgeBeforeDecisionMs = Math.max(0, Date.now() - frameCapturedAtMs);
      const availableDecisionMs = Math.max(
        1,
        Math.floor(forceAutoClickBudgetMs - captureAgeBeforeDecisionMs - preClickReserveMs),
      );
      const decisionBudgetMs = Math.min(forceAutoDeadlineMs, availableDecisionMs);
      const decision = await decideForceAutoWithJevDeadline(state, {
        ...(jev ? { jev } : {}),
        ...(compatibleHandPlan ? { handPlan: compatibleHandPlan } : {}),
        deadlineMs: decisionBudgetMs,
      });
      const clickIndex = decision.selectedAction.action === "discard" || decision.selectedAction.action === "riichi"
        ? [...state.hand, ...(state.draw ? [state.draw] : [])].map(String).lastIndexOf(decision.selectedAction.tile)
        : undefined;
      result = {
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
        ...(decision.selectedAction.action !== "discard" && request.forceAutoActionButtons?.length === 1 ? {
          actionButton: {
            action: decision.selectedAction.action === "ankan" || decision.selectedAction.action === "kakan"
              ? "kan" : decision.selectedAction.action,
            ...request.forceAutoActionButtons[0],
            source: "force_auto_single_self_action_button",
          },
        } : {}),
        ...(clickIndex !== undefined ? { clickIndex } : {}),
        ...(clickIndex !== undefined && activeLayout.clickPoints[clickIndex]
          ? { clickPoint: activeLayout.clickPoints[clickIndex] }
          : {}),
        concealedCount: recognition.tiles.length,
        openMelds: inferredOpenMelds,
        publicCache: {
          applied: Boolean(cachedPatch && !publicCacheIgnoredReason),
          ...(request.publicObservation ? {
            capturedAt: request.publicObservation.capturedAt,
            recognitionLatencyMs: request.publicObservation.recognitionLatencyMs,
            acceptedTiles: request.publicObservation.acceptedTiles,
            detectedCandidates: request.publicObservation.detectedCandidates,
            configuredRegions: request.publicObservation.configuredRegions,
          } : {}),
          ...(cacheAgeMs !== undefined ? { ageMs: cacheAgeMs } : {}),
          ...(cachedPatch ? { rejectedTiles: cachedPatch.rejectedTiles } : {}),
          ...(cacheFreshnessIgnoredReason
            ? { ignoredReason: cacheFreshnessIgnoredReason }
            : publicCacheIgnoredReason ? { ignoredReason: publicCacheIgnoredReason } : {}),
        },
        processingElapsedMs: Math.max(0, Math.round(performance.now() - processingStartedAt)),
        turnTiming: {
          clickBudgetMs: forceAutoClickBudgetMs,
          captureAgeBeforeDecisionMs: Math.round(captureAgeBeforeDecisionMs),
          preClickReserveMs,
          decisionBudgetMs,
        },
        handPlan: {
          applied: Boolean(compatibleHandPlan),
          ...(handPlan ? {
            selected: handPlan.planId,
            confidence: handPlan.confidence,
            latencyMs: handPlan.latencyMs,
            createdAt: handPlan.createdAt,
          } : {}),
          ...(handPlan && !compatibleHandPlan ? { ignoredReason: "incompatible_with_current_hand" } : {}),
        },
      };
    }
    process.stdout.write(`${JSON.stringify({ id, result })}\n`);
  } catch (error) {
    process.stdout.write(`${JSON.stringify({ id, error: error instanceof Error ? error.message : String(error) })}\n`);
  }
}
