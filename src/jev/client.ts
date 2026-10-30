import { assertYonmaEvaluation } from "../game/state.js";
import { isAllLastRound, type GameState } from "../game/state.js";
import type { DiscardEvaluation } from "../game/ukeire.js";
import type { LegalAction } from "../game/actions.js";
import { normalizeTile, parseGameTile } from "../game/tiles.js";
import type { ClosedWaitReport } from "../evaluation/closedWaitScorer.js";
import type { OpenTenpaiScore } from "../evaluation/openTenpaiScore.js";
import { handPlanMeldSignature, isHandPlanFeasible, type HandPlanMeld } from "../agent/handPlanFeasibility.js";
import { discardTacticalContext } from "./discardContext.js";

export interface JevDecision {
  actionId: string;
  confidence: number;
  probabilities: Record<string, number>;
  model: string;
  promptVersion: string;
  latencyMs: number;
  usage?: { input_tokens: number; output_tokens: number };
}

export type JevPromptProfile = "legacy-v1" | "balanced-v2" | "hierarchical-v3";

export interface JevHandPlan extends JevDecision {
  planId: string;
  sourceHand: string[];
  openMelds: number;
  melds?: HandPlanMeld[];
  createdAt: string;
}

export interface HandPlanInput {
  hand: readonly string[];
  openMelds: number;
  melds?: readonly HandPlanMeld[];
  seat?: string;
  round?: string;
}

interface JevChoiceQuestion {
  type: "choice";
  instructions: string | Record<string, unknown>;
  criteria: Record<string, string | Record<string, unknown>>;
}

interface JevRequest {
  model: string;
  state: Record<string, unknown>;
  questions: { action: JevChoiceQuestion };
}

const MAX_RESPONSE_BYTES = 1_000_000;
const DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone";

function promptVersion(profile: JevPromptProfile): string {
  if (profile === "legacy-v1") return "mahjong-discard-v1";
  return profile === "balanced-v2" ? "mahjong-discard-v2" : "mahjong-discard-hierarchical-v3";
}

function configuredProfile(value = process.env.JEV_PROMPT_PROFILE): JevPromptProfile {
  const profile = value ?? "hierarchical-v3";
  if (profile !== "legacy-v1" && profile !== "balanced-v2" && profile !== "hierarchical-v3") {
    throw new Error(`Unsupported Jev prompt profile: ${profile}`);
  }
  return profile;
}

export class JevClient {
  constructor(
    private readonly apiKey: string,
    private readonly endpoint = DEFAULT_ENDPOINT,
    private readonly model = process.env.JEV_MODEL ?? "jev-latest",
    private readonly profile: JevPromptProfile = configuredProfile(),
  ) {}

  async chooseDiscard(
    state: GameState,
    candidates: readonly DiscardEvaluation[],
    signal?: AbortSignal,
    handPlan?: JevHandPlan,
  ): Promise<JevDecision> {
    if (!this.apiKey) throw new Error("TYPESAFE_API_KEY is required");
    if (candidates.length < 2) {
      const only = candidates[0];
      if (!only) throw new Error("No candidates");
      return {
        actionId: only.actionId,
        confidence: 1,
        probabilities: { [only.actionId]: 1 },
        model: this.model,
        promptVersion: promptVersion(this.profile),
        latencyMs: 0,
      };
    }
    const request = buildJevRequest(state, candidates, this.model, this.profile, handPlan);
    const ids = Object.keys(request.questions.action.criteria);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20_000);
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    const startedAt = performance.now();
    try {
      const response = await fetch(this.endpoint, {
        method: "POST",
        headers: { Authorization: `Bearer ${this.apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify(request),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`Jev request failed with HTTP ${response.status}`);
      const raw = await readBoundedJson(response);
      const answer = raw?.answers?.action;
      const probabilities = validateChoice(answer, ids);
      if (typeof raw.model !== "string" || raw.model.length === 0 || raw.model.length > 200) throw new Error("Invalid Jev model identifier");
      const usage = validateUsage(raw.usage);
      return {
        actionId: answer.choice,
        confidence: answer.confidence,
        probabilities,
        model: raw.model,
        promptVersion: promptVersion(this.profile),
        latencyMs: Math.max(0, Math.round(performance.now() - startedAt)),
        ...(usage ? { usage } : {}),
      };
    } finally {
      clearTimeout(timeout);
      signal?.removeEventListener("abort", abort);
    }
  }

  async chooseHandPlan(input: HandPlanInput, signal?: AbortSignal): Promise<JevHandPlan> {
    if (!this.apiKey) throw new Error("TYPESAFE_API_KEY is required");
    const canonicalHand = input.hand.map((tile) => parseGameTile(tile));
    const canonicalMelds = input.melds?.map(meld => ({ type: meld.type, tiles: meld.tiles.map(parseGameTile) }));
    const request = buildJevHandPlanRequest({ ...input, hand: canonicalHand,
      ...(canonicalMelds ? { melds: canonicalMelds } : {}) }, this.model);
    const decision = await this.choose(request, "mahjong-hand-plan-v1", signal);
    return {
      ...decision,
      planId: decision.actionId,
      sourceHand: canonicalHand,
      openMelds: input.openMelds,
      ...(canonicalMelds ? { melds: canonicalMelds } : {}),
      createdAt: new Date().toISOString(),
    };
  }

  async chooseReaction(state: GameState, actions: readonly LegalAction[], signal?: AbortSignal): Promise<JevDecision> {
    if (!this.apiKey) throw new Error("TYPESAFE_API_KEY is required");
    if (actions.length === 0) throw new Error("No reaction candidates");
    if (actions.length === 1) return {
      actionId: actions[0]!.id, confidence: 1, probabilities: { [actions[0]!.id]: 1 },
      model: this.model, promptVersion: "mahjong-reaction-v1", latencyMs: 0,
    };
    const request = buildJevReactionRequest(state, actions, this.model);
    return this.choose(request, "mahjong-reaction-v1", signal);
  }

  async chooseDeclaration(state: GameState, actions: readonly LegalAction[], report: ClosedWaitReport, signal?: AbortSignal): Promise<JevDecision> {
    return this.choose(buildJevDeclarationRequest(state, actions, report, this.model), "mahjong-declaration-v1", signal);
  }

  private async choose(request: JevRequest, version: string, signal?: AbortSignal): Promise<JevDecision> {
    if (signal?.aborted) throw new Error("Jev request aborted");
    const ids = Object.keys(request.questions.action.criteria);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20_000);
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    const startedAt = performance.now();
    try {
      const response = await fetch(this.endpoint, {
        method: "POST", headers: { Authorization: `Bearer ${this.apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify(request), signal: controller.signal,
      });
      if (!response.ok) throw new Error(`Jev request failed with HTTP ${response.status}`);
      const raw = await readBoundedJson(response);
      const answer = raw?.answers?.action;
      const probabilities = validateChoice(answer, ids);
      if (typeof raw.model !== "string" || raw.model.length === 0 || raw.model.length > 200) throw new Error("Invalid Jev model identifier");
      const usage = validateUsage(raw.usage);
      return { actionId: answer.choice, confidence: answer.confidence, probabilities, model: raw.model,
        promptVersion: version, latencyMs: Math.max(0, Math.round(performance.now() - startedAt)), ...(usage ? { usage } : {}) };
    } finally {
      clearTimeout(timeout);
      signal?.removeEventListener("abort", abort);
    }
  }
}

function matchPlacementContext(state: GameState) {
  return state.matchLength === undefined ? {} : { matchLength: state.matchLength, allLast: isAllLastRound(state) };
}

export function buildJevDeclarationRequest(state: GameState, actions: readonly LegalAction[], report: ClosedWaitReport, model: string): JevRequest {
  assertYonmaEvaluation(state);
  if (actions.length !== 2 || !actions.some((action) => action.action === "discard")
    || !actions.some((action) => action.action === "riichi")
    || actions.some((action) => !("tile" in action) || action.tile !== report.discard)) {
    throw new Error("Declaration comparison requires matching discard and riichi actions");
  }
  return { model, state: {
    promptVersion: "mahjong-declaration-v1", task: "Compare riichi and dama for the same tenpai discard",
    round: state.round, seat: state.seat, scores: state.scores, honba: state.honba,
    ...matchPlacementContext(state),
    riichiSticks: state.riichiSticks, remainingTiles: state.remainingTiles, turn: state.turn,
    hand: [...state.hand, ...(state.draw ? [state.draw] : [])], opponents: state.opponents,
    ownDiscards: state.ownDiscards, doraIndicators: state.doraIndicators, scoring: report,
  }, questions: { action: { type: "choice", instructions: {
    question: "Which listed action best balances match placement, winning opportunities and defensive flexibility?",
    evidence_limits: ["Scoring is conditional on winning, not a calibrated win probability or expected value.",
      "A no_yaku dama ron cannot win an ordinary discard; do not invent a yaku.",
      "Riichi spends 1000 points and locks subsequent discards; dama retains defensive flexibility.",
      "Immediate rank is not final rank: account for dealer continuation and excluded bonuses.",
      "Missing opponent meld evidence is unknown, not proof of a closed or safe opponent."],
    output_constraint: "Select exactly one listed action id.",
  }, criteria: Object.fromEntries(actions.map((action) => [action.id, { action: action.action, tile: report.discard }])) } } };
}

export function buildJevReactionRequest(state: GameState, actions: readonly LegalAction[], model: string): JevRequest {
  assertYonmaEvaluation(state);
  if (!state.pendingDiscard) throw new Error("Reaction request requires pendingDiscard");
  const criteria = Object.fromEntries(actions.map((action) => [action.id, {
    action: action.action,
    ...(action.action === "chi" || action.action === "pon" || action.action === "minkan"
      ? { calledTile: action.tile, consumedTiles: action.consumedTiles,
        ...(action.consumedTileChoices ? { consumedTileChoices: action.consumedTileChoices } : {}) } : {}),
  }]));
  return {
    model,
    state: {
      promptVersion: "mahjong-reaction-v1", task: "Choose whether to call in Japanese Mahjong",
      round: state.round, honba: state.honba, riichiSticks: state.riichiSticks, seat: state.seat,
      ...matchPlacementContext(state),
      scores: state.scores, turn: state.turn, remainingTiles: state.remainingTiles,
      hand: state.hand, doraIndicators: state.doraIndicators, ownDiscards: state.ownDiscards,
      melds: state.melds, opponents: state.opponents, pendingDiscard: state.pendingDiscard,
    },
    questions: { action: { type: "choice", instructions: {
      question: "Which legal reaction best maximizes expected match outcome?",
      use_evidence: ["Use the complete supplied board state.", "Prefer passing when a call does not materially improve the hand.",
        "Take ron immediately unless the supplied match context strongly justifies otherwise.", "Do not invent an unlisted action."],
      output_constraint: "Select exactly one listed action id.",
    }, criteria } },
  };
}

function compactOpenScoring(score: OpenTenpaiScore, applied?: boolean) {
  return {
    scope: score.scope,
    used_for_hand_value: Boolean(applied),
    known_discard_furiten: score.knownDiscardFuriten,
    ron_ukeire: score.ronUkeire,
    tsumo_ukeire: score.tsumoUkeire,
    conditional_conservative_points: score.conditionalConservativePoints,
    winning_tiles: score.waits.filter(wait => wait.remaining > 0).map(wait => ({ tile: wait.tile,
      remaining: wait.remaining, ron_scoring_points: wait.ron?.total ?? null, tsumo_scoring_points: wait.tsumo?.total ?? null })),
  };
}

export function buildJevRequest(
  state: GameState,
  candidates: readonly DiscardEvaluation[],
  model: string,
  profile: JevPromptProfile,
  handPlan?: JevHandPlan,
): JevRequest {
  assertYonmaEvaluation(state);
  const version = promptVersion(profile);
  const commonState = {
    promptVersion: version,
    task: "Choose the strongest legal Japanese Mahjong discard",
    round: state.round,
    ...matchPlacementContext(state),
    honba: state.honba,
    riichiSticks: state.riichiSticks,
    seat: state.seat,
    scores: state.scores,
    turn: state.turn,
    remainingTiles: state.remainingTiles,
    phase: state.phase,
    openMelds: state.openMelds,
    riichiDeclared: state.riichiDeclared,
    hand: state.draw ? [...state.hand, state.draw] : state.hand,
    doraIndicators: state.doraIndicators,
    ownDiscards: state.ownDiscards,
    melds: state.melds,
    opponents: state.opponents,
  };
  if (profile === "legacy-v1") {
    const criteria = Object.fromEntries(candidates.map((candidate) => [
      candidate.actionId,
      `Discard ${candidate.tile}; shanten ${candidate.shanten}; ukeire ${candidate.ukeire}; estimated value ${candidate.estimatedValue ?? "unknown"}; win estimate ${((candidate.winProbability ?? 0) * 100).toFixed(1)}%; tenpai estimate ${((candidate.tenpaiProbability ?? 0) * 100).toFixed(1)}%; combined deal-in estimate ${((candidate.dealInProbability ?? candidate.danger ?? 0) * 100).toFixed(1)}%; heuristic round EV ${candidate.expectedRoundValue ?? "unknown"}; effective tiles ${candidate.effectiveTiles.map((x) => `${x.tile}:${x.remaining}`).join(", ") || "none"}.`,
    ]));
    return {
      model,
      state: {
        ...commonState,
        candidates: candidates.map(({ actionId, tile, shanten, ukeire, estimatedValue, winProbability, tenpaiProbability, dealInProbability, expectedRoundValue, evaluationModel, effectiveTiles, openTenpaiScore, openTenpaiScoreApplied, openOneShantenYaku }) => ({ actionId, tile, shanten, ukeire, estimatedValue, winProbability, tenpaiProbability, dealInProbability, expectedRoundValue, evaluationModel, effectiveTiles,
          ...(openOneShantenYaku ? { shortest_ordinary_open_progress: openOneShantenYaku } : {}),
          ...(openTenpaiScore ? { ordinary_open_waits: compactOpenScoring(openTenpaiScore, openTenpaiScoreApplied) } : {}) })),
      },
      questions: {
        action: {
          type: "choice",
          instructions: "Select exactly one legal discard. Prioritize lower shanten, then broad high-quality ukeire. Shortest ordinary open progress is not all future routes; zero ordinary progress does not prohibit a defensive discard. Do not invent an action.",
          criteria,
        },
      },
    };
  }

  const tactical = discardTacticalContext(state, candidates);
  const bestUkeire = Math.max(...candidates.map((candidate) => candidate.ukeire));
  const bestShanten = Math.min(...candidates.map((candidate) => candidate.shanten));
  const criteria = Object.fromEntries(candidates.map((candidate) => [
    candidate.actionId,
    {
      action: `Discard ${candidate.tile}`,
      tactical_facts: tactical.criteria.get(candidate.actionId)!,
      hand_progress: {
        shanten_after_discard: candidate.shanten,
        hand_form: candidate.form,
        ukeire: candidate.ukeire,
        effective_tiles: candidate.effectiveTiles.map(({ tile, remaining }) => `${tile}:${remaining}`),
      },
      outcome_estimates: {
        hand_value_points: candidate.estimatedValue ?? "unknown",
        win_probability: candidate.winProbability ?? "unknown",
        tenpai_probability: candidate.tenpaiProbability ?? "unknown",
        deal_in_probability: candidate.dealInProbability ?? candidate.danger ?? "unknown",
        expected_round_points: candidate.expectedRoundValue ?? "unknown",
        estimate_source: candidate.evaluationModel ?? "unknown",
        ...(candidate.closedWaitScore ? { closed_wait_scoring: candidate.closedWaitScore } : {}),
        ...(candidate.openOneShantenYaku ? { shortest_ordinary_open_progress: candidate.openOneShantenYaku } : {}),
        ...(candidate.openTenpaiScore ? { ordinary_open_waits: compactOpenScoring(candidate.openTenpaiScore, candidate.openTenpaiScoreApplied) } : {}),
      },
      ...(profile === "hierarchical-v3" ? { comparison_to_best: {
        shanten_gap: candidate.shanten - bestShanten,
        ukeire_gap: candidate.ukeire - bestUkeire,
      } } : {}),
    },
  ]));
  const compatiblePlan = handPlan && isHandPlanCompatible(handPlan, commonState.hand, state.openMelds, state.melds)
    ? summarizeHandPlan(handPlan, state.openMelds, state.melds)
    : undefined;
  return {
    model,
    // Candidate data lives only in criteria. Duplicating it in state adds tokens and
    // context rot without adding evidence.
    state: {
      ...commonState,
      tactical_summary: tactical.summary,
      ...(profile === "hierarchical-v3" ? { data_quality: {
        round_known: state.round !== "unknown",
        scores_complete: ["east", "south", "west", "north"].every((seat) => state.scores[seat] !== undefined),
        remaining_tiles_known: state.remainingTiles !== undefined,
        dora_known: state.doraIndicators.length > 0,
      } } : {}),
      ...(profile === "hierarchical-v3" && compatiblePlan ? { cached_hand_plan: compatiblePlan } : {}),
    },
    questions: {
      action: {
        type: "choice",
        instructions: profile === "balanced-v2" ? {
          question: "Which legal discard best maximizes expected match outcome from this position?",
          use_evidence: [
            "Use the supplied candidate estimates; do not recompute exact arithmetic or invent missing facts.",
            "Preserve lower shanten unless a supplied expected-round-points or safety difference justifies another option.",
            "Use tactical_facts to distinguish keeping tenpai from breaking it, live waits from exhausted waits, and exact red/indicator dora retained or lost. Dora are bonuses, not a yaku; do not preserve an isolated dora at any cost.",
            "Discard-furiten covers all structural waits including exhausted ones; temporary and riichi-pass furiten are unobserved. Structural waits do not prove yaku or a legal ron.",
            "Compare ukeire quality, hand value, win chance and tenpai chance for offense.",
            "For closed tenpai, compare supplied riichi and dama scoring outcomes with other discards' danger; scoring is not a policy EV and does not establish furiten safety.",
            "Ordinary open waits distinguish scoring wins from structural ukeire; null scoring points mean no ordinary yaku for that mode. Situational yaku and UI win legality are outside that scoring scope.",
            "Shortest ordinary open progress covers only one structural improvement followed by ordinary winning waits, not longer reconstruction or situational yaku. Zero ordinary progress does not prohibit a defensive discard.",
            "When an opponent is riichi or pressure is otherwise visible, give deal-in probability substantially more weight.",
            "Use round, scores, seat, honba, riichi sticks, turn and remaining tiles for placement and urgency.",
          ],
          output_constraint: "Select exactly one listed action id.",
        } : {
          question: "Which legal discard best maximizes expected placement-adjusted match outcome from this position?",
          use_evidence: [
            "First preserve minimum shanten; deviate only for a material supplied safety or expected-round-points advantage.",
            "Use tactical_facts to compare tenpai preservation, all structural waits and exact dora loss/retention. Do not break a live, legally scoring tenpai without a concrete defensive or placement justification; inferred EV is heuristic, not calibrated evidence.",
            "Dora are bonuses, not a yaku. Discarding an isolated dora for tenpai or material efficiency/safety can be correct; never impose unconditional dora retention.",
            "Discard-furiten includes exhausted structural waits. Temporary and riichi-pass furiten are unobserved, and structural waits alone do not prove yaku or legal ron.",
            "Second compare ukeire quality, hand value, win chance and tenpai chance using the supplied estimates.",
            "For closed tenpai, compare supplied riichi and dama scoring outcomes against defensive choices; scoring is not policy EV and does not establish furiten safety.",
            "Ordinary open waits distinguish scoring wins from structural ukeire; null scoring points mean no ordinary yaku for that mode. Situational yaku and UI win legality are outside that scoring scope.",
            "Shortest ordinary open progress covers only one structural improvement followed by ordinary winning waits, not longer reconstruction or situational yaku. Zero ordinary progress does not prohibit a defensive discard.",
            "Third, when riichi or two-or-more open meld pressure is visible, prioritize avoiding deal-in unless placement urgency clearly warrants pushing.",
            "Treat cached_hand_plan only as a soft tie-breaker among tactically close choices; abandon it when current safety, shanten, ukeire or EV disagrees.",
            "Use placement context only when its fields are known. Never infer scores, round, remaining tiles, danger or yaku that are not supplied.",
            "Do not recompute exact arithmetic and do not invent missing facts.",
          ],
          output_constraint: "Select exactly one listed action id.",
        },
        criteria,
      },
    },
  };
}

const HAND_PLAN_DEFINITIONS = {
  efficient_standard: {
    label: "Efficient standard hand",
    objective: "Keep the strongest standard-hand shape and broadest useful draws; remain flexible about yaku.",
  },
  closed_sequence: {
    label: "Closed sequence value",
    objective: "Prefer a closed riichi/pinfu-oriented sequence hand when the shape supports it.",
  },
  tanyao: {
    label: "Tanyao",
    objective: "Move toward an all-simples hand without paying a large efficiency cost.",
  },
  yakuhai: {
    label: "Yakuhai",
    objective: "Preserve a real value-honor pair or triplet as a reliable yaku source.",
  },
  chiitoitsu: {
    label: "Seven pairs",
    objective: "Develop seven pairs when pair density makes it competitive with the standard form.",
  },
  toitoi: {
    label: "All triplets",
    objective: "Develop triplets from a strongly paired hand, allowing calls when tactically justified.",
  },
  honitsu_m: { label: "Half flush in characters", objective: "Concentrate on characters plus honors." },
  honitsu_p: { label: "Half flush in circles", objective: "Concentrate on circles plus honors." },
  honitsu_s: { label: "Half flush in bamboo", objective: "Concentrate on bamboo plus honors." },
  ittsuu_m: { label: "Pure straight in characters", objective: "Preserve 123/456/789 potential in characters." },
  ittsuu_p: { label: "Pure straight in circles", objective: "Preserve 123/456/789 potential in circles." },
  ittsuu_s: { label: "Pure straight in bamboo", objective: "Preserve 123/456/789 potential in bamboo." },
  sanshoku: { label: "Mixed triple sequence", objective: "Preserve the same sequence across all three suits when the overlap is real." },
} as const;

type HandPlanId = keyof typeof HAND_PLAN_DEFINITIONS;

function handPlanCandidates(input: HandPlanInput): Array<[HandPlanId, Record<string, unknown>]> {
  const hand = input.hand.map(normalizeTile);
  const counts = new Map<string, number>();
  for (const tile of hand) counts.set(tile, (counts.get(tile) ?? 0) + 1);
  const suitTiles = (suit: "m" | "p" | "s") => hand.filter((tile) => tile.endsWith(suit));
  const honors = hand.filter((tile) => tile.length === 1);
  const terminals = hand.filter((tile) => tile.length > 1 && (tile[0] === "1" || tile[0] === "9"));
  const pairTypes = [...counts.values()].filter((count) => count >= 2).length;
  const tripletTypes = [...counts.values()].filter((count) => count >= 3).length;
  const candidates: Array<[HandPlanId, Record<string, unknown>]> = [];
  const add = (id: HandPlanId, fit: Record<string, unknown>) => {
    if (!isHandPlanFeasible(id, input.openMelds, input.melds)) return;
    candidates.push([id, {
      ...HAND_PLAN_DEFINITIONS[id], fit_evidence: fit,
      commitment_rule: "This is a soft direction, never a reason to accept a material shanten, ukeire, safety, or EV loss.",
    }]);
  };
  add("efficient_standard", { pair_types: pairTypes, triplet_types: tripletTypes, open_melds: input.openMelds });
  if (input.openMelds === 0) add("closed_sequence", { honors: honors.length, pair_types: pairTypes });
  if (honors.length + terminals.length <= 5) add("tanyao", { simple_tiles: hand.length - honors.length - terminals.length, blockers: honors.length + terminals.length });
  const roundWind = input.round?.match(/^(east|south|west|north)/i)?.[1]?.[0]?.toUpperCase();
  const honorNames: Record<string, string> = { E: "east", S: "south", W: "west", N: "north", P: "white dragon", F: "green dragon", C: "red dragon" };
  const valueHonors = ["P", "F", "C", input.seat?.[0]?.toUpperCase(), roundWind].filter(Boolean) as string[];
  const valueHonorPairs = [...new Set(valueHonors)].filter((tile) => (counts.get(tile) ?? 0) >= 2);
  if (valueHonorPairs.length) add("yakuhai", { value_honor_pairs: valueHonorPairs.map((tile) => honorNames[tile] ?? tile) });
  if (input.openMelds === 0 && pairTypes >= 4) add("chiitoitsu", { pair_types: pairTypes });
  if (pairTypes + tripletTypes >= 4) add("toitoi", { pair_types: pairTypes, triplet_types: tripletTypes });
  for (const suit of ["m", "p", "s"] as const) {
    const suited = suitTiles(suit);
    if (suited.length + honors.length >= Math.max(9, hand.length - 3)) {
      add(`honitsu_${suit}`, { suited_tiles: suited.length, honors: honors.length, off_suit_tiles: hand.length - suited.length - honors.length });
    }
    const ranks = new Set(suited.map((tile) => Number(tile[0])));
    const sections = [[1, 2, 3], [4, 5, 6], [7, 8, 9]].map((section) => section.filter((rank) => ranks.has(rank)).length);
    if (ranks.size >= 6 && sections.every((size) => size >= 1)) add(`ittsuu_${suit}`, { distinct_ranks: [...ranks].sort(), section_coverage: sections });
  }
  let bestSanshoku: { start: number; coverage: number } | undefined;
  for (let start = 1; start <= 7; start += 1) {
    const coverage = (["m", "p", "s"] as const).reduce((sum, suit) => sum
      + [start, start + 1, start + 2].filter((rank) => counts.has(`${rank}${suit}`)).length, 0);
    if (!bestSanshoku || coverage > bestSanshoku.coverage) bestSanshoku = { start, coverage };
  }
  if (bestSanshoku && bestSanshoku.coverage >= 6) add("sanshoku", bestSanshoku);
  return candidates;
}

export function buildJevHandPlanRequest(input: HandPlanInput, model: string): JevRequest {
  const criteria = Object.fromEntries(handPlanCandidates(input));
  return {
    model,
    state: {
      promptVersion: "mahjong-hand-plan-v1",
      task: "Choose a soft offensive direction for a Japanese Mahjong hand before the next draw",
      hand: input.hand,
      openMelds: input.openMelds,
      ...(input.melds ? { melds: input.melds } : {}),
      seat: input.seat ?? "unknown",
      round: input.round ?? "unknown",
      board_information_intentionally_omitted: true,
    },
    questions: { action: { type: "choice", instructions: {
      question: "Which listed plan is the most realistic direction from this hand shape?",
      use_evidence: [
        "Judge only hand structure and the supplied fit evidence; board safety will be handled later.",
        "Prefer efficient_standard when a named yaku plan is speculative or requires several costly transformations.",
        "A plan is a soft prior for the next discard, not a commitment and not proof that the yaku will complete.",
        "Do not invent tiles, melds, yaku, or board facts.",
      ],
      output_constraint: "Select exactly one listed plan id.",
    }, criteria } },
  };
}

function summarizeHandPlan(plan: JevHandPlan, openMelds: number, melds?: readonly HandPlanMeld[]): Record<string, unknown> {
  const definition = HAND_PLAN_DEFINITIONS[plan.planId as HandPlanId];
  const alternatives = Object.entries(plan.probabilities)
    .filter(([id]) => isHandPlanFeasible(id, openMelds, melds))
    .sort(([, left], [, right]) => right - left)
    .slice(0, 3)
    .map(([id, probability]) => ({ id, probability }));
  return {
    selected: plan.planId,
    label: definition?.label ?? plan.planId,
    objective: definition?.objective ?? "Unknown plan",
    confidence: plan.confidence,
    alternatives,
  };
}

export function isHandPlanCompatible(
  plan: JevHandPlan, currentHand: readonly string[], openMelds: number, melds?: readonly HandPlanMeld[],
): boolean {
  if (plan.openMelds !== openMelds || currentHand.length !== plan.sourceHand.length + 1) return false;
  const sourceSignature = handPlanMeldSignature(plan.openMelds, plan.melds);
  const currentSignature = handPlanMeldSignature(openMelds, melds);
  if (plan.melds !== undefined && sourceSignature === undefined) return false;
  if (sourceSignature !== undefined && currentSignature !== undefined && sourceSignature !== currentSignature) return false;
  // Legacy open plans have no immutable-group provenance. Preserve their
  // generic prior, but never certify a named yaku from missing evidence.
  if (openMelds > 0 && sourceSignature === undefined && plan.planId !== "efficient_standard") return false;
  if (!isHandPlanFeasible(plan.planId, openMelds, melds)) return false;
  const available = new Map<string, number>();
  for (const tile of currentHand.map(normalizeTile)) available.set(tile, (available.get(tile) ?? 0) + 1);
  for (const tile of plan.sourceHand.map(normalizeTile)) {
    const count = available.get(tile) ?? 0;
    if (count === 0) return false;
    available.set(tile, count - 1);
  }
  return true;
}

export function handPlanInputCacheKey(input: HandPlanInput): string {
  return JSON.stringify({ hand: [...input.hand].map(parseGameTile).sort(), openMelds: input.openMelds,
    melds: handPlanMeldSignature(input.openMelds, input.melds) ?? null,
    seat: input.seat ?? null, round: input.round ?? null });
}

async function readBoundedJson(response: Response): Promise<any> {
  const declaredLength = Number(response.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_BYTES) throw new Error("Jev response is too large");
  const text = await response.text();
  if (Buffer.byteLength(text, "utf8") > MAX_RESPONSE_BYTES) throw new Error("Jev response is too large");
  try {
    return JSON.parse(text);
  } catch {
    throw new Error("Jev returned malformed JSON");
  }
}

function validateUsage(raw: any): JevDecision["usage"] | undefined {
  if (raw === undefined) return undefined;
  if (
    !raw
    || !Number.isInteger(raw.input_tokens)
    || raw.input_tokens < 0
    || !Number.isInteger(raw.output_tokens)
    || raw.output_tokens < 0
  ) throw new Error("Invalid Jev usage");
  return { input_tokens: raw.input_tokens, output_tokens: raw.output_tokens };
}

function validateChoice(answer: any, ids: readonly string[]): Record<string, number> {
  if (!answer || answer.type !== "choice" || !ids.includes(answer.choice)) throw new Error("Invalid Jev choice");
  if (!Number.isFinite(answer.confidence) || answer.confidence < 0 || answer.confidence > 1) throw new Error("Invalid Jev confidence");
  const keys = Object.keys(answer.probabilities ?? {}).sort();
  if (keys.join("|") !== [...ids].sort().join("|")) throw new Error("Jev probability keys do not match candidates");
  const values = Object.values(answer.probabilities) as number[];
  if (values.some((value) => !Number.isFinite(value) || value < 0 || value > 1)) throw new Error("Invalid Jev probabilities");
  const sum = values.reduce((a, b) => a + b, 0);
  // Jev can return display-rounded probabilities (for example 0.99 or 1.01
  // in total). Accept a small rounding envelope and normalize before use.
  if (sum <= 0 || Math.abs(sum - 1) > 0.02) throw new Error("Jev probabilities do not sum to one");
  const maximum = Math.max(...values);
  if (Math.abs(answer.probabilities[answer.choice] - maximum) > 1e-9) throw new Error("Jev choice is not maximum probability");
  return Object.fromEntries(ids.map((id) => [id, answer.probabilities[id] / sum]));
}
