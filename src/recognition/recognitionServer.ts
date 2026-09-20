import { readFile } from "node:fs/promises";
import { createInterface } from "node:readline";
import { decide } from "../agent/decision.js";
import { parseGameState, parsePublicGameState } from "../game/state.js";
import { parseGameTile } from "../game/tiles.js";
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
    };
    id = request.id;
    let recognition = request.drawOnly
      ? layout.drawSlot
        ? await recognizeTileSlots(request.screenshot, [layout.drawSlot], layout, templateDirectory)
        : (() => { throw new Error("layout has no draw slot"); })()
      : request.concealedOnly
        ? await recognizeTileSlots(request.screenshot, layout.handSlots, layout, templateDirectory)
        : await recognizeHand(request.screenshot, layout, templateDirectory);
    if (request.concealedTiles && recognition.tiles.length === 1) {
      recognition = {
        ...recognition,
        tiles: [...request.concealedTiles.map(parseGameTile), recognition.tiles[0]!],
      };
    }
    let result: unknown = recognition;
    if (request.evaluateForceAuto) {
      if (!publicState) throw new Error("force-auto evaluation requires a state file");
      if (recognition.tiles.length !== 14) throw new Error(`force-auto evaluation requires 14 tiles; got ${recognition.tiles.length}`);
      const state = parseGameState({
        ...publicState,
        hand: recognition.tiles.slice(0, 13),
        draw: recognition.tiles[13],
        recognitionConfidence: recognition.confidence,
      });
      const decision = await decide(state, { mode: "force-auto" });
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
      };
    }
    process.stdout.write(`${JSON.stringify({ id, result })}\n`);
  } catch (error) {
    process.stdout.write(`${JSON.stringify({ id, error: error instanceof Error ? error.message : String(error) })}\n`);
  }
}
