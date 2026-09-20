import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";
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

const honors: Record<string, GameTile> = { "1z": "E", "2z": "S", "3z": "W", "4z": "N", "5z": "P", "6z": "F", "7z": "C" };

export function mapHybridLabel(label: string): GameTile {
  const red = { "5m-": "0m", "5p-": "0p", "5s-": "0s" }[label];
  if (red) return parseGameTile(red);
  return honors[label] ?? parseGameTile(label);
}

export class HybridTileRecognizer {
  readonly backend = "hybrid" as const;
  private child: ChildProcessWithoutNullStreams | undefined;
  private ready: Promise<void> | undefined;
  private sequence = 0;
  private pending = new Map<number, { resolve: (value: WorkerPrediction[]) => void; reject: (error: Error) => void; timer: NodeJS.Timeout }>();

  constructor(
    private readonly python = path.resolve(process.platform === "win32"
      ? ".runtime/vision-venv/Scripts/python.exe"
      : ".runtime/vision-venv/bin/python"),
    private readonly cvmajWeights = path.resolve(".runtime/hybrid-vision/cvmaj-pretrained.tar"),
    private readonly autoMajsoulWeights = path.resolve(".runtime/hybrid-vision/automajsoul-best-model.pt"),
    private readonly workerScript = path.resolve("scripts/hybrid_vision_worker.py"),
  ) {}

  private ensureWorker(): Promise<void> {
    if (this.ready) return this.ready;
    this.ready = new Promise((resolve, reject) => {
      const child = spawn(this.python, [this.workerScript, this.cvmajWeights, this.autoMajsoulWeights], { stdio: ["pipe", "pipe", "pipe"] });
      this.child = child;
      let settled = false;
      const lines = createInterface({ input: child.stdout });
      lines.on("line", (line) => {
        let message: any;
        try { message = JSON.parse(line); } catch { return; }
        if (message.ready === true && !settled) {
          settled = true;
          resolve();
          return;
        }
        if (!Number.isInteger(message.id)) return;
        const request = this.pending.get(message.id);
        if (!request) return;
        clearTimeout(request.timer);
        this.pending.delete(message.id);
        if (typeof message.error === "string") request.reject(new Error(`Hybrid vision worker: ${message.error}`));
        else request.resolve(message.predictions as WorkerPrediction[]);
      });
      let stderr = "";
      child.stderr.on("data", (chunk) => { stderr = `${stderr}${String(chunk)}`.slice(-4000); });
      child.once("error", (error) => {
        if (!settled) { settled = true; reject(error); }
      });
      child.once("exit", (code) => {
        const error = new Error(`Hybrid vision worker exited with code ${code}${stderr ? `: ${stderr.trim()}` : ""}`);
        if (!settled) { settled = true; reject(error); }
        for (const request of this.pending.values()) {
          clearTimeout(request.timer);
          request.reject(error);
        }
        this.pending.clear();
        this.child = undefined;
        this.ready = undefined;
      });
    });
    return this.ready;
  }

  private async predict(images: Buffer[]): Promise<WorkerPrediction[]> {
    await this.ensureWorker();
    const child = this.child;
    if (!child) throw new Error("Hybrid vision worker is unavailable");
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error("Hybrid vision worker timed out"));
      }, 15_000);
      this.pending.set(id, { resolve, reject, timer });
      child.stdin.write(`${JSON.stringify({ id, images: images.map((image) => image.toString("base64")) })}\n`);
    });
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
      runnerUpConfidence: prediction.runnerUpConfidence,
      selectedBy: prediction.selectedBy,
      normalPrediction: prediction.normalPrediction,
      redPrediction: prediction.redPrediction,
    }));
    const confidence = Math.min(...matches.map((match) => match.confidence));
    const ambiguityMargin = Math.min(...matches.map((match) => match.confidence - match.runnerUpConfidence));
    const turnReady = matches.length === 14;
    return {
      backend: "hybrid" as const,
      tiles: matches.map((match) => match.tile),
      matches,
      confidence,
      ambiguityMargin,
      presenceFractions,
      turnReady,
      safe: turnReady && confidence >= layout.minimumVitConfidence && ambiguityMargin >= layout.minimumVitMargin,
      redFiveClassification: "supported" as const,
    };
  }

  async close(): Promise<void> {
    const child = this.child;
    this.child = undefined;
    this.ready = undefined;
    if (!child || child.exitCode !== null) return;
    child.kill("SIGTERM");
  }
}
