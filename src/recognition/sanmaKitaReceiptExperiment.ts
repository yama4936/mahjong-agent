import { createHash } from "node:crypto";
import sharp from "sharp";
import { inspectKitaTransition, type KitaObservation } from "../game/sanmaKitaTransitionExperiment.js";
import { inspectSanmaButtonRow, SANMA_BUTTON_ROW_RECT } from "./sanmaButtonRowExperiment.js";
import type { ExperimentalTemplates } from "./sanmaButtonExperiment.js";

/**
 * Offline evidence stitching: no page, pointer or click method is accepted.
 * The timestamp, click and tile observations are external claims. Every output
 * remains non-authorizing even when individual diagnostics are consistent.
 */
export async function inspectKitaReceiptExperiment(input: {
  beforeFrame: Buffer; afterFrame: Buffer; before: KitaObservation; after: KitaObservation;
  click: { action: "kita"; atMs: number; x: number; y: number };
  // Caller-chosen evidence window; timestamps remain untrusted claims.
  maxBeforeClickMs: number; maxAfterClickMs: number;
  buttonTemplates: ExperimentalTemplates; skipTemplate: Buffer; emptyRow: Buffer; ronTemplate?: Buffer;
}) {
  const failures: string[] = [];
  const digest = (frame: Buffer) => createHash("sha256").update(frame).digest("hex");
  if (!Buffer.isBuffer(input.beforeFrame) || !Buffer.isBuffer(input.afterFrame)) throw new Error("Frame bytes required");
  if (digest(input.beforeFrame) !== input.before.frameSha256 || digest(input.afterFrame) !== input.after.frameSha256) failures.push("frame digest mismatch");
  if (!input.click || input.click.action !== "kita") failures.push("no kita click claim");
  const times = [input.before.atMs, input.click?.atMs, input.after.atMs];
  const limits = [input.maxBeforeClickMs, input.maxAfterClickMs];
  if (!times.every(t => Number.isSafeInteger(t) && t >= 0) ||
      !limits.every(t => Number.isSafeInteger(t) && t > 0)) {
    failures.push("invalid evidence timing or window");
  } else if (input.click.atMs - input.before.atMs <= 0 ||
             input.click.atMs - input.before.atMs > input.maxBeforeClickMs ||
             input.after.atMs - input.click.atMs <= 0 ||
             input.after.atMs - input.click.atMs > input.maxAfterClickMs) {
    failures.push("evidence outside timing window");
  }
  const dimension = await sharp(input.beforeFrame).metadata();
  const afterDimension = await sharp(input.afterFrame).metadata();
  if (dimension.width !== 1920 || dimension.height !== 1080 || afterDimension.width !== 1920 || afterDimension.height !== 1080) failures.push("unreviewed frame dimensions");
  if (failures.length) return {status:"unresolved" as const, failures, operationAuthorized:false as const};
  const rect = SANMA_BUTTON_ROW_RECT;
  const row = await sharp(input.beforeFrame).extract(rect).png().toBuffer();
  const ui = await inspectSanmaButtonRow(row,input.buttonTemplates,input.skipTemplate,input.emptyRow,input.ronTemplate);
  const kita = ui.slots.filter(s => s.status === "candidate" && s.action === "kita");
  if (kita.length !== 1 || ui.slots.some(s => s.status === "unresolved" || (s.status === "candidate" && s.action !== "kita" && s.action !== "skip"))) failures.push("button row incomplete or competing prompt");
  if (kita.length === 1) {
    const x = 600 + kita[0]!.slot * 290;
    if (!Number.isFinite(input.click.x) || !Number.isFinite(input.click.y) || input.click.x < x || input.click.x >= x + 245 || input.click.y < 785 || input.click.y >= 875) failures.push("click claim outside candidate button");
  }
  const transition = inspectKitaTransition(input.before,input.after,input.click.atMs);
  if (transition.status !== "consistent_candidate") failures.push(...transition.failed.map(reason => `transition: ${reason}`));
  return {status: failures.length ? "unresolved" as const : "consistent_candidate" as const,
    failures, ui, transition, operationAuthorized:false as const};
}
