import { readFile } from "node:fs/promises";
import { parseGameState } from "../game/state.js";
import { JevClient, type JevPromptProfile } from "../jev/client.js";
import { evaluateJevProfile } from "../jev/tuning.js";
import { decide } from "../agent/decision.js";
import { attachActualResult, readDecisionDataset, readDecisionLog } from "../logging/replay.js";
import { summarizeBenchmark } from "../logging/benchmark.js";
import { summarizeDecisionMetrics } from "../logging/metrics.js";
import { compareReplayPolicies, jevReplayPolicy, strategyReplayPolicies } from "../logging/policyComparison.js";
import type { CliArguments, CliCommand } from "./arguments.js";

async function replay(args: CliArguments): Promise<void> {
  const path = args.values[0];
  if (!path) throw new Error("Usage: npm run advisor -- replay.jsonl");
  const records = await readDecisionLog(path);
  const comparisons = await Promise.all(records.map(async (record) => {
    const current = await decide(parseGameState(record.state), { mode: "advisor" });
    return {
      id: record.id,
      timestamp: record.timestamp,
      previous: record.decision.selectedActionId,
      current: current.selectedActionId,
      changed: record.decision.selectedActionId !== current.selectedActionId,
    };
  }));
  console.log(JSON.stringify({ total: comparisons.length, changed: comparisons.filter((x) => x.changed).length, comparisons }, null, 2));
}

async function attachResult(args: CliArguments): Promise<void> {
  const path = args.values[0];
  const resultPath = args.values[1];
  if (!path || !resultPath) throw new Error("Usage: attach-result <decision.json> <actual-result.json>");
  const actualResult = JSON.parse(await readFile(resultPath, "utf8"));
  await attachActualResult(path, actualResult);
  console.log(JSON.stringify({ updated: path }, null, 2));
}

async function benchmark(args: CliArguments): Promise<void> {
  const path = args.values[0];
  if (!path) throw new Error("Usage: benchmark <replay-directory|decisions.jsonl|decision.json>");
  const records = await readDecisionDataset(path);
  console.log(JSON.stringify({ ...summarizeBenchmark(records), decisionMetrics: summarizeDecisionMetrics(records) }, null, 2));
}

async function policyCompare(args: CliArguments): Promise<void> {
  const path = args.values[0];
  if (!path) throw new Error("Usage: policy-compare <replay-directory|decisions.jsonl|decision.json> [--jev]");
  const records = await readDecisionDataset(path);
  const requestedProfiles = args.option("--profiles");
  const suite = strategyReplayPolicies();
  const policies = requestedProfiles
    ? requestedProfiles.split(",").map((name) => {
        const selected = suite.find((policy) => policy.name === name);
        if (!selected) throw new Error(`Unknown policy profile: ${name}`);
        return selected;
      })
    : suite;
  if (args.has("--jev")) {
    const apiKey = process.env.TYPESAFE_API_KEY ?? "";
    if (!apiKey) throw new Error("TYPESAFE_API_KEY is required with --jev");
    policies.push(jevReplayPolicy(new JevClient(apiKey)));
  }
  console.log(JSON.stringify(await compareReplayPolicies(records, policies), null, 2));
}

async function jevTune(args: CliArguments): Promise<void> {
  const path = args.values[0];
  if (!path) throw new Error("Usage: jev-tune <replay-directory|decisions.jsonl|decision.json> [--profiles=legacy-v1,balanced-v2] [--model=jev-1.13.0]");
  const apiKey = process.env.TYPESAFE_API_KEY ?? "";
  if (!apiKey) throw new Error("TYPESAFE_API_KEY is required for jev-tune");
  const profiles = (args.option("--profiles") ?? "legacy-v1,balanced-v2").split(",");
  if (profiles.some((profile) => profile !== "legacy-v1" && profile !== "balanced-v2")) throw new Error("Invalid Jev prompt profile");
  const model = args.option("--model") ?? process.env.JEV_MODEL ?? "jev-1.13.0";
  const endpoint = args.option("--endpoint") ?? "https://api.typesafe.ai/v1/systemone";
  const records = await readDecisionDataset(path);
  const results = [];
  for (const profile of profiles as JevPromptProfile[]) {
    results.push(await evaluateJevProfile(records, { apiKey, endpoint, model, profile }));
  }
  console.log(JSON.stringify({ model, records: records.length, results }, null, 2));
}

export const commands: Record<string, CliCommand> = {
  "replay": replay,
  "attach-result": attachResult,
  "benchmark": benchmark,
  "policy-compare": policyCompare,
  "jev-tune": jevTune,
};
