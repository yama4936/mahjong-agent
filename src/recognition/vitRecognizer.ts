import { PredictionWorker } from "./predictionWorker.js";
import path from "node:path";
import sharp from "sharp";
import { parseGameTile, type GameTile } from "../game/tiles.js";
import type { ScreenLayout } from "./layout.js";
import { measureSlotPresence } from "./templateMatcher.js";

interface WorkerPrediction {
  label: string;
  confidence: number;
  runnerUpLabel: string;
  runnerUpConfidence: number;
}

export interface VitTilePrediction {
  tile: GameTile;
  confidence: number;
  runnerUpTile: GameTile;
  runnerUpConfidence: number;
}

const sourceSuit = { b: "s", n: "m", p: "p" } as const;
const sourceHonor: Record<string, GameTile> = { ew: "E", sw: "S", ww: "W", nw: "N", wd: "P", gd: "F", rd: "C" };

export function mapVisionLabel(label: string): GameTile {
  if (sourceHonor[label]) return sourceHonor[label]!;
  const match = label.match(/^([1-9])([bnp])$/);
  if (!match) throw new Error(`Unknown vision label: ${label}`);
  return parseGameTile(`${match[1]}${sourceSuit[match[2] as keyof typeof sourceSuit]}`);
}

export class VitTileRecognizer {
  readonly backend = "vit" as const;
  private readonly worker: PredictionWorker<WorkerPrediction>;

  constructor(
    python = path.resolve(".runtime/vision-venv/bin/python"),
    modelDirectory = path.resolve(".runtime/mahjong-vision/vision_transformer_local"),
    workerScript = path.resolve("scripts/vision_worker.py"),
  ) {
    this.worker = new PredictionWorker({
      executable: python,
      args: [workerScript, modelDirectory],
      name: "Vision worker",
    });
  }

  private predict(images: Buffer[]): Promise<WorkerPrediction[]> {
    return this.worker.predict(images);
  }

  async classifyTileImages(images: Buffer[]): Promise<VitTilePrediction[]> {
    if (images.length === 0) return [];
    // The worker deliberately caps one inference request at 14 images. Public
    // regions can contain considerably more tiles, so keep the worker's
    // bounded request contract and concatenate deterministic chunks here.
    const predictions: WorkerPrediction[] = [];
    for (let offset = 0; offset < images.length; offset += 14) {
      predictions.push(...await this.predict(images.slice(offset, offset + 14)));
    }
    if (predictions.length !== images.length) throw new Error("Vision worker returned the wrong prediction count");
    return predictions.map((prediction) => ({
      tile: mapVisionLabel(prediction.label),
      confidence: prediction.confidence,
      runnerUpTile: mapVisionLabel(prediction.runnerUpLabel),
      runnerUpConfidence: prediction.runnerUpConfidence,
    }));
  }

  async recognizeHand(screenshot: string | Buffer, layout: ScreenLayout) {
    const slots = layout.drawSlot ? [...layout.handSlots, layout.drawSlot] : layout.handSlots;
    const presenceFractions = await measureSlotPresence(screenshot, slots);
    if (presenceFractions.some((fraction) => fraction < layout.minimumTilePresence)) {
      return { backend: "vit" as const, tiles: [], matches: [], confidence: 0, ambiguityMargin: 0, presenceFractions, turnReady: false, safe: false };
    }
    const crops = await Promise.all(slots.map((slot) => sharp(screenshot)
      .extract({ left: slot.x, top: slot.y, width: slot.width, height: slot.height })
      .png()
      .toBuffer()));
    const predictions = await this.classifyTileImages(crops);
    const matches = predictions.map((prediction) => ({
      tile: prediction.tile,
      confidence: prediction.confidence,
      runnerUpConfidence: prediction.runnerUpConfidence,
    }));
    const confidence = Math.min(...matches.map((match) => match.confidence));
    const ambiguityMargin = Math.min(...matches.map((match) => match.confidence - match.runnerUpConfidence));
    const turnReady = matches.length === slots.length;
    return {
      backend: "vit" as const,
      tiles: matches.map((match) => match.tile),
      matches,
      confidence,
      ambiguityMargin,
      presenceFractions,
      turnReady,
      safe: turnReady && confidence >= layout.minimumVitConfidence && ambiguityMargin >= layout.minimumVitMargin,
      redFiveClassification: "unsupported" as const,
    };
  }

  async close(): Promise<void> {
    this.worker.close();
  }
}
