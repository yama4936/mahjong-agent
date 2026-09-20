import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";
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
  private child: ChildProcessWithoutNullStreams | undefined;
  private ready: Promise<void> | undefined;
  private sequence = 0;
  private pending = new Map<number, { resolve: (value: WorkerPrediction[]) => void; reject: (error: Error) => void; timer: NodeJS.Timeout }>();

  constructor(
    private readonly python = path.resolve(".runtime/vision-venv/bin/python"),
    private readonly modelDirectory = path.resolve(".runtime/mahjong-vision/vision_transformer_local"),
    private readonly workerScript = path.resolve("scripts/vision_worker.py"),
  ) {}

  private ensureWorker(): Promise<void> {
    if (this.ready) return this.ready;
    this.ready = new Promise((resolve, reject) => {
      const child = spawn(this.python, [this.workerScript, this.modelDirectory], { stdio: ["pipe", "pipe", "pipe"] });
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
        if (typeof message.error === "string") request.reject(new Error(`Vision worker: ${message.error}`));
        else request.resolve(message.predictions as WorkerPrediction[]);
      });
      let stderr = "";
      child.stderr.on("data", (chunk) => { stderr = `${stderr}${String(chunk)}`.slice(-4000); });
      child.once("error", (error) => {
        if (!settled) { settled = true; reject(error); }
      });
      child.once("exit", (code) => {
        const error = new Error(`Vision worker exited with code ${code}${stderr ? `: ${stderr.trim()}` : ""}`);
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
    if (!child) throw new Error("Vision worker is unavailable");
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error("Vision worker timed out"));
      }, 15_000);
      this.pending.set(id, { resolve, reject, timer });
      child.stdin.write(`${JSON.stringify({ id, images: images.map((image) => image.toString("base64")) })}\n`);
    });
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
    const child = this.child;
    this.child = undefined;
    this.ready = undefined;
    if (!child || child.exitCode !== null) return;
    child.kill("SIGTERM");
  }
}
