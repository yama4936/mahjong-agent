import sharp from "sharp";

/** Offline experiment only: never used as a click target or action certificate. */
export const EXPERIMENTAL_BUTTONS = ["kita", "riichi", "tsumo", "kan", "pon"] as const;
export type ExperimentalButton = typeof EXPERIMENTAL_BUTTONS[number];
export type ExperimentalTemplates = Record<ExperimentalButton, Buffer>;
export type ExperimentalMatch =
  | { status: "matched"; action: ExperimentalButton; confidence: number; margin: number }
  | { status: "unresolved"; reason: "low_confidence" | "ambiguous"; confidence: number; margin: number };

async function signature(image: Buffer): Promise<Buffer> {
  return sharp(image).resize(64, 24, { fit: "fill" }).removeAlpha().raw().toBuffer();
}

/**
 * Compare one already-cropped button against all five competing labels.
 * Threshold and margin are experimental and calibrated only to one friend
 * match; the result is not a validated screen recognizer or permission to act.
 * A missing competing reference is an error, not evidence for another label.
 */
export async function classifySanmaButtonCrop(crop: Buffer, templates: ExperimentalTemplates): Promise<ExperimentalMatch> {
  if (!Buffer.isBuffer(crop) || !templates || EXPERIMENTAL_BUTTONS.some(action => !Buffer.isBuffer(templates[action]))) {
    throw new Error("All five button templates and a crop are required");
  }
  const observed = await signature(crop);
  const values = await Promise.all(EXPERIMENTAL_BUTTONS.map(async action => {
    const expected = await signature(templates[action]);
    if (expected.length !== observed.length || !observed.length) throw new Error("Invalid button image");
    let difference = 0;
    for (let i = 0; i < observed.length; i++) difference += Math.abs(observed[i]! - expected[i]!);
    return { action, confidence: 1 - difference / (observed.length * 255) };
  }));
  values.sort((a, b) => b.confidence - a.confidence);
  const best = values[0]!;
  const margin = best.confidence - values[1]!.confidence;
  if (best.confidence < 0.98) return { status: "unresolved", reason: "low_confidence", confidence: best.confidence, margin };
  if (margin < 0.03) return { status: "unresolved", reason: "ambiguous", confidence: best.confidence, margin };
  return { status: "matched", action: best.action, confidence: best.confidence, margin };
}
