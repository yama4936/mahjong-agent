import { createHash } from "node:crypto";
import { sanmaDiscardExperiment } from "../game/sanmaDiscardExperiment.js";
import type { inspectSanmaFrame } from "./sanmaFrameExperiment.js";

type FrameReport = Awaited<ReturnType<typeof inspectSanmaFrame>>;
type UiAction = "kita" | "tsumo" | "ron" | "pon" | "kan" | "pass";
/**
 * External human-reviewed state and complete UI evidence. This is a caller
 * assertion for offline research, never a certificate for the live operator.
 * Unknown fields must be omitted and evaluation will then reject them.
 */
export type ReviewedFrameEvidence = {
  digest: string; source: "external_review"; state: unknown;
  riichiStatus: "not_declared"; ui: { status: "confirmed"; actions: readonly UiAction[] };
  turnContext: "ordinary_draw_confirmed"; handEvidence: "confirmed";
  meldEvidence: "confirmed"; visibleEvidence: "confirmed_complete";
};

export function evaluateSanmaFrameCandidate(input: {
  frame: Buffer; report: FrameReport; review?: ReviewedFrameEvidence;
}) {
  const reasons: string[] = [];
  const { frame, report, review } = input;
  if (!Buffer.isBuffer(frame) || createHash("sha256").update(frame).digest("hex") !== report.digest) reasons.push("frame digest mismatch");
  if (!review || review.source !== "external_review") reasons.push("complete independent review missing");
  else if (review.digest !== report.digest) reasons.push("review digest mismatch");
  if (report.hand.status !== "candidate" || !report.hand.value.safe) reasons.push("hand recognition unconfirmed");
  if (report.publicTiles.status !== "candidate") reasons.push("public recognition failed");
  if (report.button.status === "candidate" && report.button.value.status === "matched") reasons.push(`visible ${report.button.value.action} button needs separate handling`);
  if (reasons.length || !review || report.hand.status !== "candidate" || report.publicTiles.status !== "candidate") {
    return { status: "blocked" as const, reasons, operationAuthorized: false as const };
  }
  if (!review.state || typeof review.state !== "object" || Array.isArray(review.state)) {
    return {status: "blocked" as const, reasons: ["reviewed state missing"], operationAuthorized: false as const};
  }
  const state = review.state as Record<string, unknown>;
  const observed = report.hand.value.tiles;
  if (!Array.isArray(state.hand) || typeof state.draw !== "string" ||
      JSON.stringify([...state.hand, state.draw]) !== JSON.stringify(observed)) {
    return {status: "blocked" as const, reasons: ["reviewed physical hand differs from recognition"], operationAuthorized: false as const};
  }
  const publicObservation = report.publicTiles.value.observation;
  if (state.seat !== publicObservation.opponentDiscards.map(o => o.seat).reduce((seats, seat) => seats.filter(value => value !== seat), ["east", "south", "west"])[0]) {
    return {status: "blocked" as const, reasons: ["reviewed seat conflicts with observation"], operationAuthorized: false as const};
  }
  // Accepted partial observations must be a subsequence of the reviewed full
  // river; their omissions are not filled with zero and do not prove completeness.
  const containsOrdered = (full: unknown, partial: readonly string[]) => {
    if (!Array.isArray(full)) return false;
    let i = 0;
    for (const tile of full) if (tile === partial[i]) i++;
    return i === partial.length;
  };
  const containsMelds = (full: unknown, partial: readonly { type: string; tiles: readonly string[] }[]) => {
    if (!Array.isArray(full)) return false;
    const unused = [...full];
    return partial.every(meld => {
      const index = unused.findIndex(item => item?.type === meld.type && Array.isArray(item.tiles)
        && [...item.tiles].sort().join(",") === [...meld.tiles].sort().join(","));
      if (index < 0) return false;
      unused.splice(index, 1);
      return true;
    });
  };
  const opponents = Array.isArray(state.opponents) ? state.opponents : undefined;
  if (!containsOrdered(state.ownDiscards, publicObservation.ownDiscards)
      || !containsOrdered(state.doraIndicators, publicObservation.doraIndicators)
      || !containsMelds(state.melds, publicObservation.ownMelds ?? [])
      || !opponents
      || publicObservation.opponentDiscards.some(observedOpponent => {
        const opponent = opponents!.find((o: any) => o?.seat === observedOpponent.seat);
        return !opponent || !containsOrdered(opponent.discards, observedOpponent.discards)
          || !containsMelds(opponent.melds, observedOpponent.melds ?? []);
      })) return {status: "blocked" as const, reasons: ["reviewed public state conflicts with candidate tiles"], operationAuthorized: false as const};
  try {
    const rows = sanmaDiscardExperiment(review);
    return {status: "offline_evaluation" as const, digest: report.digest, rows,
      assumptions: ["external review is correct", "not a defense or point-value model"], operationAuthorized: false as const};
  } catch (error) {
    return {status: "blocked" as const, reasons: [error instanceof Error ? error.message : String(error)], operationAuthorized: false as const};
  }
}
