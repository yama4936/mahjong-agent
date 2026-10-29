import { mkdir, readFile, writeFile } from "node:fs/promises";
import { parsePublicGameState } from "../game/state.js";
import { JevClient } from "../jev/client.js";
import { layoutSchema } from "../recognition/layout.js";
import { layoutFromHandProposal, proposeHandLayout, proposeLiveHandLayout } from "../recognition/handLayoutProposal.js";
import { connectJantama } from "../jantama/browser.js";
import { processTurn, runAgentLoop } from "../agent/controller.js";
import { modelRecognizer } from "./modelRecognizer.js";
import type { CliArguments, CliCommand } from "./arguments.js";

async function watchHandLayout(args: CliArguments): Promise<void> {
  const cdp = args.option("--cdp") ?? "http://127.0.0.1:9222";
  const outputDirectory = args.option("--output") ?? "artifacts/calibration";
  const pollIntervalMs = Number(args.option("--poll") ?? 100);
  if (!Number.isFinite(pollIntervalMs) || pollIntervalMs < 100) throw new Error("--poll must be at least 100ms");
  const session = await connectJantama(cdp);
  let aborted = false;
  process.once("SIGINT", () => { aborted = true; });
  let frames = 0;
  try {
    while (!aborted) {
      frames += 1;
      const image = await session.page.screenshot({ animations: "disabled" });
      try {
        const proposal = await proposeHandLayout(image);
        const stamp = new Date().toISOString().replaceAll(":", "-");
        await mkdir(outputDirectory, { recursive: true });
        const screenshotPath = `${outputDirectory}/${stamp}.png`;
        const proposalPath = `${outputDirectory}/${stamp}.hand-layout.json`;
        await writeFile(screenshotPath, image, { mode: 0o600 });
        await writeFile(proposalPath, JSON.stringify(proposal, null, 2), { encoding: "utf8", mode: 0o600 });
        console.log(JSON.stringify({ frames, screenshotPath, proposalPath, proposal }, null, 2));
        return;
      } catch (error) {
        if (frames === 1 || frames % 30 === 0) console.error(`[waiting] frame ${frames}: ${error instanceof Error ? error.message : String(error)}`);
      }
      await session.page.waitForTimeout(pollIntervalMs);
    }
    console.log(JSON.stringify({ frames, aborted: true }));
  } finally {
    await session.browser.close();
  }
}

async function liveAdvisor(args: CliArguments): Promise<void> {
  const publicStatePath = args.values.find((argument) => !argument.startsWith("--"));
  const cdp = args.option("--cdp") ?? "http://127.0.0.1:9222";
  const outputDirectory = args.option("--output") ?? "artifacts/live";
  const templateDirectory = args.option("--templates") ?? "templates/live-verified";
  const recognizerValue = args.option("--recognizer") ?? "hybrid";
  const pollIntervalMs = Number(args.option("--poll") ?? 100);
  const maxTurns = Number(args.option("--max-turns") ?? 1);
  if (!Number.isFinite(pollIntervalMs) || pollIntervalMs < 100) throw new Error("--poll must be at least 100ms");
  if (!Number.isInteger(maxTurns) || maxTurns < 1) throw new Error("--max-turns must be a positive integer");

  const rawPublicState = publicStatePath
    ? JSON.parse(await readFile(publicStatePath, "utf8"))
    : {};
  const publicState = parsePublicGameState({ ...rawPublicState, phase: "self_turn" });
  const session = await connectJantama(cdp);
  const recognizer = modelRecognizer(recognizerValue);
  let frames = 0;
  try {
    let proposal: Awaited<ReturnType<typeof proposeHandLayout>> | undefined;
    let calibrationImage: Buffer | undefined;
    while (!proposal) {
      frames += 1;
      calibrationImage = await session.page.screenshot({ animations: "disabled" });
      try {
        proposal = await proposeLiveHandLayout(calibrationImage);
      } catch (error) {
        if (frames === 1 || frames % 30 === 0) {
          console.error(`[calibrating] frame ${frames}: ${error instanceof Error ? error.message : String(error)}`);
        }
        await session.page.waitForTimeout(pollIntervalMs);
      }
    }

    const layout = layoutFromHandProposal(proposal);
    const stamp = new Date().toISOString().replaceAll(":", "-");
    await mkdir(outputDirectory, { recursive: true });
    const screenshotPath = `${outputDirectory}/${stamp}.calibration.png`;
    const layoutPath = `${outputDirectory}/${stamp}.layout.json`;
    await writeFile(screenshotPath, calibrationImage!, { mode: 0o600 });
    await writeFile(layoutPath, JSON.stringify(layout, null, 2), { encoding: "utf8", mode: 0o600 });
    console.error(`[calibrated] frame ${frames}: ${layoutPath}`);

    const apiKey = process.env.TYPESAFE_API_KEY;
    const result = await runAgentLoop({
      page: session.page,
      mode: "advisor",
      layout,
      templateDirectory,
      artifactDirectory: "artifacts",
      publicState,
      ...(recognizer ? { tileRecognizer: recognizer } : {}),
      ...(apiKey ? { jev: new JevClient(apiKey) } : {}),
    }, {
      pollIntervalMs,
      maxTurns,
      onStatus: (status) => console.error(`[${status.kind}] ${status.message}`),
    });
    console.log(JSON.stringify({ ...result, calibrationFrames: frames, screenshotPath, layoutPath }, null, 2));
  } finally {
    await recognizer?.close();
    await session.browser.close();
  }
}

async function turn(args: CliArguments): Promise<void> {
  const path = args.values[0];
  const command = args.command;
  const publicStatePath = path;
  const layoutPath = args.values[1];
  const templates = args.values[2];
  if (!publicStatePath || !layoutPath || !templates) throw new Error(`Usage: ${command} <public-state.json> <layout.json> <templates> [--cdp=URL] [--mode=observer|advisor|auto]`);
  const cdp = args.option("--cdp") ?? "http://127.0.0.1:9222";
  const modeValue = args.option("--mode") ?? "advisor";
  if (!(["observer", "advisor", "auto"] as string[]).includes(modeValue)) throw new Error(`Invalid mode: ${modeValue}`);
  const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
  const rawState = JSON.parse(await readFile(publicStatePath, "utf8"));
  delete rawState.hand;
  delete rawState.draw;
  delete rawState.recognitionConfidence;
  delete rawState.recognition_confidence;
  const publicState = parsePublicGameState(rawState);
  const session = await connectJantama(cdp);
  const recognizerValue = args.option("--recognizer") ?? "hybrid";
  const recognizer = modelRecognizer(recognizerValue);
  try {
    const apiKey = process.env.TYPESAFE_API_KEY;
    const context = {
      page: session.page,
      mode: modeValue as "observer" | "advisor" | "auto",
      layout,
      templateDirectory: templates,
      ...(args.option("--action-templates")
        ? { actionTemplateDirectory: args.option("--action-templates")! }
        : {}),
      artifactDirectory: "artifacts",
      publicState,
      ...(apiKey ? { jev: new JevClient(apiKey) } : {}),
      useUntrustedPublicObservation: args.has("--use-public-observation"),
      ...(recognizer ? { tileRecognizer: recognizer } : {}),
    };
    if (command === "watch") {
      const pollIntervalMs = Number(args.option("--poll") ?? 100);
      const maxTurnsArgument = args.option("--max-turns");
      const abort = new AbortController();
      process.once("SIGINT", () => abort.abort());
      const result = await runAgentLoop(context, {
        pollIntervalMs,
        ...(maxTurnsArgument ? { maxTurns: Number(maxTurnsArgument) } : {}),
        signal: abort.signal,
        onStatus: (status) => console.error(`[${status.kind}] ${status.message}`),
      });
      console.log(JSON.stringify(result, null, 2));
      return;
    }
    const result = await processTurn(context);
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await recognizer?.close();
    await session.browser.close();
  }
}

export const commands: Record<string, CliCommand> = {
  "watch-hand-layout": watchHandLayout,
  "live-advisor": liveAdvisor,
  "turn": turn,
  "watch": turn,
};
