import { readFile } from "node:fs/promises";
import { parseGameState } from "../game/state.js";
import { deterministicAdvice } from "../evaluation/advisor.js";
import { JevClient } from "../jev/client.js";
import { decide } from "../agent/decision.js";
import { appendDecisionLog } from "../logging/replay.js";
import type { CliArguments, CliCommand } from "./arguments.js";

async function advise(args: CliArguments): Promise<void> {
  const path = args.values[0];
  if (!path) throw new Error("Usage: npm run advisor -- state.json [--jev]");
  const state = parseGameState(JSON.parse(await readFile(path, "utf8")));
  const result = deterministicAdvice(state);
  if (args.has("--jev")) {
    const decision = await decide(state, { mode: "advisor", jev: new JevClient(process.env.TYPESAFE_API_KEY ?? "") });
    if (args.has("--log")) await appendDecisionLog("artifacts/replays", state, decision);
    console.log(JSON.stringify(decision, null, 2));
    return;
  }
  console.log(JSON.stringify(result, null, 2));
}

async function jevSmoke(args: CliArguments): Promise<void> {
  const state = parseGameState({ hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"], draw: "6p" });
  const result = deterministicAdvice(state);
  const decision = await new JevClient(process.env.TYPESAFE_API_KEY ?? "").chooseDiscard(state, result.candidates);
  console.log(JSON.stringify({ actionId: decision.actionId, confidence: decision.confidence, model: decision.model, usage: decision.usage }, null, 2));
}

export const commands: Record<string, CliCommand> = {
  "advise": advise,
  "jev-smoke": jevSmoke,
};
