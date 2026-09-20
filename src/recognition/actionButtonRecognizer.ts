import path from "node:path";
import { access } from "node:fs/promises";
import sharp from "sharp";
import type { ScreenLayout } from "./layout.js";

export const ACTION_BUTTONS = ["riichi", "tsumo", "ron", "chi", "pon", "kan", "kyuushu", "pass"] as const;
export type ActionButton = typeof ACTION_BUTTONS[number];

export interface ActionButtonMatch {
  action: ActionButton;
  confidence: number;
  present: boolean;
  center: { x: number; y: number };
}

async function signature(image: string | Buffer, extract?: { left: number; top: number; width: number; height: number }): Promise<Buffer> {
  let pipeline = sharp(image);
  if (extract) pipeline = pipeline.extract(extract);
  return pipeline.resize(64, 24, { fit: "fill" }).removeAlpha().raw().toBuffer();
}

function similarity(left: Buffer, right: Buffer): number {
  if (left.length !== right.length || left.length === 0) return 0;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference += Math.abs(left[index]! - right[index]!);
  return Math.max(0, 1 - difference / (left.length * 255));
}

/**
 * Matches only explicitly calibrated action-button regions. Missing templates
 * or regions produce no action, so UI actions can never be invented.
 */
export async function recognizeActionButtons(
  screenshot: string | Buffer,
  layout: ScreenLayout,
  templateDirectory: string,
  minimumConfidence = 0.98,
): Promise<ActionButtonMatch[]> {
  const matches: ActionButtonMatch[] = [];
  for (const action of ACTION_BUTTONS) {
    const region = layout.actionButtonRegions?.[action];
    if (!region) continue;
    const template = path.join(templateDirectory, `${action}.png`);
    try {
      await access(template);
    } catch {
      continue;
    }
    const [observed, expected] = await Promise.all([
      signature(screenshot, { left: region.x, top: region.y, width: region.width, height: region.height }),
      signature(template),
    ]);
    const confidence = similarity(observed, expected);
    matches.push({
      action,
      confidence,
      present: confidence >= minimumConfidence,
      center: { x: region.x + region.width / 2, y: region.y + region.height / 2 },
    });
  }
  return matches;
}

export function availableUiActions(matches: readonly ActionButtonMatch[]): ActionButton[] {
  return matches.filter((match) => match.present).map((match) => match.action);
}
