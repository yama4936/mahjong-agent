import sharp from "sharp";
import { classifySanmaButtonCrop, type ExperimentalButton, type ExperimentalTemplates } from "./sanmaButtonExperiment.js";

/** A fixed-geometry diagnostic of the entire observed action row, never an action certificate. */
export const SANMA_BUTTON_ROW_RECT = { left: 600, top: 785, width: 825, height: 90 } as const;
const SLOT_OFFSETS = [0, 290, 580] as const;
const SLOT_WIDTH = 245;
type SlotResult = { status: "candidate"; action: ExperimentalButton | "skip" | "ron"; slot: number; confidence: number }
  | { status: "empty_candidate"; slot: number; confidence: number }
  | { status: "unresolved"; slot: number; reason: string };

async function signature(image: Buffer): Promise<Buffer> {
  return sharp(image).resize(64, 24, { fit: "fill" }).removeAlpha().raw().toBuffer();
}
async function similarity(a: Buffer, b: Buffer): Promise<number> {
  const [x, y] = await Promise.all([signature(a), signature(b)]);
  if (x.length !== y.length || !x.length) throw new Error("invalid slot image");
  let sum = 0;
  for (let i = 0; i < x.length; i++) sum += Math.abs(x[i]! - y[i]!);
  return 1 - sum / (x.length * 255);
}

/**
 * Operates only on a 825×90 crop from the documented 1920×1080 viewport.
 * Three slots cover observed two/three-button layouts; more-left positions are unverified,
 * a blank-looking region is only a same-scene visual candidate. Unknown buttons,
 * animations, occlusion, and unobserved positions prevent completeness claims.
 */
export async function inspectSanmaButtonRow(row: Buffer, templates: ExperimentalTemplates, skip: Buffer, emptyRow: Buffer, ronReference?: Buffer) {
  const dimensions = await sharp(row).metadata();
  const emptyDimensions = await sharp(emptyRow).metadata();
  if (dimensions.width !== SANMA_BUTTON_ROW_RECT.width || dimensions.height !== SANMA_BUTTON_ROW_RECT.height ||
      emptyDimensions.width !== dimensions.width || emptyDimensions.height !== dimensions.height) throw new Error("unreviewed button row dimensions");
  const slots = await Promise.all(SLOT_OFFSETS.map(async (offset, slot): Promise<SlotResult> => {
    const rect = { left: offset, top: 0, width: SLOT_WIDTH, height: 90 };
    const [crop, blank] = await Promise.all([sharp(row).extract(rect).png().toBuffer(), sharp(emptyRow).extract(rect).png().toBuffer()]);
    const [action, skipConfidence, emptyConfidence, ronConfidence] = await Promise.all([
      classifySanmaButtonCrop(crop, templates), similarity(crop, skip), similarity(crop, blank),
      ronReference ? similarity(crop, ronReference) : Promise.resolve(0),
    ]);
    if (action.status === "matched" && action.confidence > skipConfidence + 0.03 && action.confidence > emptyConfidence + 0.03 && action.confidence > ronConfidence + 0.03) {
      return { status: "candidate", action: action.action, slot, confidence: action.confidence };
    }
    if (ronConfidence >= 0.98 && ronConfidence > action.confidence + 0.03 && ronConfidence > skipConfidence + 0.03 && ronConfidence > emptyConfidence + 0.03) {
      return { status: "candidate", action: "ron", slot, confidence: ronConfidence };
    }
    if (skipConfidence >= 0.98 && skipConfidence > action.confidence + 0.03 && skipConfidence > emptyConfidence + 0.03 && skipConfidence > ronConfidence + 0.03) {
      return { status: "candidate", action: "skip", slot, confidence: skipConfidence };
    }
    if (emptyConfidence >= 0.98 && emptyConfidence > action.confidence + 0.03 && emptyConfidence > skipConfidence + 0.03 && emptyConfidence > ronConfidence + 0.03) {
      return { status: "empty_candidate", slot, confidence: emptyConfidence };
    }
    return { status: "unresolved", slot, reason: "unknown, obscured, animated, or ambiguous slot" };
  }));
  return { scope: "offline_untrusted_sanma_button_row" as const, slots, complete: false as const, operationAuthorized: false as const };
}
