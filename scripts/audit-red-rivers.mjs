import fs from "node:fs";
import { parseGameState } from "../dist/src/game/state.js";
import { normalizeTile } from "../dist/src/game/tiles.js";
import { deterministicAdvice } from "../dist/src/evaluation/advisor.js";

// Read-only counterfactual: preserve hand/dora/melds and normalize only opponent
// river tile identities. This exercises both genbutsu and suji lookups, and is
// not evidence of changed Jev selections or improved match outcomes.
const files = process.argv.slice(2);
if (!files.length) throw new Error("Usage: node scripts/audit-red-rivers.mjs <python-operator.jsonl> [...]");
for (const file of files) {
  const rows = fs.readFileSync(file, "utf8").trim().split(/\r?\n/).filter(Boolean).map(JSON.parse);
  let checked = 0, dangerAffected = 0;
  const changes = [], errors = [];
  for (const row of rows.filter(row => row.event === "decision")) {
    try {
      const state = row.evaluation.state;
      const corrected = { ...state, opponents: state.opponents.map(opponent => ({
        ...opponent, discards: opponent.discards.map(normalizeTile),
      })) };
      const before = deterministicAdvice(parseGameState(state));
      const after = deterministicAdvice(parseGameState(corrected));
      checked++;
      if (before.candidates.some(candidate => candidate.danger !==
          after.candidates.find(other => other.tile === candidate.tile)?.danger)) dangerAffected++;
      if (before.tile !== after.tile) changes.push({
        timestamp: row.timestamp, before: before.tile, normalizedRiver: after.tile,
      });
    } catch (error) { errors.push({ timestamp: row.timestamp, error: String(error) }); }
  }
  console.log(JSON.stringify({ file, scope: "local sensitivity; genbutsu and suji together; no win-rate inference",
    checked, dangerAffected, changes, errors }, null, 2));
}
