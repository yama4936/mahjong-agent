import { parseGameState } from "./state.js";
import { calculateShanten } from "./shanten.js";
import { sanmaStructuralCandidates } from "./sanmaLegalExperiment.js";

/** Offline hypothesis only; caller supplies unverified observations. */
export function inspectSanmaSelfTurnPriority(input: {
  state: unknown;
  riichiStatus: "not_declared" | "declared";
  ui: { status: "confirmed"; actions: readonly ("kita" | "tsumo" | "riichi" | "kan" | "pass")[] };
}) {
  if (!input || !["not_declared", "declared"].includes(input.riichiStatus) || input.ui?.status !== "confirmed" || !Array.isArray(input.ui.actions)
      || new Set(input.ui.actions).size !== input.ui.actions.length || input.ui.actions.some(x => !["kita", "tsumo", "riichi", "kan", "pass"].includes(x))) throw new Error("Explicit unambiguous UI and pre-riichi status required");
  if (!input.state || typeof input.state !== "object" || Array.isArray(input.state)) throw new Error("Explicit state required");
  const raw = input.state as Record<string, unknown>;
  if (input.riichiStatus === "declared") {
    if (raw.rules !== "sanma" || raw.phase !== "self_turn" || raw.riichiDeclared !== true
        || typeof raw.draw !== "string" || !Array.isArray(raw.hand) || !Array.isArray(raw.melds)
        || !Number.isInteger(raw.openMelds) || raw.openMelds !== raw.melds.length
        || raw.availableUiActions !== undefined || raw.available_ui_actions !== undefined) {
      throw new Error("Explicit sanma post-riichi draw and meld evidence required");
    }
    if (input.ui.actions.some(action => action !== "tsumo" && action !== "pass")) {
      throw new Error("Post-riichi kita, kan and other prompts require separate policy");
    }
    const state = parseGameState(raw);
    if (state.melds.some(meld => meld.type !== "ankan") || calculateShanten(state.hand, state.openMelds).shanten !== 0) {
      throw new Error("Post-riichi concealed hand must remain tenpai");
    }
    if (input.ui.actions.includes("tsumo")) {
      if (calculateShanten([...state.hand,state.draw!],state.openMelds).shanten !== -1) throw new Error("Tsumo UI without complete hand");
      return {scope:"offline_untrusted_sanma_self_turn" as const, stage:"win_candidate" as const,
        candidates:[{action:"tsumo" as const}], riichiDiscards:[], operationAuthorized:false as const};
    }
    if (input.ui.actions.length) throw new Error("Unresolved pass prompt after riichi");
    return {scope:"offline_untrusted_sanma_self_turn" as const, stage:"draw_discard_candidate" as const,
      candidates:[{action:"discard" as const,tile:state.draw!,physicalPosition:"draw" as const}],
      riichiDiscards:[],operationAuthorized:false as const};
  }
  if (raw.rules !== "sanma" || raw.phase !== "self_turn" || raw.riichiDeclared !== false || typeof raw.draw !== "string"
      || !Array.isArray(raw.hand) || !Array.isArray(raw.melds) || !Number.isInteger(raw.openMelds) || raw.openMelds !== raw.melds.length) throw new Error("Complete explicit self-turn state required");
  const state = parseGameState(raw);
  const otherActions = input.ui.actions.filter((a): a is "kita" | "tsumo" | "kan" | "pass" => a !== "riichi");
  const candidates = sanmaStructuralCandidates({state: raw, riichiStatus: "not_declared", ui: {status:"confirmed", actions: otherActions}});
  const riichiDiscards: string[] = [];
  if (input.ui.actions.includes("riichi")) {
    if (!raw.scores || typeof raw.scores !== "object" || Array.isArray(raw.scores)
        || !Number.isInteger((raw.scores as Record<string, unknown>)[state.seat])
        || state.scores[state.seat]! < 1000 || state.melds.some(m => m.type !== "ankan")) throw new Error("Riichi requires closed hand and explicit sufficient score");
    const hand = [...state.hand, state.draw!];
    for (const tile of new Set(hand)) {
      const remaining = [...hand]; remaining.splice(remaining.indexOf(tile), 1);
      if (calculateShanten(remaining, state.openMelds).shanten === 0) riichiDiscards.push(tile);
    }
    if (!riichiDiscards.length) throw new Error("Riichi UI without a tenpai discard");
  }
  // An offered win precedes other choices. Extraction versus riichi, kan, and
  // ordinary discard is strategic; an offer alone cannot choose among them.
  const stage = input.ui.actions.includes("tsumo") ? "win_candidate"
    : input.ui.actions.includes("kita") || input.ui.actions.includes("riichi") || input.ui.actions.includes("kan")
      ? "action_choice_required" : input.ui.actions.length ? "prompt_requires_review" : "discard_candidate";
  return {scope:"offline_untrusted_sanma_self_turn" as const, stage, candidates, riichiDiscards,
    operationAuthorized:false as const};
}
