import { createHash } from "node:crypto";
import sharp from "sharp";
import { evaluateDiscards } from "../game/ukeire.js";
import { proposeLiveHandLayout, knownOpenHandProposalFitsCalibratedRow } from "./handLayoutProposal.js";
import { recoverSanmaRaisedHand } from "./sanmaRaisedHandRecovery.js";
import { recoverSanmaRaisedDrawAfterTwoCalls } from "./sanmaRaisedDrawRecovery.js";
import { recoverSanmaRaisedFive } from "./sanmaRaisedFiveRecovery.js";
import { recoverSanmaRaisedClosedHand } from "./sanmaRaisedClosedHandRecovery.js";
import { recoverSanmaRaisedClosedDraw } from "./sanmaRaisedClosedDrawRecovery.js";
import type { ScreenLayout } from "./layout.js";
import { recognizeTileSlots } from "./templateMatcher.js";
import { classifySanmaButtonCrop, type ExperimentalTemplates } from "./sanmaButtonExperiment.js";
import { inspectSanmaButtonRow, SANMA_BUTTON_ROW_RECT } from "./sanmaButtonRowExperiment.js";
import { sanmaOwnMeldExperiment } from "./sanmaOwnMeldExperiment.js";
import { recognizeSanmaPublicCandidates, type PublicVitClassifier } from "./publicTileRecognizer.js";

/** Read-only frame experiment. No result in this function authorizes play. */
export async function inspectSanmaFrame(input: {
  frame: Buffer; layout: ScreenLayout; templates: string; buttonTemplates: ExperimentalTemplates;
  ownSeat?: "east" | "south" | "west";
  ownSeatPromise?: Promise<"east" | "south" | "west" | undefined>; publicClassifier: PublicVitClassifier;
  buttonRowReferences?: { skip: Buffer; emptyRow: Buffer; ron?: Buffer };
  assumedHandRightEdge?: number;
}) {
  if (!Buffer.isBuffer(input.frame)) throw new Error("Frame bytes required");
  // Attach the rejection handler before the first image await; OCR may fail
  // immediately while metadata is still being read.
  const seatResolution = input.ownSeatPromise?.then(value => ({ ok: true as const, value }),
    error => ({ ok: false as const, error }));
  // The same immutable snapshot is used for every branch. Paths are not
  // accepted, since a live screenshot file can change during recognition.
  const frame = Buffer.from(input.frame);
  const digest = createHash("sha256").update(frame).digest("hex");
  const image = sharp(frame);
  const dimensions = await image.metadata();
  if (dimensions.width !== 1920 || dimensions.height !== 1080) throw new Error("Unreviewed frame dimensions");
  const handPromise = (async () => {
    let unverifiedClosedRecovery = false;
    let proposal;
    try { proposal = await proposeLiveHandLayout(frame); }
    catch (error) {
      const recovered = await recoverSanmaRaisedClosedDraw(frame,input.layout);
      if (!recovered) throw error;
      proposal = recovered;
      unverifiedClosedRecovery = true;
    }
    if (proposal.evidence.detectedTiles === 2 && !knownOpenHandProposalFitsCalibratedRow(proposal, input.layout, 4)) {
      let recovered = await recoverSanmaRaisedHand(frame, input.layout, proposal)
        ?? await recoverSanmaRaisedDrawAfterTwoCalls(frame, input.layout, proposal)
        ?? await recoverSanmaRaisedFive(frame, input.layout, proposal);
      if (!recovered) {
        recovered = await recoverSanmaRaisedClosedHand(frame,input.layout,proposal);
        unverifiedClosedRecovery = Boolean(recovered);
      }
      if (!recovered) throw new Error("suspected false compact hand and raised-row recovery unavailable");
      proposal = recovered;
    }
    const slots = [...proposal.handSlots, proposal.drawSlot];
    const classified = await recognizeTileSlots(frame, slots, { ...input.layout, ...proposal }, input.templates);
    const possibleMelds = (14 - slots.length) / 3;
    const recognizedAll = classified.matches.length === slots.length;
    // Row length suggests a possible number of melds but is not proof; a
    // concealed or raised tile may be missed. Never authorize it as safe.
    const candidateMelds = recognizedAll && Number.isInteger(possibleMelds) && possibleMelds >= 0 && possibleMelds <= 4
      ? possibleMelds : undefined;
    const recognition = {...classified, turnReady:recognizedAll && slots.length === 14 && !unverifiedClosedRecovery,
      safe:classified.safe && recognizedAll && slots.length === 14 && !unverifiedClosedRecovery,
      slotClassificationSafe:classified.safe && recognizedAll,
      ...(candidateMelds !== undefined ? {candidateMelds} : {})};
    return { recognition, proposal };
  })();
  const publicPromise = (async () => {
    const resolved = seatResolution ? await seatResolution : undefined;
    if (resolved && !resolved.ok) throw resolved.error;
    const ownSeat = resolved ? resolved.value : input.ownSeat;
    if (!ownSeat) throw new Error("own seat unknown: opponent mapping unavailable");
    return recognizeSanmaPublicCandidates(frame, input.layout, ownSeat, input.publicClassifier);
  })();
  const buttonPromise = (async () => {
    const crop = await sharp(frame).extract({ left: 890, top: 785, width: 245, height: 90 }).png().toBuffer();
    return classifySanmaButtonCrop(crop, input.buttonTemplates);
  })();
  const buttonRowPromise = (async () => {
    if (!input.buttonRowReferences) throw new Error("button row references missing");
    const row = await sharp(frame).extract(SANMA_BUTTON_ROW_RECT).png().toBuffer();
    return inspectSanmaButtonRow(row, input.buttonTemplates, input.buttonRowReferences.skip, input.buttonRowReferences.emptyRow, input.buttonRowReferences.ron);
  })();
  const ownMeldPromise = sanmaOwnMeldExperiment(frame, input.layout, input.publicClassifier, input.assumedHandRightEdge);
  const [hand, publicTiles, button, buttonRow, ownMelds] = await Promise.allSettled([
    handPromise, publicPromise, buttonPromise, buttonRowPromise, ownMeldPromise,
  ]);
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
  const decisionReasons = ["hand recognition unverified", "public observations incomplete",
    "action row incomplete", "turn, meld and riichi status unverified"];
  if (buttonRow.status === "rejected") decisionReasons.push("button row unavailable");
  else {
    for (const slot of buttonRow.value.slots) {
      if (slot.status === "candidate") decisionReasons.push(`possible ${slot.action} in button slot ${slot.slot}`);
      if (slot.status === "unresolved") decisionReasons.push(`button slot ${slot.slot} unresolved`);
    }
  }
  if (ownMelds.status === "rejected") decisionReasons.push("own meld observation failed");
  else if (ownMelds.value.reason) decisionReasons.push(`own melds unknown: ${ownMelds.value.reason}`);
  else decisionReasons.push("own meld hypotheses unverified");
  return { scope: "offline_untrusted_sanma_frame" as const, digest,
    hand: hand.status === "fulfilled" ? describe({ status: "fulfilled", value: hand.value.recognition }) : { status: "unresolved" as const, reason: hand.reason instanceof Error ? hand.reason.message : String(hand.reason) },
    handGeometry: hand.status === "fulfilled" ? describe({ status: "fulfilled", value: hand.value.proposal }) : { status: "unresolved" as const, reason: hand.reason instanceof Error ? hand.reason.message : String(hand.reason) },
    publicTiles: describe(publicTiles), button: describe(button), buttonRow: describe(buttonRow), ownMelds: describe(ownMelds), shape,
    decision: { status: "blocked" as const, reasons: decisionReasons },
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
  if (report.buttonRow.status === "unresolved") blockers.push("button row unavailable");
  else {
    blockers.push("button row is not complete");
    for (const slot of report.buttonRow.value.slots) {
      if (slot.status === "candidate") blockers.push(`possible ${slot.action} in button slot ${slot.slot}`);
      if (slot.status === "unresolved") blockers.push(`button slot ${slot.slot} unresolved`);
    }
  }
  if (report.ownMelds.status === "unresolved") blockers.push("own meld observation failed");
  else blockers.push(`own melds unknown${report.ownMelds.value.reason ? `: ${report.ownMelds.value.reason}` : ""}`);
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
