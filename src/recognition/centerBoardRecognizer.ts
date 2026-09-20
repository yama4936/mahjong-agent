import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import sharp from "sharp";
import { z } from "zod";
import type { Rect, ScreenLayout } from "./layout.js";

const seatSchema = z.enum(["east", "south", "west", "north"]);
const scoresSchema = z.object({
  east: z.number().int(), south: z.number().int(), west: z.number().int(), north: z.number().int(),
});

const referenceSampleSchema = z.object({
  screenshot: z.string().min(1),
  round: z.string().regex(/^(east|south|west|north)_[1-4]$/),
  honba: z.number().int().min(0),
  riichiSticks: z.number().int().min(0),
  remainingTiles: z.number().int().min(0).max(70),
  ownSeat: seatSchema,
  scores: scoresSchema,
});

export const centerBoardReferenceManifestSchema = z.object({
  schemaVersion: z.literal(1),
  viewport: z.object({ width: z.number().int().positive(), height: z.number().int().positive() }),
  samples: z.array(referenceSampleSchema).min(1),
});

export type CenterBoardReferenceManifest = z.infer<typeof centerBoardReferenceManifestSchema>;
export type CenterBoardField = "round" | "honba" | "riichiSticks" | "remainingTiles" | "ownSeat" |
  "ownScore" | "rightScore" | "oppositeScore" | "leftScore";

export interface CenterBoardFieldMatch {
  field: CenterBoardField;
  value?: string;
  confidence: number;
  runnerUpConfidence: number;
  ambiguityMargin: number;
  safe: boolean;
  reference: string;
}

export interface CenterBoardObservation {
  round?: string;
  honba?: number;
  riichiSticks?: number;
  remainingTiles?: number;
  ownSeat?: z.infer<typeof seatSchema>;
  scores?: Partial<Record<z.infer<typeof seatSchema>, number>>;
  fields: Record<CenterBoardField, CenterBoardFieldMatch>;
  confidence: number;
  complete: boolean;
  trusted: false;
  consistencyErrors: string[];
  safetyReasons: string[];
  referenceSetFingerprint: string;
}

interface PreparedImage { data: Uint8Array; }
interface PreparedReference { label: string; screenshot: string; image: PreparedImage; }

const FIELDS: CenterBoardField[] = [
  "round", "honba", "riichiSticks", "remainingTiles", "ownSeat",
  "ownScore", "rightScore", "oppositeScore", "leftScore",
];
const SEATS = ["east", "south", "west", "north"] as const;

async function cropField(source: string | Buffer, region: Rect & { rotationToUpright?: 0 | 90 | 180 | 270 }): Promise<PreparedImage> {
  const { data } = await sharp(source)
    .extract({ left: region.x, top: region.y, width: region.width, height: region.height })
    .rotate(region.rotationToUpright ?? 0)
    .resize(64, 32, { fit: "fill" })
    .greyscale()
    .normalise()
    .raw()
    .toBuffer({ resolveWithObject: true });
  return { data: new Uint8Array(data) };
}

function similarity(left: PreparedImage, right: PreparedImage): number {
  if (left.data.length !== right.data.length) return 0;
  let absoluteDifference = 0;
  for (let index = 0; index < left.data.length; index += 1) {
    absoluteDifference += Math.abs(left.data[index]! - right.data[index]!);
  }
  return Math.max(0, 1 - absoluteDifference / (left.data.length * 255));
}

function relativeSeat(ownSeat: z.infer<typeof seatSchema>, offset: number): z.infer<typeof seatSchema> {
  return SEATS[(SEATS.indexOf(ownSeat) + offset) % 4]!;
}

function labelFor(sample: z.infer<typeof referenceSampleSchema>, field: CenterBoardField): string {
  if (field === "round") return sample.round;
  if (field === "honba") return String(sample.honba);
  if (field === "riichiSticks") return String(sample.riichiSticks);
  if (field === "remainingTiles") return String(sample.remainingTiles);
  if (field === "ownSeat") return sample.ownSeat;
  const offset = field === "ownScore" ? 0 : field === "rightScore" ? 1 : field === "oppositeScore" ? 2 : 3;
  return String(sample.scores[relativeSeat(sample.ownSeat, offset)]);
}

function fingerprint(manifest: CenterBoardReferenceManifest): string {
  return createHash("sha256").update(JSON.stringify(manifest)).digest("hex");
}

function parseInteger(match: CenterBoardFieldMatch): number | undefined {
  if (!match.safe || match.value === undefined || !/^\d+$/.test(match.value)) return undefined;
  return Number(match.value);
}

/**
 * Reads calibrated center-board fields by comparing each configured ROI with
 * labeled reference frames. Unknown or ambiguous values remain absent. This
 * recognizer is deliberately never trusted for Auto until an independent
 * calibration certificate is implemented and validated.
 */
export async function recognizeCenterBoard(
  screenshot: string | Buffer,
  layout: ScreenLayout,
  manifestPath: string,
  options: { minimumConfidence?: number; minimumMargin?: number } = {},
): Promise<CenterBoardObservation> {
  if (!layout.centerBoardRegions) throw new Error("Layout has no centerBoardRegions");
  const manifest = centerBoardReferenceManifestSchema.parse(JSON.parse(await readFile(manifestPath, "utf8")));
  if (manifest.viewport.width !== layout.viewport.width || manifest.viewport.height !== layout.viewport.height) {
    throw new Error("Center-board reference viewport does not match layout");
  }
  const minimumConfidence = options.minimumConfidence ?? 0.97;
  const minimumMargin = options.minimumMargin ?? 0.01;
  const base = path.dirname(path.resolve(manifestPath));
  const referenceByField = new Map<CenterBoardField, PreparedReference[]>();
  await Promise.all(manifest.samples.flatMap((sample) => FIELDS.map(async (field) => {
    const region = layout.centerBoardRegions![field];
    const referencePath = path.resolve(base, sample.screenshot);
    const image = await cropField(referencePath, region);
    const list = referenceByField.get(field) ?? [];
    list.push({ label: labelFor(sample, field), screenshot: referencePath, image });
    referenceByField.set(field, list);
  })));

  const matches = await Promise.all(FIELDS.map(async (field): Promise<[CenterBoardField, CenterBoardFieldMatch]> => {
    const current = await cropField(screenshot, layout.centerBoardRegions![field]);
    const references = referenceByField.get(field) ?? [];
    const bestPerLabel = new Map<string, { confidence: number; screenshot: string }>();
    for (const reference of references) {
      const confidence = similarity(current, reference.image);
      const previous = bestPerLabel.get(reference.label);
      if (!previous || confidence > previous.confidence) bestPerLabel.set(reference.label, { confidence, screenshot: reference.screenshot });
    }
    const ranked = [...bestPerLabel.entries()].map(([label, value]) => ({ label, ...value }))
      .sort((left, right) => right.confidence - left.confidence);
    const best = ranked[0];
    const runnerUpConfidence = ranked[1]?.confidence ?? 0;
    const confidence = best?.confidence ?? 0;
    const ambiguityMargin = confidence - runnerUpConfidence;
    const safe = Boolean(best) && confidence >= minimumConfidence && ambiguityMargin >= minimumMargin;
    return [field, {
      field,
      ...(safe ? { value: best!.label } : {}),
      confidence,
      runnerUpConfidence,
      ambiguityMargin,
      safe,
      reference: best?.screenshot ?? "",
    }];
  }));
  const fields = Object.fromEntries(matches) as Record<CenterBoardField, CenterBoardFieldMatch>;
  const ownSeat = fields.ownSeat.safe ? seatSchema.safeParse(fields.ownSeat.value).data : undefined;
  const relativeScores = [fields.ownScore, fields.rightScore, fields.oppositeScore, fields.leftScore].map(parseInteger);
  const scores: Partial<Record<z.infer<typeof seatSchema>, number>> = {};
  if (ownSeat) relativeScores.forEach((score, offset) => { if (score !== undefined) scores[relativeSeat(ownSeat, offset)] = score; });
  const consistencyErrors: string[] = [];
  const riichiSticks = parseInteger(fields.riichiSticks);
  const scoreValues = Object.values(scores);
  if (scoreValues.some((score) => score % 100 !== 0)) consistencyErrors.push("score_not_multiple_of_100");
  if (scoreValues.length === 4 && riichiSticks !== undefined
    && scoreValues.reduce((sum, score) => sum + score, 0) + riichiSticks * 1000 !== 100000) {
    consistencyErrors.push("score_and_riichi_pool_total_invalid");
  }
  const complete = FIELDS.every((field) => fields[field].safe) && ownSeat !== undefined
    && Object.keys(scores).length === 4 && consistencyErrors.length === 0;
  const confidence = Math.min(...FIELDS.map((field) => fields[field].confidence));
  return {
    ...(fields.round.safe ? { round: fields.round.value } : {}),
    ...(parseInteger(fields.honba) !== undefined ? { honba: parseInteger(fields.honba)! } : {}),
    ...(parseInteger(fields.riichiSticks) !== undefined ? { riichiSticks: parseInteger(fields.riichiSticks)! } : {}),
    ...(parseInteger(fields.remainingTiles) !== undefined ? { remainingTiles: parseInteger(fields.remainingTiles)! } : {}),
    ...(ownSeat ? { ownSeat, scores } : {}),
    fields,
    confidence,
    complete,
    trusted: false,
    consistencyErrors,
    safetyReasons: ["center_board_independent_calibration_missing"],
    referenceSetFingerprint: fingerprint(manifest),
  };
}

export class CenterBoardConsensus {
  private observations: CenterBoardObservation[] = [];

  constructor(private readonly requiredFrames = 3) {
    if (!Number.isInteger(requiredFrames) || requiredFrames < 2) throw new Error("requiredFrames must be at least 2");
  }

  observe(observation: CenterBoardObservation): CenterBoardObservation | undefined {
    if (!observation.complete) { this.observations = []; return undefined; }
    const signature = JSON.stringify([observation.round, observation.honba, observation.riichiSticks, observation.remainingTiles, observation.ownSeat, observation.scores]);
    const previous = this.observations.at(-1);
    const previousSignature = previous && JSON.stringify([previous.round, previous.honba, previous.riichiSticks, previous.remainingTiles, previous.ownSeat, previous.scores]);
    if (previousSignature && previousSignature !== signature) this.observations = [];
    this.observations.push(observation);
    if (this.observations.length < this.requiredFrames) return undefined;
    this.observations = this.observations.slice(-this.requiredFrames);
    return observation;
  }
}
