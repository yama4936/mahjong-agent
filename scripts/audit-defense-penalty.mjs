import fs from "node:fs";
import { parseGameState } from "../dist/src/game/state.js";
import { deterministicAdvice } from "../dist/src/evaluation/advisor.js";

// Read-only sensitivity analysis, not a replacement policy or win-rate test.
// Run npm run build first. Preserve every recorded input except the comparator's
// extra defense deduction; the base expectedRoundValue still includes defense.
const file = process.argv[2];
if (!file) throw new Error("Usage: node scripts/audit-defense-penalty.mjs <python-operator.jsonl>");
const rows = fs.readFileSync(file, "utf8").trim().split(/\r?\n/).filter(Boolean).map(JSON.parse);
const changes = [], errors = [];
let checked = 0;
for (const row of rows.filter(row => row.event === "decision")) {
  try {
    const state = parseGameState(row.evaluation.state);
    const current = deterministicAdvice(state);
    const candidates = [...current.candidates];
    const minimum = Math.min(...candidates.map(c => c.shanten));
    const threat = state.opponents.some(o => o.riichi || o.openMelds >= 2);
    const phase = state.turn <= 6 ? "early" : state.turn <= 11 ? "middle" : "late";
    const scores = Object.values(state.scores).sort((a, b) => b - a);
    const rank = scores.indexOf(state.scores[state.seat]) + 1;
    const urgent = /^(south|west|north)_4$/i.test(state.round) && rank === 4;
    candidates.sort((a, b) => {
      const value = (b.expectedRoundValue ?? -Infinity) - (a.expectedRoundValue ?? -Infinity);
      if (phase === "early" && !threat) return a.shanten - b.shanten || b.ukeire - a.ukeire || value;
      if (!threat && phase !== "late" && a.shanten !== b.shanten) return a.shanten - b.shanten;
      const ar = a.shanten <= minimum + 1, br = b.shanten <= minimum + 1;
      if (ar !== br) return ar ? -1 : 1;
      if ((threat || phase === "late") && !urgent && ar && br && value) return value;
      if (threat && ar && br && value) return value;
      return a.shanten - b.shanten || value || b.ukeire - a.ukeire;
    });
    checked++;
    if (current.tile !== candidates[0].tile) changes.push({
      timestamp: row.timestamp, round: state.round, turn: state.turn, threat,
      current: current.tile, singlePenalty: candidates[0].tile,
      currentShanten: current.candidates[0].shanten,
      singlePenaltyShanten: candidates[0].shanten,
    });
  } catch (error) { errors.push({ timestamp: row.timestamp, error: String(error) }); }
}
console.log(JSON.stringify({ scope: "local comparator sensitivity only; no win-rate inference", checked, changes, errors }, null, 2));
