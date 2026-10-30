import { createHash } from "node:crypto";
import sharp from "sharp";
import { evaluateDiscards } from "../game/ukeire.js";
import { proposeLiveHandLayout } from "./handLayoutProposal.js";
import type { ScreenLayout } from "./layout.js";
import { recognizeHand } from "./templateMatcher.js";
import { classifySanmaButtonCrop, type ExperimentalTemplates } from "./sanmaButtonExperiment.js";
import { recognizeSanmaPublicCandidates, type PublicVitClassifier } from "./publicTileRecognizer.js";

/** Read-only frame experiment. No result in this function authorizes play. */
export async function inspectSanmaFrame(input: {
  frame: Buffer; layout: ScreenLayout; templates: string; buttonTemplates: ExperimentalTemplates;
  ownSeat: "east" | "south" | "west"; publicClassifier: PublicVitClassifier;
}) {
  if (!Buffer.isBuffer(input.frame)) throw new Error("Frame bytes required");
  // The same immutable snapshot is used for every branch. Paths are not
  // accepted, since a live screenshot file can change during recognition.
  const frame = Buffer.from(input.frame);
  const digest = createHash("sha256").update(frame).digest("hex");
  const image = sharp(frame);
  const dimensions = await image.metadata();
  if (dimensions.width !== 1920 || dimensions.height !== 1080) throw new Error("Unreviewed frame dimensions");
  const handPromise = (async () => {
    const proposal = await proposeLiveHandLayout(frame);
    const recognition = await recognizeHand(frame, { ...input.layout, ...proposal }, input.templates);
    return { recognition, proposal };
  })();
  const publicPromise = recognizeSanmaPublicCandidates(frame, input.layout, input.ownSeat, input.publicClassifier);
  const buttonPromise = (async () => {
    const crop = await sharp(frame).extract({ left: 890, top: 785, width: 245, height: 90 }).png().toBuffer();
    return classifySanmaButtonCrop(crop, input.buttonTemplates);
  })();
  const [hand, publicTiles, button] = await Promise.allSettled([handPromise, publicPromise, buttonPromise]);
  const describe = <T>(value: PromiseSettledResult<T>) => value.status === "fulfilled"
    ? { status: "candidate" as const, value: value.value }
    : { status: "unresolved" as const, reason: value.reason instanceof Error ? value.reason.message : String(value.reason) };
  // A single cropped button, missing public tiles and uncertain meld/riichi
  // status cannot authorize a decision. Produce only hypothetical closed-hand
  // shape calculations, assuming zero outside tiles; they are not a policy.
  let shape: { status: "hypothesis"; assumptions: string[]; rows: ReturnType<typeof evaluateDiscards> } | { status: "unresolved"; reason: string };
  if (hand.status === "fulfilled" && hand.value.recognition.safe && hand.value.recognition.tiles.length === 14) {
    try {
      shape = { status: "hypothesis", assumptions: ["closed hand", "no visible tiles", "no action priority", "hand labels correct"],
        rows: evaluateDiscards(hand.value.recognition.tiles, [], 0, "sanma") };
    } catch (error) { shape = { status: "unresolved", reason: error instanceof Error ? error.message : String(error) }; }
  } else shape = { status: "unresolved", reason: "No complete candidate hand" };
  return { scope: "offline_untrusted_sanma_frame" as const, digest,
    hand: hand.status === "fulfilled" ? describe({ status: "fulfilled", value: hand.value.recognition }) : { status: "unresolved" as const, reason: hand.reason instanceof Error ? hand.reason.message : String(hand.reason) },
    handGeometry: hand.status === "fulfilled" ? describe({ status: "fulfilled", value: hand.value.proposal }) : { status: "unresolved" as const, reason: hand.reason instanceof Error ? hand.reason.message : String(hand.reason) },
    publicTiles: describe(publicTiles), button: describe(button), shape,
    decision: { status: "blocked" as const, reasons: ["hand recognition unverified", "public observations incomplete",
      "single crop does not establish all available actions", "turn, meld and riichi status unverified"] },
    operationAuthorized: false as const };
}


/** Binds only a hypothetical shape row to candidate physical positions.
 * This is diagnostic evidence, never permission or a click target.
 */
export function bindSanmaDiscardHypothesis(
  report: Awaited<ReturnType<typeof inspectSanmaFrame>>, frame: Buffer, rowIndex: number,
) {
  const blockers: string[] = [];
  if (!Buffer.isBuffer(frame) || createHash("sha256").update(frame).digest("hex") !== report.digest) {
    blockers.push("frame digest differs from observation");
    return { status: "blocked" as const, digest: report.digest, blockers, operationAuthorized: false as const };
  }
  if (report.hand.status !== "candidate") blockers.push("hand recognition failed");
  else if (!report.hand.value.safe) blockers.push("hand recognition did not meet confidence requirements");
  if (report.handGeometry.status !== "candidate") blockers.push("hand positions unavailable");
  else if (report.handGeometry.value.requiresHoldoutValidation) blockers.push("physical positions lack holdout calibration");
  if (report.publicTiles.status !== "candidate" || !report.publicTiles.value.observation.complete) blockers.push("public tiles incomplete");
  if (report.button.status !== "candidate" || report.button.value.status !== "matched") blockers.push("button crop unrecognized");
  else blockers.push(`button ${report.button.value.action} is only a single unverified crop`);
  blockers.push("full action list, turn, melds and riichi status are unverified");
  if (report.shape.status !== "hypothesis" || !Number.isInteger(rowIndex) || rowIndex < 0 || rowIndex >= report.shape.rows.length) {
    blockers.push("discard shape hypothesis unavailable");
    return { status: "blocked" as const, digest: report.digest, blockers, operationAuthorized: false as const };
  }
  const row = report.shape.rows[rowIndex]!;
  if (report.hand.status !== "candidate" || report.handGeometry.status !== "candidate") {
    return { status: "blocked" as const, digest: report.digest, blockers, operationAuthorized: false as const };
  }
  const geometry = report.handGeometry.value;
  const slots = [...geometry.handSlots, geometry.drawSlot];
  if (slots.length !== report.hand.value.tiles.length || slots.length !== report.handGeometry.value.clickPoints.length) {
    blockers.push("hand and physical position counts differ");
    return { status: "blocked" as const, digest: report.digest, blockers, operationAuthorized: false as const };
  }
  const positions = report.hand.value.tiles.flatMap((tile, index) => tile === row.tile
    ? [{ index, rect: slots[index]!, point: geometry.clickPoints[index]! }] : []);
  if (!positions.length) blockers.push("hypothetical tile has no matching physical position");
  // Never select one of several equal physical tiles; drawn-tile and red-tile
  // distinctions and action side effects need independent confirmation.
  return { status: "blocked" as const, digest: report.digest, blockers, hypothesis: { row, positions },
    operationAuthorized: false as const };
}
