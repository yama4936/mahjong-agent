import { normalizeTile, toCounts, type GameTile } from "../game/tiles.js";
import type { TileMatch } from "./templateMatcher.js";
import type { VitTilePrediction } from "./vitRecognizer.js";

/** The model has 34 labels. Red identity must come from independently
 * calibrated 37-class evidence, never from normalizing away a disagreement. */
export function combineTileEvidence(template: TileMatch, model: VitTilePrediction, redIdentityCalibrated = false) {
  const isFive = /[05][mps]/.test(template.tile);
  const agrees = normalizeTile(template.tile) === model.tile;
  const accepted = agrees && (!isFive || redIdentityCalibrated)
    && template.confidence >= 0.98 && template.confidence - template.runnerUpConfidence >= 0.01
    && model.confidence >= 0.98 && model.confidence - model.runnerUpConfidence >= 0.01;
  return { tile: template.tile, accepted, agrees, redIdentityVerified: !isFive || redIdentityCalibrated,
    score: Math.min(template.confidence, model.confidence), scoreIsProbability: false as const };
}

export interface HandObservation { roundId: string; capturedAt: number; tiles: GameTile[]; accepted: boolean }

/** Independent captures, same round, identical order, bounded age. Repeated
 * frames reduce animation errors but cannot correct a systematic wrong label. */
export class HandConsensus {
  private observations: HandObservation[] = [];
  constructor(private readonly required = 3, private readonly maximumAgeMs = 10_000) {
    if (!Number.isInteger(required) || required < 2 || maximumAgeMs <= 0) throw new Error("Invalid consensus limits");
  }
  observe(frame: HandObservation): boolean {
    const prior = this.observations.at(-1);
    if (!Number.isFinite(frame.capturedAt) || !frame.accepted || frame.tiles.length !== 14) { this.observations = []; return false; }
    try { toCounts(frame.tiles); } catch { this.observations = []; return false; }
    if (prior && frame.capturedAt <= prior.capturedAt) { this.observations = []; return false; }
    if (prior && (prior.roundId !== frame.roundId || prior.tiles.join() !== frame.tiles.join())) this.observations = [];
    this.observations = this.observations.filter(f => frame.capturedAt - f.capturedAt <= this.maximumAgeMs);
    this.observations.push({ ...frame, tiles: [...frame.tiles] });
    this.observations = this.observations.slice(-this.required);
    return this.observations.length >= this.required;
  }
}
