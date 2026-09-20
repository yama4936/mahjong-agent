import { readFile } from "node:fs/promises";
import { createInterface } from "node:readline";
import { decideForceAutoWithJevDeadline } from "../agent/decision.js";
import { JevClient } from "../jev/client.js";
import { parseGameState, parsePublicGameState } from "../game/state.js";
import { parseGameTile } from "../game/tiles.js";
import { proposeLiveHandLayout } from "./handLayoutProposal.js";
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
const forceAutoDeadlineMs = Number(process.env.JEV_FORCE_AUTO_DEADLINE_MS ?? 700);
if (!Number.isFinite(forceAutoDeadlineMs) || forceAutoDeadlineMs <= 0) {
  throw new Error(`Invalid force-auto Jev deadline: ${process.env.JEV_FORCE_AUTO_DEADLINE_MS}`);
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
    };
    id = request.id;
    const activeLayout = request.dynamicLayout
      ? {
          ...layout,
          ...(await proposeLiveHandLayout(request.screenshot)),
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
      const state = parseGameState({
        ...publicState,
        openMelds: inferredOpenMelds,
        melds: [],
        hand: recognition.tiles.slice(0, -1),
        draw: recognition.tiles.at(-1),
        recognitionConfidence: recognition.confidence,
      });
      const decision = await decideForceAutoWithJevDeadline(state, {
        ...(jev ? { jev } : {}),
        deadlineMs: forceAutoDeadlineMs,
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
        ...(clickIndex !== undefined ? { clickIndex } : {}),
        ...(clickIndex !== undefined && activeLayout.clickPoints[clickIndex]
          ? { clickPoint: activeLayout.clickPoints[clickIndex] }
          : {}),
        concealedCount: recognition.tiles.length,
        openMelds: inferredOpenMelds,
      };
    }
    process.stdout.write(`${JSON.stringify({ id, result })}\n`);
  } catch (error) {
    process.stdout.write(`${JSON.stringify({ id, error: error instanceof Error ? error.message : String(error) })}\n`);
  }
}
