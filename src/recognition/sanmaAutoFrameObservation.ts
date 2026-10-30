import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { inspectSanmaFrame } from "./sanmaFrameExperiment.js";
import type { ScreenLayout } from "./layout.js";
import type { ExperimentalTemplates } from "./sanmaButtonExperiment.js";
import { mapPublicOpponentPositions } from "./publicSeatMapping.js";
import type { PublicVitClassifier } from "./publicTileRecognizer.js";

const run = promisify(execFile);
type NorthPosition = { verified: false; complete: false; frame_sha256?: string; [key: string]: unknown };
type NorthPositions = { own: NorthPosition; opposite: NorthPosition; left: NorthPosition };
type NorthResult = { status: "unknown"; verified: false; complete: false; reason?: string; positions?: NorthPositions };

/** Maps screen positions under an unverified seat candidate; never counts extracts. */
export function mapSanmaNorthCandidates(ownSeat: "east" | "south" | "west" | undefined, positions: NorthPositions | undefined) {
  if (!ownSeat || !positions) return undefined;
  return { [ownSeat]: positions.own,
    ...mapPublicOpponentPositions(ownSeat, { opposite: positions.opposite, left: positions.left }, "sanma") };
}
/** Offline OCR plus image analysis from one immutable byte snapshot; never a live operation certificate. */
export async function observeSanmaFrameAutomatically(input: {
  frame: Buffer; layout: ScreenLayout; templates: string; buttonTemplates: ExperimentalTemplates;
  publicClassifier: PublicVitClassifier; buttonRowReferences?: { skip: Buffer; emptyRow: Buffer; ron?: Buffer };
  boardObserver?: { observe(frame: Buffer): Promise<unknown> };
}) {
  if (!Buffer.isBuffer(input.frame)) throw new Error("Frame bytes required");
  const frame = Buffer.from(input.frame);
  const digest = createHash("sha256").update(frame).digest("hex");
  let board: { verified: false; reason?: string; candidate?: { seat?: string } };
  let north: NorthResult = { status: "unknown", verified: false, complete: false, reason: "north observations unavailable" };
  try {
    let data: { board: typeof board; north: NorthResult; frame_sha256?: string };
    if (input.boardObserver) {
      data = await input.boardObserver.observe(frame) as typeof data;
      if (data.frame_sha256 !== digest) throw new Error("OCR frame digest mismatch");
    } else {
      const directory = await mkdtemp(path.join(tmpdir(), "jantama-sanma-observe-"));
      try {
        const file = path.join(directory, "frame.png");
        await writeFile(file, frame, { mode: 0o600, flag: "wx" });
        const result = await run(path.resolve(".runtime/python-auto-venv/bin/python"),
          [path.resolve("python/sanma_board_image.py"), file, "--with-north"], { timeout: 30_000, maxBuffer: 2_000_000 });
        data = JSON.parse(result.stdout) as typeof data;
        if (createHash("sha256").update(await readFile(file)).digest("hex") !== digest) throw new Error("OCR frame changed");
      } finally { await rm(directory, { recursive: true, force: true }); }
    }
    if (data.board?.verified !== false) throw new Error("board OCR did not return an unverified candidate");
    board = data.board;
    if (data.north?.status !== "unknown" || data.north.verified !== false || data.north.complete !== false) {
      throw new Error("north observations lack unverified/incomplete flags");
    }
    for (const value of Object.values(data.north.positions ?? {})) {
      if (value.verified !== false || value.complete !== false || (value.frame_sha256 !== undefined && value.frame_sha256 !== digest)) {
        throw new Error("north observation frame or status mismatch");
      }
    }
    north = data.north;
  } catch (error) { board = { verified: false, reason: `board observation failed: ${error instanceof Error ? error.message : String(error)}` }; }
  const seat = board.candidate?.seat;
  const ownSeat = seat === "east" || seat === "south" || seat === "west" ? seat : undefined;
  const report = await inspectSanmaFrame({ frame, layout: input.layout, templates: input.templates,
    buttonTemplates: input.buttonTemplates, publicClassifier: input.publicClassifier,
    ...(ownSeat ? { ownSeat } : {}), ...(input.buttonRowReferences ? { buttonRowReferences: input.buttonRowReferences } : {}) });
  if (report.digest !== digest) throw new Error("snapshot digest mismatch");
  // The older diagnostic evaluates with an assumed empty visible-tile list.
  // Do not expose it in the automatic observation as if unknown tiles were zero.
  report.shape = {status: "unresolved", reason: "visible tile completeness unavailable"};
  const positions = north.positions;
  const bySeat = mapSanmaNorthCandidates(ownSeat, positions);
  const candidates = deriveSanmaActionCandidates(report, ownSeat !== undefined);
  if (!input.buttonRowReferences?.ron) candidates.missing.push("ron reference unavailable");
  return { scope: "offline_untrusted_sanma_auto_observation" as const, digest, board, north: { ...north, ...(bySeat ? { bySeat, mappingVerified: false as const } : {}) }, candidates,
    ownSeat: ownSeat ? { status: "candidate" as const, value: ownSeat, verified: false as const }
      : { status: "unknown" as const, reason: board.reason ?? "seat unavailable" },
    report, operationAuthorized: false as const };
}


type ObservedFrame = Awaited<ReturnType<typeof inspectSanmaFrame>>;
/** Read-only action hypotheses; these are not legal actions or priority decisions. */
export function deriveSanmaActionCandidates(report: ObservedFrame, hasSeatCandidate: boolean) {
  const missing = ["game rules and OCR seat unverified", "action row incomplete", "turn and riichi status unverified",
    "public tiles and extracted north counts incomplete", "physical action targets uncalibrated"];
  if (!hasSeatCandidate) missing.push("own seat unavailable");
  if (report.hand.status !== "candidate") missing.push("hand recognition unavailable");
  else if (!report.hand.value.safe) missing.push("hand labels below confidence threshold");
  if (report.buttonRow.status !== "candidate") {
    missing.push("button row unavailable");
    return { status: "unresolved" as const, candidates: [], missing, operationAuthorized: false as const };
  }
  if (report.buttonRow.value.slots.some(slot => slot.status === "unresolved")) missing.push("some button slots unresolved");
  if (!hasSeatCandidate) return { status: "unresolved" as const, candidates: [], missing, operationAuthorized: false as const };
  type Candidate = { action: "kita" | "riichi" | "tsumo" | "ron" | "pon" | "kan"; slot: number;
    handSupport: "not_checked" | "unknown" | "north_not_observed" | "north_candidate"; northIndexes?: number[] };
  const candidates = report.buttonRow.value.slots.flatMap<Candidate>(slot => {
    if (slot.status !== "candidate" || slot.action === "skip") return [];
    if (slot.action !== "kita") return [{action:slot.action, slot:slot.slot, handSupport:"not_checked" as const}];
    if (report.hand.status !== "candidate") return [{action:slot.action, slot:slot.slot, handSupport:"unknown" as const}];
    const northIndexes = report.hand.value.tiles.flatMap((tile, index) => tile === "N" ? [index] : []);
    if (!northIndexes.length) return [{action:slot.action, slot:slot.slot, handSupport:"north_not_observed" as const}];
    return [{action:slot.action, slot:slot.slot, handSupport:"north_candidate" as const, northIndexes}];
  });
  const conflicts = candidates.filter(candidate => candidate.handSupport === "north_not_observed");
  const supported = candidates.filter(candidate => candidate.handSupport !== "north_not_observed");
  if (conflicts.length) missing.push("kita button conflicts with recognized hand; neither result is verified");
  return { status: supported.length ? "hypotheses" as const : "unresolved" as const,
    candidates: supported, conflicts, missing, operationAuthorized: false as const };
}
