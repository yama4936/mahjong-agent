import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { inspectSanmaFrame } from "./sanmaFrameExperiment.js";
import type { ScreenLayout } from "./layout.js";
import type { ExperimentalTemplates } from "./sanmaButtonExperiment.js";
import type { PublicVitClassifier } from "./publicTileRecognizer.js";

const run = promisify(execFile);
/** Offline OCR plus image analysis from one immutable byte snapshot; never a live operation certificate. */
export async function observeSanmaFrameAutomatically(input: {
  frame: Buffer; layout: ScreenLayout; templates: string; buttonTemplates: ExperimentalTemplates;
  publicClassifier: PublicVitClassifier; buttonRowReferences?: { skip: Buffer; emptyRow: Buffer; ron?: Buffer };
}) {
  if (!Buffer.isBuffer(input.frame)) throw new Error("Frame bytes required");
  const frame = Buffer.from(input.frame);
  const digest = createHash("sha256").update(frame).digest("hex");
  const directory = await mkdtemp(path.join(tmpdir(), "jantama-sanma-observe-"));
  let board: { verified: false; reason?: string; candidate?: { seat?: string } };
  try {
    const file = path.join(directory, "frame.png");
    await writeFile(file, frame, { mode: 0o600, flag: "wx" });
    try {
      const result = await run(path.resolve(".runtime/python-auto-venv/bin/python"),
        [path.resolve("python/sanma_board_image.py"), file], { timeout: 30_000, maxBuffer: 2_000_000 });
      const data = JSON.parse(result.stdout) as typeof board;
      if (data.verified !== false) throw new Error("board OCR did not return an unverified candidate");
      if (createHash("sha256").update(await readFile(file)).digest("hex") !== digest) throw new Error("OCR frame changed");
      board = data;
    } catch (error) { board = { verified: false, reason: `board observation failed: ${error instanceof Error ? error.message : String(error)}` }; }
  } finally { await rm(directory, { recursive: true, force: true }); }
  const seat = board.candidate?.seat;
  const ownSeat = seat === "east" || seat === "south" || seat === "west" ? seat : undefined;
  const report = await inspectSanmaFrame({ frame, layout: input.layout, templates: input.templates,
    buttonTemplates: input.buttonTemplates, publicClassifier: input.publicClassifier,
    ...(ownSeat ? { ownSeat } : {}), ...(input.buttonRowReferences ? { buttonRowReferences: input.buttonRowReferences } : {}) });
  if (report.digest !== digest) throw new Error("snapshot digest mismatch");
  return { scope: "offline_untrusted_sanma_auto_observation" as const, digest, board,
    ownSeat: ownSeat ? { status: "candidate" as const, value: ownSeat, verified: false as const }
      : { status: "unknown" as const, reason: board.reason ?? "seat unavailable" },
    report, operationAuthorized: false as const };
}
