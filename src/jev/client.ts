import type { GameState } from "../game/state.js";
import type { DiscardEvaluation } from "../game/ukeire.js";

export interface JevDecision {
  actionId: string;
  confidence: number;
  probabilities: Record<string, number>;
  model: string;
  promptVersion: string;
  latencyMs: number;
  usage?: { input_tokens: number; output_tokens: number };
}

export type JevPromptProfile = "legacy-v1" | "balanced-v2";

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
  return profile === "legacy-v1" ? "mahjong-discard-v1" : "mahjong-discard-v2";
}

function configuredProfile(value = process.env.JEV_PROMPT_PROFILE): JevPromptProfile {
  const profile = value ?? "balanced-v2";
  if (profile !== "legacy-v1" && profile !== "balanced-v2") {
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

  async chooseDiscard(state: GameState, candidates: readonly DiscardEvaluation[], signal?: AbortSignal): Promise<JevDecision> {
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
    const request = buildJevRequest(state, candidates, this.model, this.profile);
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
}

export function buildJevRequest(
  state: GameState,
  candidates: readonly DiscardEvaluation[],
  model: string,
  profile: JevPromptProfile,
): JevRequest {
  const version = promptVersion(profile);
  const commonState = {
    promptVersion: version,
    task: "Choose the strongest legal Japanese Mahjong discard",
    round: state.round,
    honba: state.honba,
    riichiSticks: state.riichiSticks,
    seat: state.seat,
    scores: state.scores,
    turn: state.turn,
    remainingTiles: state.remainingTiles,
    phase: state.phase,
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
        candidates: candidates.map(({ actionId, tile, shanten, ukeire, estimatedValue, winProbability, tenpaiProbability, dealInProbability, expectedRoundValue, evaluationModel, effectiveTiles }) => ({ actionId, tile, shanten, ukeire, estimatedValue, winProbability, tenpaiProbability, dealInProbability, expectedRoundValue, evaluationModel, effectiveTiles })),
      },
      questions: {
        action: {
          type: "choice",
          instructions: "Select exactly one legal discard. Prioritize lower shanten, then broad high-quality ukeire. Do not invent an action.",
          criteria,
        },
      },
    };
  }

  const criteria = Object.fromEntries(candidates.map((candidate) => [
    candidate.actionId,
    {
      action: `Discard ${candidate.tile}`,
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
      },
    },
  ]));
  return {
    model,
    // Candidate data lives only in criteria. Duplicating it in state adds tokens and
    // context rot without adding evidence.
    state: commonState,
    questions: {
      action: {
        type: "choice",
        instructions: {
          question: "Which legal discard best maximizes expected match outcome from this position?",
          use_evidence: [
            "Use the supplied candidate estimates; do not recompute exact arithmetic or invent missing facts.",
            "Preserve lower shanten unless a supplied expected-round-points or safety difference justifies another option.",
            "Compare ukeire quality, hand value, win chance and tenpai chance for offense.",
            "When an opponent is riichi or pressure is otherwise visible, give deal-in probability substantially more weight.",
            "Use round, scores, seat, honba, riichi sticks, turn and remaining tiles for placement and urgency.",
          ],
          output_constraint: "Select exactly one listed action id.",
        },
        criteria,
      },
    },
  };
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
