import { readFile } from "node:fs/promises";
import { layoutSchema } from "../recognition/layout.js";
import { recognizeHand, recognizeTileSlots } from "../recognition/templateMatcher.js";
import { detectConfiguredPublicRegions } from "../recognition/regionDetector.js";
import { recognizeConfiguredPublicTiles, recognizeConfiguredPublicTilesWithVit, toPublicTileObservation } from "../recognition/publicTileRecognizer.js";
import { proposeHandLayout } from "../recognition/handLayoutProposal.js";
import { HybridTileRecognizer } from "../recognition/hybridTileRecognizer.js";
import { availableUiActions, recognizeActionButtons } from "../recognition/actionButtonRecognizer.js";
import { recognizeCenterBoard } from "../recognition/centerBoardRecognizer.js";
import { recognizeHighlightedDiscard } from "../recognition/highlightedDiscard.js";
import type { CliArguments, CliCommand } from "./arguments.js";

async function recognize(args: CliArguments): Promise<void> {
  const screenshot = args.values[0];
  const layoutPath = args.values[1];
  const templates = args.values[2];
  if (!screenshot || !layoutPath || !templates) throw new Error("Usage: npm run recognize -- screenshot.png layout.json templates/");
  const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
  if (args.has("--backend=hybrid")) {
    const recognizer = new HybridTileRecognizer();
    try {
      console.log(JSON.stringify(await recognizer.recognizeHand(screenshot,
        args.has("--concealed-only") ? { ...layout, drawSlot: undefined } : layout)));
    } finally {
      await recognizer.close();
    }
    return;
  }
  console.log(JSON.stringify(args.has("--concealed-only")
    ? await recognizeTileSlots(screenshot, layout.handSlots, layout, templates)
    : await recognizeHand(screenshot, layout, templates), null, 2));
}

async function detectRegions(args: CliArguments): Promise<void> {
  const screenshot = args.values[0];
  const layoutPath = args.values[1];
  if (!screenshot || !layoutPath) throw new Error("Usage: detect-regions <screenshot.png> <layout.json>");
  const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
  console.log(JSON.stringify(await detectConfiguredPublicRegions(screenshot, layout), null, 2));
}

async function recognizeRegions(args: CliArguments): Promise<void> {
  const screenshot = args.values[0];
  const layoutPath = args.values[1];
  const templates = args.values[2];
  if (!screenshot || !layoutPath || !templates) throw new Error("Usage: recognize-regions <screenshot.png> <layout.json> <templates>");
  const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
  console.log(JSON.stringify(await recognizeConfiguredPublicTiles(screenshot, layout, templates), null, 2));
}

async function publicObservation(args: CliArguments): Promise<void> {
  const screenshot = args.values[0];
  const layoutPath = args.values[1];
  const templates = args.values[2];
  const seat = args.option("--seat") ?? "east";
  if (!screenshot || !layoutPath || !templates) throw new Error("Usage: public-observation <screenshot.png> <layout.json> <templates> --seat=east|south|west|north");
  if (!(["east", "south", "west", "north"] as const).includes(seat as any)) throw new Error("Invalid seat");
  const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
  const useHybrid = args.has("--backend=hybrid");
  const recognizer = useHybrid ? new HybridTileRecognizer() : undefined;
  let recognition;
  try {
    recognition = recognizer
      ? await recognizeConfiguredPublicTilesWithVit(screenshot, layout, recognizer)
      : await recognizeConfiguredPublicTiles(screenshot, layout, templates);
  } finally {
    await recognizer?.close();
  }
  const observation = toPublicTileObservation(recognition, seat as "east" | "south" | "west" | "north");
  const highlightedDiscard = args.has("--reaction-highlight")
    ? await recognizeHighlightedDiscard(screenshot, recognition, seat as "east" | "south" | "west" | "north") : undefined;
  console.log(JSON.stringify({ ...observation, ...(highlightedDiscard ? { highlightedDiscard } : {}) }));
}

async function recognizeCenter(args: CliArguments): Promise<void> {
  const screenshot = args.values[0];
  const layoutPath = args.values[1];
  const manifest = args.values[2];
  if (!screenshot || !layoutPath || !manifest) throw new Error("Usage: recognize-center <screenshot.png> <layout.json> <reference-manifest.json>");
  const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
  console.log(JSON.stringify(await recognizeCenterBoard(screenshot, layout, manifest), null, 2));
}

async function recognizeActions(args: CliArguments): Promise<void> {
  const screenshot = args.values[0];
  const layoutPath = args.values[1];
  const templates = args.values[2];
  const minimumConfidence = Number(args.option("--minimum-confidence") ?? 0.98);
  if (!screenshot || !layoutPath || !templates) throw new Error("Usage: recognize-actions <screenshot.png> <layout.json> <action-templates> [--minimum-confidence=0.98]");
  if (!Number.isFinite(minimumConfidence) || minimumConfidence < 0 || minimumConfidence > 1) throw new Error("Invalid action confidence threshold");
  const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
  const matches = await recognizeActionButtons(screenshot, layout, templates, minimumConfidence);
  console.log(JSON.stringify({ availableUiActions: availableUiActions(matches), matches }, null, 2));
}

async function proposeLayout(args: CliArguments): Promise<void> {
  const path = args.values[0];
  if (!path) throw new Error("Usage: propose-hand-layout <screenshot.png>");
  console.log(JSON.stringify(await proposeHandLayout(path), null, 2));
}

export const commands: Record<string, CliCommand> = {
  "recognize": recognize,
  "detect-regions": detectRegions,
  "recognize-regions": recognizeRegions,
  "public-observation": publicObservation,
  "recognize-center": recognizeCenter,
  "recognize-actions": recognizeActions,
  "propose-hand-layout": proposeLayout,
};
