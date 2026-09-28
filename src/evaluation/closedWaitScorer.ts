import { spawn } from "node:child_process";
import path from "node:path";
import { z } from "zod";
import type { GameState } from "../game/state.js";

const reportSchema = z.object({
  library: z.literal("mahjong==2.0.0"), discard: z.string(),
  scope: z.literal("closed_hand_scoring_not_policy_ev"),
  assumptions: z.record(z.string(), z.boolean()),
  rows: z.array(z.object({
    wait: z.string(), riichi: z.boolean(), tsumo: z.boolean(), error: z.string().nullable(),
    han: z.number().nullable(), fu: z.number().nullable(), yaku: z.array(z.string()),
    cost: z.record(z.string(), z.union([z.number(), z.string()])).nullable(),
    scoreScenarios: z.array(z.object({
      payer: z.string().nullable(), scores: z.record(z.string(), z.number()),
      rankRange: z.tuple([z.number(), z.number()]),
      scope: z.literal("immediate_scores_not_final_match_rank"), dealer_win: z.boolean(),
    })),
  })),
});
export type ClosedWaitReport = z.infer<typeof reportSchema>;

/** Bounded offline scorer bridge. It does not change the selected action. */
export function scoreClosedWaits(state: GameState, discard: string, waits: readonly string[],
  options: { timeoutMs?: number; python?: string; signal?: AbortSignal } = {}): Promise<ClosedWaitReport> {
  const timeoutMs = options.timeoutMs ?? 750;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error("Invalid scoring timeout");
  if (!waits.length || new Set(waits).size !== waits.length) throw new Error("Unique scoring waits required");
  if (options.signal?.aborted) return Promise.reject(new Error("Scoring aborted"));
  const python = options.python ?? path.resolve(".runtime/scoring-venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  return new Promise((resolve, reject) => {
    const child = spawn(python, [path.resolve("python/score_closed_waits.py"), "-", "--discard", discard,
      ...waits.flatMap((wait) => ["--wait", wait])], { stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
    let output = "";
    let settled = false;
    const finish = (error?: Error, report?: ClosedWaitReport) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", abort);
      if (error) { child.kill(); reject(error); }
      else resolve(report!);
    };
    const abort = () => finish(new Error("Scoring aborted"));
    const timer = setTimeout(() => finish(new Error("Scoring deadline exceeded")), timeoutMs);
    options.signal?.addEventListener("abort", abort, { once: true });
    child.on("error", (error) => finish(error));
    child.stdin.on("error", (error) => finish(error));
    child.stdout.on("data", (chunk) => {
      output += String(chunk);
      if (output.length > 1_000_000) finish(new Error("Scoring response too large"));
    });
    // Consume stderr without retaining hand information or arbitrary subprocess output.
    child.stderr.resume();
    child.on("close", (code) => {
      if (settled) return;
      if (code !== 0) return finish(new Error(`Scoring exited with code ${code}`));
      try {
        const report = reportSchema.parse(JSON.parse(output));
        const combinations = new Set(report.rows.map((row) => `${row.wait}:${row.riichi}:${row.tsumo}`));
        if (report.discard !== discard || report.rows.length !== waits.length * 4
          || combinations.size !== waits.length * 4
          || report.rows.some((row) => !waits.includes(row.wait))) throw new Error("Scoring response does not match request");
        finish(undefined, report);
      } catch (error) { finish(error instanceof Error ? error : new Error("Invalid scoring response")); }
    });
    child.stdin.end(JSON.stringify({ state }));
  });
}
