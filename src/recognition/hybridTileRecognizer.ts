import { PredictionWorker } from "./predictionWorker.js";
import path from "node:path";
import sharp from "sharp";
import { parseGameTile, type GameTile } from "../game/tiles.js";
import type { ScreenLayout } from "./layout.js";
import { measureSlotPresence } from "./templateMatcher.js";
import type { VitTilePrediction } from "./vitRecognizer.js";

interface WorkerPrediction {
  label: string;
  confidence: number;
  runnerUpLabel: string;
  runnerUpConfidence: number;
  selectedBy: "normal" | "red-gate";
  normalPrediction: { label: string; confidence: number };
  redPrediction: { label: string; confidence: number };
}

export interface HybridTilePrediction extends VitTilePrediction {
  selectedBy: "normal" | "red-gate";
  normalPrediction: { tile: GameTile; confidence: number };
  redPrediction: { label: string; confidence: number };
}

export function isKnownSixSevenPinConfusion(match: {
  tile: GameTile;
  runnerUpTile?: GameTile;
  confidence: number;
}): boolean {
  return match.tile === "6p" && match.runnerUpTile === "7p" && match.confidence < 0.788;
}

const honors: Record<string, GameTile> = { "1z": "E", "2z": "S", "3z": "W", "4z": "N", "5z": "P", "6z": "F", "7z": "C" };

export function mapHybridLabel(label: string): GameTile {
  const red = { "5m-": "0m", "5p-": "0p", "5s-": "0s" }[label];
  if (red) return parseGameTile(red);
  return honors[label] ?? parseGameTile(label);
}

export class HybridTileRecognizer {
  readonly backend = "hybrid" as const;
  private readonly worker: PredictionWorker<WorkerPrediction>;

  constructor(
    python = path.resolve(process.platform === "win32"
      ? ".runtime/vision-venv/Scripts/python.exe"
      : ".runtime/vision-venv/bin/python"),
    cvmajWeights = path.resolve(".runtime/hybrid-vision/cvmaj-pretrained.tar"),
    autoMajsoulWeights = path.resolve(".runtime/hybrid-vision/automajsoul-best-model.pt"),
    workerScript = path.resolve("scripts/hybrid_vision_worker.py"),
  ) {
    this.worker = new PredictionWorker({
      executable: python,
      args: [workerScript, cvmajWeights, autoMajsoulWeights],
      name: "Hybrid vision worker",
    });
  }

  private predict(images: Buffer[]): Promise<WorkerPrediction[]> {
    return this.worker.predict(images);
  }

  async classifyTileImages(images: Buffer[]): Promise<HybridTilePrediction[]> {
    if (images.length === 0) return [];
    const predictions: WorkerPrediction[] = [];
    for (let offset = 0; offset < images.length; offset += 64) {
      predictions.push(...await this.predict(images.slice(offset, offset + 64)));
    }
    if (predictions.length !== images.length) throw new Error("Hybrid vision worker returned the wrong prediction count");
    return predictions.map((prediction) => ({
      tile: mapHybridLabel(prediction.label),
      confidence: prediction.confidence,
      runnerUpTile: mapHybridLabel(prediction.runnerUpLabel),
      runnerUpConfidence: prediction.runnerUpConfidence,
      selectedBy: prediction.selectedBy,
      normalPrediction: {
        tile: mapHybridLabel(prediction.normalPrediction.label),
        confidence: prediction.normalPrediction.confidence,
      },
      redPrediction: prediction.redPrediction,
    }));
  }

  async recognizeHand(screenshot: string | Buffer, layout: ScreenLayout) {
    const slots = layout.drawSlot ? [...layout.handSlots, layout.drawSlot] : layout.handSlots;
    const presenceFractions = await measureSlotPresence(screenshot, slots);
    if (presenceFractions.some((fraction) => fraction < layout.minimumTilePresence)) {
      return { backend: "hybrid" as const, tiles: [], matches: [], confidence: 0, ambiguityMargin: 0, presenceFractions, turnReady: false, safe: false, redFiveClassification: "supported" as const };
    }
    const crops = await Promise.all(slots.map((slot) => sharp(screenshot)
      .extract({ left: slot.x, top: slot.y, width: slot.width, height: slot.height })
      .png()
      .toBuffer()));
    const predictions = await this.classifyTileImages(crops);
    const matches = predictions.map((prediction) => ({
      tile: prediction.tile,
      confidence: prediction.confidence,
      runnerUpTile: prediction.runnerUpTile,
      runnerUpConfidence: prediction.runnerUpConfidence,
      selectedBy: prediction.selectedBy,
      normalPrediction: prediction.normalPrediction,
      redPrediction: prediction.redPrediction,
    }));
    const confidence = Math.min(...matches.map((match) => match.confidence));
    const ambiguityMargin = Math.min(...matches.map((match) => match.confidence - match.runnerUpConfidence));
    const turnReady = matches.length === slots.length;
    // Three reviewed live frames contain actual 7p tiles that this model calls
    // 6p at 0.70-0.7803 confidence with 7p second.  A verified correct 6p/7p
    // competition is 0.788, so fail closed only inside the measured gap.
    const knownSixSevenPinConfusion = matches.some(isKnownSixSevenPinConfusion);
    return {
      backend: "hybrid" as const,
      tiles: matches.map((match) => match.tile),
      matches,
      confidence,
      ambiguityMargin,
      presenceFractions,
      turnReady,
      safe: turnReady && !knownSixSevenPinConfusion
        && confidence >= layout.minimumVitConfidence && ambiguityMargin >= layout.minimumVitMargin,
      redFiveClassification: "supported" as const,
    };
  }

  async close(): Promise<void> {
    this.worker.close();
  }
}
