import { readFile } from "node:fs/promises";
import { realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parseGameState, parsePublicGameState, type PublicGameState } from "../game/state.js";
import { decideForceAutoWithJevDeadline } from "../agent/decision.js";
import { JevClient } from "../jev/client.js";
import { opponentStatesFromObservation, type PublicTileObservation } from "./publicTileRecognizer.js";

// The live reaction path already recognizes the prompt. Keep its decision
// entrypoint independent of the browser/calibration/reporting CLI imports.
export async function evaluateRecognizedReaction(
  rawState: Record<string, unknown>, observation: PublicTileObservation,
  recognition: { tiles: string[]; confidence: number; ambiguityMargin: number; safe: boolean },
  tile: string, fromSeat: string, availableUiActions: string[],
) {
  const { hand: _hand, draw: _draw, recognitionConfidence: _confidence,
    recognition_confidence: _legacyConfidence, ...publicFields } = rawState;
  const publicState = parsePublicGameState({
    ...publicFields,
    doraIndicators: observation.doraIndicators,
    ownDiscards: observation.ownDiscards,
    turn: observation.ownDiscards?.length ?? publicFields.turn,
    melds: observation.ownMelds,
    openMelds: observation.ownMelds?.length ?? publicFields.openMelds,
    opponents: opponentStatesFromObservation(observation, rawState.opponents as PublicGameState["opponents"]),
    phase: "reaction",
    pendingDiscard: { tile, fromSeat, inRiver: Boolean(observation.opponentDiscards?.some(
      opponent => opponent.seat === fromSeat && opponent.discards.at(-1) === tile,
    )) },
  });
  const expectedTiles = 13 - 3 * (publicState.openMelds ?? 0);
  if (recognition.tiles.length !== expectedTiles) {
    return { schemaVersion: 1, status: "not_ready", recognition: { ...recognition, turnReady: false } };
  }
  const state = parseGameState({ ...publicState, hand: recognition.tiles,
    availableUiActions, recognitionConfidence: recognition.confidence });
  const apiKey = process.env.TYPESAFE_API_KEY;
  const decision = await decideForceAutoWithJevDeadline(state, {
    ...(apiKey ? { jev: new JevClient(apiKey) } : {}),
    deadlineMs: Number(process.env.JEV_FORCE_AUTO_DEADLINE_MS ?? 2300),
  });
  return { schemaVersion: 1, status: "decision", state,
    recognition: { backend: "template", ...recognition }, decision };
}

function isEntrypoint(): boolean {
  if (!process.argv[1]) return false;
  try {
    // Frozen checkouts may share dist through a symlink. Node resolves the
    // module URL but preserves the invoked path in argv, so compare files.
    return realpathSync(fileURLToPath(import.meta.url)) === realpathSync(process.argv[1]);
  } catch {
    return false;
  }
}

if (isEntrypoint()) {
  const [statePath, observationPath, recognitionPath, tile, seat, actions] = process.argv.slice(2);
  try {
    if (!statePath || !observationPath || !recognitionPath || !tile || !seat || !actions) {
      throw new Error("Usage: reactionEvaluator <state> <observation> <recognition> <tile> <seat> <actions>");
    }
    const [state, observation, recognition] = await Promise.all(
      [statePath, observationPath, recognitionPath].map(async path => JSON.parse(await readFile(path, "utf8"))),
    );
    process.stdout.write(JSON.stringify(await evaluateRecognizedReaction(
      state, observation, recognition, tile, seat, actions.split(","),
    )) + "\n");
  } catch (error) {
    process.stderr.write((error instanceof Error ? error.message : String(error)) + "\n");
    process.exitCode = 1;
  }
}
