import { createHash } from "node:crypto";
import { inspectSanmaSelfTurnPriority } from "../game/sanmaSelfTurnPriorityExperiment.js";
import { inspectSanmaDiscardSafety } from "../game/sanmaDiscardSafetyExperiment.js";
import type { inspectSanmaFrame } from "./sanmaFrameExperiment.js";

type FrameReport = Awaited<ReturnType<typeof inspectSanmaFrame>>;
type UiAction = "kita" | "tsumo" | "ron" | "pon" | "kan" | "pass" | "riichi";
/**
 * External human-reviewed state and complete UI evidence. This is a caller
 * assertion for offline research, never a certificate for the live operator.
 * Unknown fields must be omitted and evaluation will then reject them.
 */
export type ReviewedFrameEvidence = {
  digest: string; source: "external_review"; state: unknown;
  riichiStatus: "not_declared" | "declared"; ui: { status: "confirmed"; actions: readonly UiAction[] };
  turnContext: "ordinary_draw_confirmed"; handEvidence: "confirmed";
  meldEvidence: "confirmed"; visibleEvidence: "confirmed_complete";
};

export function evaluateSanmaFrameCandidate(input: {
  frame: Buffer; report: FrameReport; review?: ReviewedFrameEvidence; priorityOnly?: boolean;
}) {
  const reasons: string[] = [];
  const { frame, report, review, priorityOnly } = input;
  if (!Buffer.isBuffer(frame) || createHash("sha256").update(frame).digest("hex") !== report.digest) reasons.push("frame digest mismatch");
  if (!review || review.source !== "external_review") reasons.push("complete independent review missing");
  else if (review.digest !== report.digest) reasons.push("review digest mismatch");
  const openCandidate = report.hand.status === "candidate" && report.hand.value.candidateMelds !== undefined
    && report.hand.value.candidateMelds > 0 && report.hand.value.slotClassificationSafe
    && review?.handEvidence === "confirmed" && review.meldEvidence === "confirmed";
  if (report.hand.status !== "candidate" || (!report.hand.value.safe && !openCandidate)) reasons.push("hand recognition unconfirmed");
  if (report.publicTiles.status !== "candidate") reasons.push("public recognition failed");
  const accepts = (action: string) => priorityOnly === true && !!review && Array.isArray(review.ui?.actions)
    && review.ui.actions.includes((action === "skip" ? "pass" : action) as UiAction);
  if (report.button.status === "candidate" && report.button.value.status === "matched" && !accepts(report.button.value.action)) reasons.push(`visible ${report.button.value.action} button needs separate handling`);
  if (report.buttonRow?.status === "candidate") {
    for (const slot of report.buttonRow.value.slots) {
      if (slot.status === "candidate" && !accepts(slot.action)) reasons.push(`possible ${slot.action} button in slot ${slot.slot} needs separate handling`);
    }
  }
  if (reasons.length || !review || report.hand.status !== "candidate" || report.publicTiles.status !== "candidate") {
    return { status: "blocked" as const, reasons, operationAuthorized: false as const };
  }
  if (!review.state || typeof review.state !== "object" || Array.isArray(review.state)) {
    return {status: "blocked" as const, reasons: ["reviewed state missing"], operationAuthorized: false as const};
  }
  const state = review.state as Record<string, unknown>;
  const observed = report.hand.value.tiles;
  if (openCandidate && (state.openMelds !== report.hand.value.candidateMelds
      || !Array.isArray(state.melds) || state.melds.length !== report.hand.value.candidateMelds)) {
    return {status:"blocked" as const, reasons:["reviewed meld count conflicts with physical row candidate"],operationAuthorized:false as const};
  }
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
      || (report.ownMelds?.status === "candidate" && !containsMelds(state.melds, report.ownMelds.value.hypotheses))
      || !opponents
      || publicObservation.opponentDiscards.some(observedOpponent => {
        const opponent = opponents!.find((o: any) => o?.seat === observedOpponent.seat);
        return !opponent || !containsOrdered(opponent.discards, observedOpponent.discards)
          || !containsMelds(opponent.melds, observedOpponent.melds ?? []);
      })) return {status: "blocked" as const, reasons: ["reviewed public state conflicts with candidate tiles"], operationAuthorized: false as const};
  try {
    if (priorityOnly) {
      if (review.handEvidence !== "confirmed" || review.meldEvidence !== "confirmed"
          || review.turnContext !== "ordinary_draw_confirmed" || review.visibleEvidence !== "confirmed_complete") {
        throw new Error("complete self-turn evidence required");
      }
      const actions = review.ui.actions;
      if (actions.some(action => action === "ron" || action === "pon")) throw new Error("reaction action is not a self-turn priority");
      const priority = inspectSanmaSelfTurnPriority(review as Parameters<typeof inspectSanmaSelfTurnPriority>[0]);
      return { status:"offline_priority" as const, digest:report.digest, priority,
        assumptions:["external review is correct", "action list and self-turn status externally confirmed"], operationAuthorized:false as const };
    }
    if (review.riichiStatus === "declared") throw new Error("post-riichi discard requires separate handling");
    if (review.ui.actions.includes("riichi")) throw new Error("riichi requires separate handling");
    const { rows } = inspectSanmaDiscardSafety(review as Parameters<typeof inspectSanmaDiscardSafety>[0]);
    return {status: "offline_evaluation" as const, digest: report.digest, rows,
      assumptions: ["external review is correct", "genbutsu candidates are not a complete defense or point-value model"], operationAuthorized: false as const};
  } catch (error) {
    return {status: "blocked" as const, reasons: [error instanceof Error ? error.message : String(error)], operationAuthorized: false as const};
  }
}

/**
 * Assemble unverified observations for review without converting a missing
 * region, empty recognition, or extracted-north occlusion into a zero value.
 * Optional external review is a caller assertion and cannot authorize play.
 */
export function assembleSanmaEvaluation(input: {
  frame: Buffer;
  observation: Awaited<ReturnType<typeof import("./sanmaAutoFrameObservation.js").observeSanmaFrameAutomatically>>;
  review?: ReviewedFrameEvidence;
}) {
  const {frame, observation, review} = input;
  const digest = Buffer.isBuffer(frame) ? createHash("sha256").update(frame).digest("hex") : "";
  if (digest !== observation.digest || digest !== observation.report.digest ||
      Object.values(observation.north.positions ?? {}).some(position => position.frame_sha256 !== undefined && position.frame_sha256 !== digest)) {
    return {scope:"offline_untrusted_sanma_evaluation_assembly" as const, status:"blocked" as const,
      reasons:["frame evidence digest mismatch"], operationAuthorized:false as const};
  }
  const report = observation.report;
  const partial: Record<string, unknown> = {};
  // Candidate values are intentionally not promoted into a playable GameState.
  if (observation.ownSeat.status === "candidate") partial.seat = observation.ownSeat.value;
  if (observation.board.candidate) partial.board = observation.board.candidate;
  if (report.hand.status === "candidate" && report.hand.value.tiles.length) {
    partial.orderedHand = report.hand.value.tiles;
    partial.handRecognizerAccepted = report.hand.value.safe;
    if (report.hand.value.candidateMelds !== undefined && report.hand.value.candidateMelds > 0
        && report.hand.value.tiles.length === 14 - 3 * report.hand.value.candidateMelds) {
      partial.possibleOpenHand = { melds:report.hand.value.candidateMelds,
        concealed:report.hand.value.tiles.slice(0,-1), draw:report.hand.value.tiles.at(-1),
        slotClassificationSafe:report.hand.value.slotClassificationSafe, verified:false };
    }
  }
  if (report.publicTiles.status === "candidate") {
    const publicTiles = report.publicTiles.value.observation;
    const rivers = publicTiles.opponentDiscards.filter(o => o.discards.length).map(o => ({seat:o.seat, tiles:o.discards}));
    if (publicTiles.ownDiscards.length) partial.ownRiverCandidates = publicTiles.ownDiscards;
    if (publicTiles.doraIndicators.length) partial.doraCandidates = publicTiles.doraIndicators;
    if (rivers.length) partial.opponentRiverCandidates = rivers;
    if (publicTiles.ownMelds?.length) partial.ownMeldCandidates = publicTiles.ownMelds;
  }
  if (observation.candidates.candidates.length) partial.actionCandidates = observation.candidates.candidates;
  const missing = ["rules and seat not verified", "hand and draw not verified", "turn and riichi status unknown",
    "action list incomplete", "rivers and melds incomplete", "all three extracted north counts unknown"];
  let northConflict = false;
  if (review?.state && typeof review.state === "object" && !Array.isArray(review.state)) {
    const state = review.state as Record<string, unknown>;
    const own = observation.north.positions?.own;
    if (state.ownKitaCount === 0 && Array.isArray(own?.matches) && own.matches.length) northConflict = true;
    const seats = observation.north.bySeat;
    if (seats && Array.isArray(state.opponents)) {
      for (const opponent of state.opponents) {
        if (!opponent || typeof opponent !== "object") continue;
        const row = opponent as Record<string, unknown>;
        const position = seats[String(row.seat) as keyof typeof seats];
        if (row.kitaCount === 0 && position?.candidate) northConflict = true;
      }
    }
  }
  const evaluation = northConflict
    ? {status:"blocked" as const, reasons:["reviewed zero north count conflicts with visual candidate"],operationAuthorized:false as const}
    : evaluateSanmaFrameCandidate({frame, report, ...(review ? {review} : {})});
  const priority = northConflict
    ? {status:"blocked" as const, reasons:["reviewed zero north count conflicts with visual candidate"],operationAuthorized:false as const}
    : evaluateSanmaFrameCandidate({frame, report, ...(review ? {review} : {}), priorityOnly:true});
  return {scope:"offline_untrusted_sanma_evaluation_assembly" as const, status:"blocked" as const,
    digest, partial, missing, evaluation, priority, operationAuthorized:false as const};
}
