import { mkdir, readFile, writeFile } from "node:fs/promises";
import { parseGameState, parsePublicGameState } from "./game/state.js";
import { deterministicAdvice } from "./evaluation/advisor.js";
import { JevClient, type JevPromptProfile } from "./jev/client.js";
import { evaluateJevProfile } from "./jev/tuning.js";
import { layoutSchema } from "./recognition/layout.js";
import { measureSlotPresence, recognizeHand, recognizeTileSlots } from "./recognition/templateMatcher.js";
import { detectConfiguredPublicRegions } from "./recognition/regionDetector.js";
import { recognizeConfiguredPublicTiles, recognizeConfiguredPublicTilesWithVit, toPublicTileObservation } from "./recognition/publicTileRecognizer.js";
import { layoutFromHandProposal, proposeHandLayout } from "./recognition/handLayoutProposal.js";
import { VitTileRecognizer } from "./recognition/vitRecognizer.js";
import { HybridTileRecognizer } from "./recognition/hybridTileRecognizer.js";
import { decide } from "./agent/decision.js";
import { appendDecisionLog, attachActualResult, readDecisionDataset, readDecisionLog } from "./logging/replay.js";
import { summarizeBenchmark } from "./logging/benchmark.js";
import { compareReplayPolicies, deterministicReplayPolicy, jevReplayPolicy } from "./logging/policyComparison.js";
import { collectHandTemplates } from "./recognition/templateCollector.js";
import { AUTO_MINIMUM_HOLDOUTS, fingerprintTemplateDirectory, validateTemplateDirectory } from "./recognition/templateValidator.js";
import { connectJantama } from "./jantama/browser.js";
import { assertTemplateSetMatchesCalibration, processTurn, runAgentLoop } from "./agent/controller.js";
import { availableUiActions, recognizeActionButtons } from "./recognition/actionButtonRecognizer.js";
import { recognizeCenterBoard } from "./recognition/centerBoardRecognizer.js";

type ModelRecognizer = VitTileRecognizer | HybridTileRecognizer;

function modelRecognizer(value: string): ModelRecognizer | undefined {
  if (value === "template") return undefined;
  if (value === "vit") return new VitTileRecognizer();
  if (value === "hybrid") return new HybridTileRecognizer();
  throw new Error(`Invalid recognizer: ${value}; expected template, hybrid, or vit`);
}

async function main(): Promise<void> {
  const [command, path] = process.argv.slice(2);
  if (command === "advise") {
    if (!path) throw new Error("Usage: npm run advisor -- state.json [--jev]");
    const state = parseGameState(JSON.parse(await readFile(path, "utf8")));
    const result = deterministicAdvice(state);
    if (process.argv.includes("--jev")) {
      const decision = await decide(state, { mode: "advisor", jev: new JevClient(process.env.TYPESAFE_API_KEY ?? "") });
      if (process.argv.includes("--log")) await appendDecisionLog("artifacts/replays", state, decision);
      console.log(JSON.stringify(decision, null, 2));
      return;
    }
    console.log(JSON.stringify(result, null, 2));
    return;
  }
  if (command === "jev-smoke") {
    const state = parseGameState({ hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"], draw: "6p" });
    const result = deterministicAdvice(state);
    const decision = await new JevClient(process.env.TYPESAFE_API_KEY ?? "").chooseDiscard(state, result.candidates);
    console.log(JSON.stringify({ actionId: decision.actionId, confidence: decision.confidence, model: decision.model, usage: decision.usage }, null, 2));
    return;
  }
  if (command === "recognize") {
    const screenshot = path;
    const layoutPath = process.argv[4];
    const templates = process.argv[5];
    if (!screenshot || !layoutPath || !templates) throw new Error("Usage: npm run recognize -- screenshot.png layout.json templates/");
    const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
    console.log(JSON.stringify(process.argv.includes("--concealed-only")
      ? await recognizeTileSlots(screenshot, layout.handSlots, layout, templates)
      : await recognizeHand(screenshot, layout, templates), null, 2));
    return;
  }
  if (command === "evaluate-frame") {
    const screenshot = path;
    const layoutPath = process.argv[4];
    const templates = process.argv[5];
    const stateArgument = process.argv.find((argument) => argument.startsWith("--state="))?.slice(8);
    const modeArgument = process.argv.find((argument) => argument.startsWith("--mode="))?.slice(7) ?? "advisor";
    const actionTemplatesArgument = process.argv.find((argument) => argument.startsWith("--action-templates="))?.slice(19);
    if (!screenshot || !layoutPath || !templates || !stateArgument) {
      throw new Error("Usage: evaluate-frame <screenshot.png> <layout.json> <templates> --state=public-state.json [--mode=advisor|auto]");
    }
    if (modeArgument !== "advisor" && modeArgument !== "auto") throw new Error("evaluate-frame mode must be advisor or auto");
    const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
    const rawPublicState = JSON.parse(await readFile(stateArgument, "utf8"));
    delete rawPublicState.hand;
    delete rawPublicState.draw;
    delete rawPublicState.recognitionConfidence;
    delete rawPublicState.recognition_confidence;
    const publicState = parsePublicGameState(rawPublicState);
    const recognition = publicState.phase === "reaction"
      ? await recognizeTileSlots(screenshot, layout.handSlots, layout, templates)
      : await recognizeHand(screenshot, layout, templates);
    const expectedTiles = publicState.phase === "reaction" ? 13 : 14;
    if (!recognition.safe || recognition.tiles.length !== expectedTiles) {
      console.log(JSON.stringify({
        schemaVersion: 1,
        status: "not_ready",
        recognition: {
          tiles: recognition.tiles,
          confidence: recognition.confidence,
          ambiguityMargin: recognition.ambiguityMargin,
          safe: recognition.safe,
          turnReady: recognition.tiles.length === expectedTiles,
        },
      }));
      return;
    }
    const actionMatches = actionTemplatesArgument
      ? await recognizeActionButtons(screenshot, layout, actionTemplatesArgument)
      : [];
    const state = parseGameState({
      ...publicState,
      hand: recognition.tiles.slice(0, 13),
      ...(publicState.phase === "self_turn" ? { draw: recognition.tiles[13] } : {}),
      availableUiActions: actionMatches.length ? availableUiActions(actionMatches) : publicState.availableUiActions,
      recognitionConfidence: recognition.confidence,
    });
    const apiKey = process.env.TYPESAFE_API_KEY;
    if (modeArgument === "auto" && !apiKey) throw new Error("TYPESAFE_API_KEY is required in Auto mode");
    if (modeArgument === "auto") {
      if (!layout.autoOperation) throw new Error("Auto operation is not enabled by a passing template calibration");
      await assertTemplateSetMatchesCalibration(layout, templates);
    }
    const decision = await decide(state, {
      mode: modeArgument,
      ...(apiKey ? { jev: new JevClient(apiKey) } : {}),
    });
    const clickIndex = decision.selectedAction.action === "discard" || decision.selectedAction.action === "riichi"
      ? [...state.hand, ...(state.draw ? [state.draw] : [])].map(String).lastIndexOf(decision.selectedAction.tile)
      : undefined;
    const actionButtonName = decision.selectedAction.action === "minkan" || decision.selectedAction.action === "ankan" || decision.selectedAction.action === "kakan"
      ? "kan"
      : decision.selectedAction.action;
    const actionButton = actionMatches.find((match) => match.action === actionButtonName && match.present);
    const actionTemplateSetFingerprint = actionButton && actionTemplatesArgument
      ? await fingerprintTemplateDirectory(actionTemplatesArgument)
      : undefined;
    console.log(JSON.stringify({
      schemaVersion: 1,
      status: "decision",
      state,
      recognition: {
        backend: "template",
        tiles: recognition.tiles,
        confidence: recognition.confidence,
        ambiguityMargin: recognition.ambiguityMargin,
        safe: recognition.safe,
      },
      decision,
      ...(clickIndex !== undefined ? { clickIndex } : {}),
      ...(actionButton ? { actionButton: { ...actionButton, templateSetFingerprint: actionTemplateSetFingerprint } } : {}),
    }));
    return;
  }
  if (command === "verify-discard-frame") {
    const screenshot = path;
    const layoutPath = process.argv[4];
    const templates = process.argv[5];
    const beforeArgument = process.argv.find((argument) => argument.startsWith("--before="))?.slice(9);
    const clickIndex = Number(process.argv.find((argument) => argument.startsWith("--click-index="))?.slice(14));
    if (!screenshot || !layoutPath || !templates || !beforeArgument || !Number.isInteger(clickIndex)) {
      throw new Error("Usage: verify-discard-frame <screenshot.png> <layout.json> <templates> --before=t1,...,t14 --click-index=N");
    }
    const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
    const before = beforeArgument.split(",");
    if (before.length !== 14 || clickIndex < 0 || clickIndex >= before.length) throw new Error("Invalid pre-discard hand or click index");
    const expected = before.filter((_, index) => index !== clickIndex).sort();
    const recognition = await recognizeTileSlots(screenshot, layout.handSlots, layout, templates);
    const actual = recognition.tiles.map(String).sort();
    const drawPresence = layout.drawSlot ? (await measureSlotPresence(screenshot, [layout.drawSlot]))[0]! : 0;
    const drawSlotEmpty = drawPresence < layout.minimumTilePresence;
    const verified = recognition.safe && drawSlotEmpty && JSON.stringify(actual) === JSON.stringify(expected);
    console.log(JSON.stringify({ schemaVersion: 1, verified, expected, actual, drawPresence, drawSlotEmpty, recognition }));
    return;
  }
  if (command === "detect-regions") {
    const screenshot = path;
    const layoutPath = process.argv[4];
    if (!screenshot || !layoutPath) throw new Error("Usage: detect-regions <screenshot.png> <layout.json>");
    const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
    console.log(JSON.stringify(await detectConfiguredPublicRegions(screenshot, layout), null, 2));
    return;
  }
  if (command === "recognize-regions") {
    const screenshot = path;
    const layoutPath = process.argv[4];
    const templates = process.argv[5];
    if (!screenshot || !layoutPath || !templates) throw new Error("Usage: recognize-regions <screenshot.png> <layout.json> <templates>");
    const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
    console.log(JSON.stringify(await recognizeConfiguredPublicTiles(screenshot, layout, templates), null, 2));
    return;
  }
  if (command === "recognize-center") {
    const screenshot = path;
    const layoutPath = process.argv[4];
    const manifest = process.argv[5];
    if (!screenshot || !layoutPath || !manifest) throw new Error("Usage: recognize-center <screenshot.png> <layout.json> <reference-manifest.json>");
    const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
    console.log(JSON.stringify(await recognizeCenterBoard(screenshot, layout, manifest), null, 2));
    return;
  }
  if (command === "recognize-actions") {
    const screenshot = path;
    const layoutPath = process.argv[4];
    const templates = process.argv[5];
    const minimumConfidence = Number(process.argv.find((argument) => argument.startsWith("--minimum-confidence="))?.slice(21) ?? 0.98);
    if (!screenshot || !layoutPath || !templates) throw new Error("Usage: recognize-actions <screenshot.png> <layout.json> <action-templates> [--minimum-confidence=0.98]");
    if (!Number.isFinite(minimumConfidence) || minimumConfidence < 0 || minimumConfidence > 1) throw new Error("Invalid action confidence threshold");
    const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
    const matches = await recognizeActionButtons(screenshot, layout, templates, minimumConfidence);
    console.log(JSON.stringify({ availableUiActions: availableUiActions(matches), matches }, null, 2));
    return;
  }
  if (command === "propose-hand-layout") {
    if (!path) throw new Error("Usage: propose-hand-layout <screenshot.png>");
    console.log(JSON.stringify(await proposeHandLayout(path), null, 2));
    return;
  }
  if (command === "analyze-screenshot") {
    const screenshot = path;
    if (!screenshot || screenshot.startsWith("--")) throw new Error("Usage: analyze-screenshot <screenshot.png> [--state=public-state.json] [--jev]");
    const statePath = process.argv.find((argument) => argument.startsWith("--state="))?.slice(8);
    const rawPublicState = statePath ? JSON.parse(await readFile(statePath, "utf8")) : {};
    delete rawPublicState.hand;
    delete rawPublicState.draw;
    delete rawPublicState.recognitionConfidence;
    delete rawPublicState.recognition_confidence;
    const publicState = parsePublicGameState({ ...rawPublicState, phase: "self_turn" });
    const proposal = await proposeHandLayout(screenshot);
    const layout = layoutFromHandProposal(proposal);
    const recognizerValue = process.argv.find((argument) => argument.startsWith("--recognizer="))?.slice(13) ?? "hybrid";
    const recognizer = modelRecognizer(recognizerValue);
    if (!recognizer) throw new Error("analyze-screenshot requires --recognizer=hybrid or --recognizer=vit");
    try {
      const recognition = await recognizer.recognizeHand(screenshot, layout);
      if (!recognition.turnReady || recognition.tiles.length !== 14) {
        throw new Error(`Screenshot does not contain a complete self-turn hand (recognized ${recognition.tiles.length} tiles)`);
      }
      const publicRecognition = await recognizeConfiguredPublicTilesWithVit(screenshot, layout, recognizer);
      const publicObservation = toPublicTileObservation(publicRecognition);
      const usePublicObservation = process.argv.includes("--use-public-observation");
      let publicObservationApplied = usePublicObservation;
      let state;
      try {
        state = parseGameState({
          ...publicState,
          ...(usePublicObservation && publicState.doraIndicators.length === 0 ? { doraIndicators: publicObservation.doraIndicators } : {}),
          ...(usePublicObservation && publicState.ownDiscards.length === 0 ? { ownDiscards: publicObservation.ownDiscards } : {}),
          ...(usePublicObservation && publicState.visibleTiles.length === 0 && !publicState.opponents.some((opponent) => opponent.discards.length > 0)
            ? { visibleTiles: publicObservation.otherVisibleTiles }
            : {}),
          hand: recognition.tiles.slice(0, 13),
          draw: recognition.tiles[13],
          recognitionConfidence: recognition.confidence,
        });
      } catch {
        publicObservationApplied = false;
        state = parseGameState({
          ...publicState,
          hand: recognition.tiles.slice(0, 13),
          draw: recognition.tiles[13],
          recognitionConfidence: recognition.confidence,
        });
      }
      const apiKey = process.argv.includes("--jev") ? process.env.TYPESAFE_API_KEY : undefined;
      if (process.argv.includes("--jev") && !apiKey) throw new Error("TYPESAFE_API_KEY is required with --jev");
      const decision = await decide(state, { mode: "advisor", ...(apiKey ? { jev: new JevClient(apiKey) } : {}) });
      if (process.argv.includes("--compact")) {
        console.log(JSON.stringify({ recommended_action: decision.recommendedAction, tile: decision.tile }, null, 2));
        return;
      }
      console.log(JSON.stringify({
        recommended_action: decision.recommendedAction,
        tile: decision.tile,
        confidence: decision.confidence,
        source: decision.source,
        recognition: {
          backend: recognizer.backend,
          tiles: recognition.tiles,
          confidence: recognition.confidence,
          ambiguityMargin: recognition.ambiguityMargin,
          safe: recognition.safe,
          redFiveClassification: recognition.redFiveClassification,
        },
        layout: { confidence: proposal.confidence, evidence: proposal.evidence },
        publicObservation: { ...publicObservation, applied: publicObservationApplied },
        candidates: decision.candidates,
        safety: decision.safety,
      }, null, 2));
    } finally {
      await recognizer.close();
    }
    return;
  }
  if (command === "watch-hand-layout") {
    const cdp = process.argv.find((arg) => arg.startsWith("--cdp="))?.slice(6) ?? "http://127.0.0.1:9222";
    const outputDirectory = process.argv.find((arg) => arg.startsWith("--output="))?.slice(9) ?? "artifacts/calibration";
    const pollIntervalMs = Number(process.argv.find((arg) => arg.startsWith("--poll="))?.slice(7) ?? 1000);
    if (!Number.isFinite(pollIntervalMs) || pollIntervalMs < 250) throw new Error("--poll must be at least 250ms");
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
    return;
  }
  if (command === "live-advisor") {
    const publicStatePath = process.argv.slice(3).find((argument) => !argument.startsWith("--"));
    const cdp = process.argv.find((arg) => arg.startsWith("--cdp="))?.slice(6) ?? "http://127.0.0.1:9222";
    const outputDirectory = process.argv.find((arg) => arg.startsWith("--output="))?.slice(9) ?? "artifacts/live";
    const templateDirectory = process.argv.find((arg) => arg.startsWith("--templates="))?.slice(12) ?? "templates/live-verified";
    const recognizerValue = process.argv.find((arg) => arg.startsWith("--recognizer="))?.slice(13) ?? "hybrid";
    const pollIntervalMs = Number(process.argv.find((arg) => arg.startsWith("--poll="))?.slice(7) ?? 750);
    const maxTurns = Number(process.argv.find((arg) => arg.startsWith("--max-turns="))?.slice(12) ?? 1);
    if (!Number.isFinite(pollIntervalMs) || pollIntervalMs < 250) throw new Error("--poll must be at least 250ms");
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
          proposal = await proposeHandLayout(calibrationImage);
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
    return;
  }
  if (command === "replay") {
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
    return;
  }
  if (command === "attach-result") {
    const resultPath = process.argv[4];
    if (!path || !resultPath) throw new Error("Usage: attach-result <decision.json> <actual-result.json>");
    const actualResult = JSON.parse(await readFile(resultPath, "utf8"));
    await attachActualResult(path, actualResult);
    console.log(JSON.stringify({ updated: path }, null, 2));
    return;
  }
  if (command === "benchmark") {
    if (!path) throw new Error("Usage: benchmark <replay-directory|decisions.jsonl|decision.json>");
    const records = await readDecisionDataset(path);
    console.log(JSON.stringify(summarizeBenchmark(records), null, 2));
    return;
  }
  if (command === "policy-compare") {
    if (!path) throw new Error("Usage: policy-compare <replay-directory|decisions.jsonl|decision.json> [--jev]");
    const records = await readDecisionDataset(path);
    const policies = [deterministicReplayPolicy()];
    if (process.argv.includes("--jev")) {
      const apiKey = process.env.TYPESAFE_API_KEY ?? "";
      if (!apiKey) throw new Error("TYPESAFE_API_KEY is required with --jev");
      policies.push(jevReplayPolicy(new JevClient(apiKey)));
    }
    console.log(JSON.stringify(await compareReplayPolicies(records, policies), null, 2));
    return;
  }
  if (command === "jev-tune") {
    if (!path) throw new Error("Usage: jev-tune <replay-directory|decisions.jsonl|decision.json> [--profiles=legacy-v1,balanced-v2] [--model=jev-1.13.0]");
    const apiKey = process.env.TYPESAFE_API_KEY ?? "";
    if (!apiKey) throw new Error("TYPESAFE_API_KEY is required for jev-tune");
    const profiles = (process.argv.find((argument) => argument.startsWith("--profiles="))?.slice(11) ?? "legacy-v1,balanced-v2").split(",");
    if (profiles.some((profile) => profile !== "legacy-v1" && profile !== "balanced-v2")) throw new Error("Invalid Jev prompt profile");
    const model = process.argv.find((argument) => argument.startsWith("--model="))?.slice(8) ?? process.env.JEV_MODEL ?? "jev-1.13.0";
    const endpoint = process.argv.find((argument) => argument.startsWith("--endpoint="))?.slice(11) ?? "https://api.typesafe.ai/v1/systemone";
    const records = await readDecisionDataset(path);
    const results = [];
    for (const profile of profiles as JevPromptProfile[]) {
      results.push(await evaluateJevProfile(records, { apiKey, endpoint, model, profile }));
    }
    console.log(JSON.stringify({ model, records: records.length, results }, null, 2));
    return;
  }
  if (command === "collect-templates") {
    const screenshot = path;
    const layoutPath = process.argv[4];
    const labels = process.argv[5]?.split(",");
    const output = process.argv.slice(6).find((argument) => !argument.startsWith("--")) ?? "templates";
    const splitValue = process.argv.find((argument) => argument.startsWith("--split="))?.slice(8) ?? "train";
    if (!screenshot || !layoutPath || !labels) throw new Error("Usage: collect-templates <screenshot> <layout> <comma-separated tiles> [output] [--split=train|holdout]");
    if (splitValue !== "train" && splitValue !== "holdout") throw new Error(`Invalid template split: ${splitValue}`);
    const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
    console.log(JSON.stringify(await collectHandTemplates(screenshot, layout, labels, output, splitValue), null, 2));
    return;
  }
  if (command === "validate-templates") {
    if (!path) throw new Error("Usage: validate-templates <templates> [--holdout=pattern] [--max-per-class=N]");
    const holdout = process.argv.find((arg) => arg.startsWith("--holdout="))?.slice(10) ?? "(?:capture|holdout|test)";
    const maxPerClass = Number(process.argv.find((arg) => arg.startsWith("--max-per-class="))?.slice(16) ?? Number.POSITIVE_INFINITY);
    const orientationValue = process.argv.find((arg) => arg.startsWith("--orientation="))?.slice(14) ?? "any";
    if (orientationValue !== "any" && orientationValue !== "upright") throw new Error(`Invalid orientation: ${orientationValue}`);
    const tileMatcher = layoutSchema.shape.tileMatcher.parse(process.argv.find(arg => arg.startsWith("--matcher="))?.slice(10));
    const report = await validateTemplateDirectory(path, { holdoutPattern: new RegExp(holdout, "i"), maxPerClass, orientation: orientationValue, tileMatcher });
    const output = process.argv.find((arg) => arg.startsWith("--output="))?.slice(9);
    if (output) await writeFile(output, JSON.stringify(report, null, 2), { encoding: "utf8", mode: 0o600 });
    console.log(JSON.stringify(output ? {
      output,
      total: report.total,
      accuracy: report.accuracy,
      automationSafeRate: report.automationSafeRate,
      passesAutoCalibration: report.passesAutoCalibration,
      crossLabelCollisions: report.crossLabelCollisions.length,
    } : report, null, 2));
    return;
  }
  if (command === "certify-layout") {
    const reportPath = process.argv[4];
    const outputPath = process.argv[5];
    if (!path || !reportPath || !outputPath) throw new Error("Usage: certify-layout <layout.json> <validation-report.json> <output-layout.json>");
    const layout = layoutSchema.parse(JSON.parse(await readFile(path, "utf8")));
    const report = JSON.parse(await readFile(reportPath, "utf8"));
    if (report.matcherVersion !== "2" || report.tileMatcher !== layout.tileMatcher) {
      throw new Error("Validation matcher/version does not match layout; rerun validation");
    }
    if (report.passesAutoCalibration !== true || report.accuracy !== 1 || report.automationSafeRate !== 1 || report.total < AUTO_MINIMUM_HOLDOUTS) {
      throw new Error("Validation report does not satisfy Auto calibration requirements");
    }
    const certified = layoutSchema.parse({
      ...layout,
      autoOperation: {
        enabled: true,
        recognizer: "template",
        matcherVersion: report.matcherVersion,
        tileMatcher: report.tileMatcher,
        samples: report.total,
        accuracy: report.accuracy,
        automationSafeRate: report.automationSafeRate,
        validatedAt: new Date().toISOString(),
        templateSetFingerprint: report.templateSetFingerprint,
      },
    });
    await writeFile(outputPath, JSON.stringify(certified, null, 2), { encoding: "utf8", mode: 0o600 });
    console.log(JSON.stringify({ certifiedLayout: outputPath, templateSetFingerprint: report.templateSetFingerprint }, null, 2));
    return;
  }
  if (command === "turn" || command === "watch") {
    const publicStatePath = path;
    const layoutPath = process.argv[4];
    const templates = process.argv[5];
    if (!publicStatePath || !layoutPath || !templates) throw new Error(`Usage: ${command} <public-state.json> <layout.json> <templates> [--cdp=URL] [--mode=observer|advisor|auto]`);
    const cdp = process.argv.find((arg) => arg.startsWith("--cdp="))?.slice(6) ?? "http://127.0.0.1:9222";
    const modeValue = process.argv.find((arg) => arg.startsWith("--mode="))?.slice(7) ?? "advisor";
    if (!(["observer", "advisor", "auto"] as string[]).includes(modeValue)) throw new Error(`Invalid mode: ${modeValue}`);
    const layout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
    const rawState = JSON.parse(await readFile(publicStatePath, "utf8"));
    delete rawState.hand;
    delete rawState.draw;
    delete rawState.recognitionConfidence;
    delete rawState.recognition_confidence;
    const publicState = parsePublicGameState(rawState);
    const session = await connectJantama(cdp);
    const recognizerValue = process.argv.find((arg) => arg.startsWith("--recognizer="))?.slice(13) ?? "hybrid";
    const recognizer = modelRecognizer(recognizerValue);
    try {
      const apiKey = process.env.TYPESAFE_API_KEY;
      const context = {
        page: session.page,
        mode: modeValue as "observer" | "advisor" | "auto",
        layout,
        templateDirectory: templates,
        ...(process.argv.find((arg) => arg.startsWith("--action-templates="))?.slice(19)
          ? { actionTemplateDirectory: process.argv.find((arg) => arg.startsWith("--action-templates="))!.slice(19) }
          : {}),
        artifactDirectory: "artifacts",
        publicState,
        ...(apiKey ? { jev: new JevClient(apiKey) } : {}),
        useUntrustedPublicObservation: process.argv.includes("--use-public-observation"),
        ...(recognizer ? { tileRecognizer: recognizer } : {}),
      };
      if (command === "watch") {
        const pollIntervalMs = Number(process.argv.find((arg) => arg.startsWith("--poll="))?.slice(7) ?? 750);
        const maxTurnsArgument = process.argv.find((arg) => arg.startsWith("--max-turns="))?.slice(12);
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
    return;
  }
  throw new Error("Commands: advise, jev-smoke, jev-tune, recognize, evaluate-frame, verify-discard-frame, detect-regions, recognize-regions, recognize-center, recognize-actions, propose-hand-layout, analyze-screenshot, watch-hand-layout, live-advisor, replay, attach-result, benchmark, policy-compare, collect-templates, validate-templates, certify-layout, turn, watch");
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
