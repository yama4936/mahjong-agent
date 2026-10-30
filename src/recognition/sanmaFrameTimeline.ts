import { observeSanmaFrameAutomatically } from "./sanmaAutoFrameObservation.js";

type Observation = Awaited<ReturnType<typeof observeSanmaFrameAutomatically>>;
type FrameEntry = { index: number; observation: Observation };
type Comparison = "same_candidates" | "different_candidates" | "unknown";
export type SanmaFrameTimeline = {
  scope: "offline_untrusted_sanma_timeline"; status: "unknown"; operationAuthorized: false;
  latest: FrameEntry; previous?: FrameEntry; rejected?: FrameEntry;
  relationship: "first_frame" | "unproven_equal_board" | "possible_hand_boundary" | "board_unknown" | "invalid_frame_order" | "duplicate_frame" | "inconsistent_frame";
  notes: string[];
  comparison: { hand: Comparison; rivers: Comparison; north: Record<"own" | "opposite" | "left", Comparison> };
};

function boardIdentity(observation: Observation): string | undefined {
  const raw: unknown = observation.board.candidate;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const board = raw as Record<string, unknown>;
  if (!["east", "south", "west"].includes(String(board.seat)) || typeof board.round !== "string"
      || !/^(east|south)_[1-3]$/.test(board.round) || !Number.isInteger(board.honba) || Number(board.honba) < 0) return undefined;
  return JSON.stringify([board.seat, board.round, board.honba]);
}

/**
 * Preserve a bounded pair of *raw*, individually timestamped frame candidates.
 * No historical value is promoted to the current frame; unknown and missing
 * stay unknown. Equal OCR labels do not establish same hand or match. Even an
 * apparent boundary may be OCR error. This state is never playable game state.
 */
export function advanceSanmaFrameTimeline(previous: SanmaFrameTimeline | undefined,
  index: number, observation: Observation): SanmaFrameTimeline {
  if (!Number.isSafeInteger(index) || index < 0) throw new Error("frame index must be a nonnegative safe integer");
  const latest = { index, observation };
  const notes = ["unverified screenshot candidates; no state is confirmed", "no cross-frame value is filled into current observation"];
  let relationship: SanmaFrameTimeline["relationship"] = "first_frame";
  let prior: FrameEntry | undefined;
  if (previous) {
    prior = previous.latest;
    if (index <= prior.index) relationship = "invalid_frame_order";
    else if (observation.digest === prior.observation.digest) relationship = "duplicate_frame";
    else {
      const before = boardIdentity(prior.observation), after = boardIdentity(observation);
      if (!before || !after) relationship = "board_unknown";
      else relationship = before === after ? "unproven_equal_board" : "possible_hand_boundary";
    }
  }
  if (observation.report.digest !== observation.digest || Object.values(observation.north.positions ?? {}).some(
      position => position.frame_sha256 !== undefined && position.frame_sha256 !== observation.digest)) relationship = "inconsistent_frame";
  if (relationship === "inconsistent_frame") notes.push("observation components have inconsistent image digests");
  if (relationship === "unproven_equal_board") notes.push("equal OCR labels do not prove same match or hand");
  if (relationship === "possible_hand_boundary") notes.push("board labels differ; cross-frame hand and river continuity withheld");
  if (relationship === "board_unknown") notes.push("missing board evidence; continuity withheld");
  if (relationship === "invalid_frame_order" || relationship === "duplicate_frame") notes.push("temporal ordering cannot be established");
  const comparison: SanmaFrameTimeline["comparison"] = {
    hand: "unknown", rivers: "unknown", north: { own:"unknown", opposite:"unknown", left:"unknown" },
  };
  if (relationship === "unproven_equal_board" && prior) {
    const old = prior.observation, current = observation;
    const equality = (a: unknown, b: unknown): Comparison => JSON.stringify(a) === JSON.stringify(b) ? "same_candidates" : "different_candidates";
    if (old.report.hand.status === "candidate" && current.report.hand.status === "candidate"
        && old.report.hand.value.tiles.length && current.report.hand.value.tiles.length) {
      comparison.hand = equality(old.report.hand.value.tiles, current.report.hand.value.tiles);
    }
    if (old.report.publicTiles.status === "candidate" && current.report.publicTiles.status === "candidate") {
      const rivers = (item: Observation) => {
        if (item.report.publicTiles.status !== "candidate") return undefined;
        const publicTiles = item.report.publicTiles.value.observation;
        return { own:publicTiles.ownDiscards, opponents:publicTiles.opponentDiscards.map(o => ({seat:o.seat, tiles:o.discards})) };
      };
      const before = rivers(old), after = rivers(current);
      // Empty arrays are unobserved, not proof of an empty river.
      if (before?.own.length && after?.own.length && before.opponents.every(o => o.tiles.length)
          && after.opponents.every(o => o.tiles.length)) comparison.rivers = equality(before, after);
    }
    for (const position of ["own", "opposite", "left"] as const) {
      const before = old.north.positions?.[position], after = current.north.positions?.[position];
      if (!before || !after) continue;
      // A missing match may be occluded, so never compare it as an empty row.
      const points = (value: typeof before): string[] => Array.isArray(value.matches)
        ? value.matches.filter(m => m && typeof m === "object" && Number.isFinite(m.x) && Number.isFinite(m.y)).map(m => `${m.x},${m.y}`).sort()
        : value.candidate && typeof value.candidate === "object" && "x" in value.candidate && "y" in value.candidate
          ? [`${value.candidate.x},${value.candidate.y}`] : [];
      const a = points(before), b = points(after);
      if (a.length && b.length && equality(a,b) === "same_candidates") comparison.north[position] = "same_candidates";
    }
    notes.push("candidate comparisons are descriptive only; absent matches may be occluded");
  }
  if ((relationship === "invalid_frame_order" || relationship === "duplicate_frame" || relationship === "inconsistent_frame") && previous) {
    return { scope: "offline_untrusted_sanma_timeline", status: "unknown", operationAuthorized: false,
      latest: previous.latest, ...(previous.previous ? {previous:previous.previous} : {}), rejected:latest, relationship, notes, comparison };
  }
  return { scope: "offline_untrusted_sanma_timeline", status: "unknown", operationAuthorized: false,
    latest, ...(prior ? {previous:prior} : {}), relationship, notes, comparison };
}

/** Analyze ordered saved buffers using the same offline pipeline, without user-supplied board state. */
export async function observeSanmaFrameTimeline(input: Omit<Parameters<typeof observeSanmaFrameAutomatically>[0], "frame"> & {
  frames: readonly { index: number; frame: Buffer }[];
}): Promise<SanmaFrameTimeline | undefined> {
  let state: SanmaFrameTimeline | undefined;
  for (const entry of input.frames) {
    const observation = await observeSanmaFrameAutomatically({ ...input, frame:entry.frame });
    state = advanceSanmaFrameTimeline(state, entry.index, observation);
  }
  return state;
}
