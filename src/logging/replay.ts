import { appendFile, mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { z } from "zod";
import type { GameState } from "../game/state.js";
import type { DecisionResult } from "../agent/decision.js";
import type { ActionExecutionReceipt, UiActionExecutionReceipt } from "../jantama/browser.js";

export interface TurnEvidence {
  recognition: {
    backend: "template" | "vit" | "hybrid";
    tiles: string[];
    confidence: number;
    ambiguityMargin: number;
    safe: boolean;
  };
  publicObservation?: {
    ownDiscards: string[];
    otherVisibleTiles: string[];
    acceptedTiles: number;
    detectedCandidates: number;
    complete: boolean;
    applied: boolean;
  };
  execution?: ActionExecutionReceipt | UiActionExecutionReceipt | { action: "riichi"; declaration: UiActionExecutionReceipt; discard: ActionExecutionReceipt };
  executionError?: string;
}

export interface ExecutionEvidence {
  status: "not_attempted" | "verified" | "failed";
  actionId: string;
  reason?: string;
  receipt?: TurnEvidence["execution"];
}

export interface OutcomeEvidence {
  observedAt: string;
  screenshot: string;
  screenState: "round_result" | "match_result";
  screenConfidence: number;
}

export interface DecisionRecord {
  schemaVersion: 1;
  id: string;
  timestamp: string;
  screenshot?: string;
  state: GameState;
  decision: DecisionResult;
  /** Present on all newly written records; optional only for legacy replay compatibility. */
  executionEvidence?: ExecutionEvidence;
  evidence?: TurnEvidence;
  actualResult?: ActualResult;
}

const outcomeEvidenceSchema = z.object({
  observedAt: z.iso.datetime({ offset: true }),
  screenshot: z.string().min(1),
  screenState: z.enum(["round_result", "match_result"]),
  screenConfidence: z.number().min(0).max(1),
});

const actualResultSchema = z.object({
  expertActionId: z.string().min(1).max(200).optional(),
  won: z.boolean().optional(),
  dealIn: z.boolean().optional(),
  tenpaiAtDraw: z.boolean().optional(),
  pointsDelta: z.number().int().optional(),
  finalRank: z.number().int().min(1).max(4).optional(),
  round: outcomeEvidenceSchema.optional(),
  match: outcomeEvidenceSchema.optional(),
  note: z.string().max(2000).optional(),
}).passthrough();

export type ActualResult = z.infer<typeof actualResultSchema>;

function executionEvidence(decision: DecisionResult, evidence?: TurnEvidence): ExecutionEvidence {
  if (evidence?.execution) {
    return { status: "verified", actionId: decision.selectedActionId, receipt: evidence.execution };
  }
  if (evidence?.executionError) {
    return { status: "failed", actionId: decision.selectedActionId, reason: evidence.executionError };
  }
  return {
    status: "not_attempted",
    actionId: decision.selectedActionId,
    reason: decision.executable ? "executor_did_not_supply_evidence" : "decision_not_executable",
  };
}

export async function appendDecisionLog(directory: string, state: GameState, decision: DecisionResult, screenshot?: string, evidence?: TurnEvidence): Promise<DecisionRecord> {
  await mkdir(directory, { recursive: true });
  const record: DecisionRecord = {
    schemaVersion: 1,
    id: randomUUID(),
    timestamp: new Date().toISOString(),
    ...(screenshot ? { screenshot } : {}),
    state,
    decision,
    executionEvidence: executionEvidence(decision, evidence),
    ...(evidence ? { evidence } : {}),
  };
  const line = `${JSON.stringify(record)}\n`;
  await appendFile(path.join(directory, "decisions.jsonl"), line, { encoding: "utf8", mode: 0o600 });
  await writeFile(path.join(directory, `${record.id}.json`), JSON.stringify(record, null, 2), { encoding: "utf8", mode: 0o600 });
  return record;
}

export async function readDecisionLog(file: string): Promise<DecisionRecord[]> {
  const content = await readFile(file, "utf8");
  if (file.endsWith(".jsonl")) return content.split("\n").filter(Boolean).map((line) => JSON.parse(line) as DecisionRecord);
  return [JSON.parse(content) as DecisionRecord];
}

export async function readDecisionDataset(input: string): Promise<DecisionRecord[]> {
  if (!(await stat(input)).isDirectory()) return readDecisionLog(input);
  const files = (await readdir(input))
    .filter((file) => file.endsWith(".json") && file !== "decisions.json")
    .sort();
  return Promise.all(files.map(async (file) => JSON.parse(await readFile(path.join(input, file), "utf8")) as DecisionRecord));
}

export async function attachActualResult(file: string, actualResult: Record<string, unknown>): Promise<void> {
  if (file.endsWith(".jsonl")) throw new Error("Attach results to the per-decision JSON file, not JSONL");
  const record = JSON.parse(await readFile(file, "utf8")) as DecisionRecord;
  record.actualResult = actualResultSchema.parse({ ...record.actualResult, ...actualResult });
  await writeFile(file, JSON.stringify(record, null, 2), { encoding: "utf8", mode: 0o600 });
}
