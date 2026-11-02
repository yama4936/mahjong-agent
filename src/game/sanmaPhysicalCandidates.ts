import { physicalConsumption } from "./physicalConsumption.js";
import { sanmaStructuralCandidates, type SanmaCandidate } from "./sanmaLegalExperiment.js";
import { parseGameState } from "./state.js";
import type { GameTile } from "./tiles.js";

type CallCandidate = Extract<SanmaCandidate, { action: "pon" | "minkan" | "ankan" | "kakan" }>;
export type SanmaPhysicalCallCandidate = CallCandidate & {
  /** Exact concealed copies required; alternatives are not an observed UI selection. */
  consumedTiles: GameTile[];
  consumedTileChoices?: GameTile[][];
  /** Present only for a reaction, preserving the red identity of the called tile. */
  calledTile?: GameTile;
};

/** Offline call hypotheses only: never an authorization to click or select tiles. */
export function sanmaPhysicalCallCandidates(input: Parameters<typeof sanmaStructuralCandidates>[0]): {
  scope: "offline_untrusted_sanma_physical_calls";
  candidates: SanmaPhysicalCallCandidate[];
  operationAuthorized: false;
} {
  const structural = sanmaStructuralCandidates(input);
  const state = parseGameState(input.state);
  const concealed = [...state.hand, ...(state.draw ? [state.draw] : [])];
  const candidates: SanmaPhysicalCallCandidate[] = [];
  for (const candidate of structural) {
    if (!["pon", "minkan", "ankan", "kakan"].includes(candidate.action)) continue;
    const call = candidate as CallCandidate;
    const count = call.action === "pon" ? 2 : call.action === "minkan" ? 3 : call.action === "ankan" ? 4 : 1;
    const consumption = physicalConsumption(concealed, Array(count).fill(call.tile));
    const calledTile = call.action === "pon" || call.action === "minkan" ? state.pendingDiscard!.tile : undefined;
    candidates.push({ ...call, ...consumption, ...(calledTile ? { calledTile } : {}) });
  }
  return { scope: "offline_untrusted_sanma_physical_calls", candidates, operationAuthorized: false };
}
