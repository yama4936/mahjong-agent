import assert from "node:assert/strict";
import test from "node:test";
import { parseGameState } from "../src/game/state.js";
import { evaluateDiscards } from "../src/game/ukeire.js";
import { knownTilesOutsideHand } from "../src/game/state.js";
import { discardTacticalContext } from "../src/jev/discardContext.js";
import { buildJevRequest } from "../src/jev/client.js";

test("explicit bonus losses distinguish red and normal fives with repeated indicators", () => {
  const state = parseGameState({
    hand: ["1m", "2m", "3m", "4m", "0m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"],
    draw: "5m", doraIndicators: ["4m", "4m"],
  });
  const candidates = evaluateDiscards([...state.hand, state.draw!], knownTilesOutsideHand(state));
  const original = JSON.stringify(state);
  const context = discardTacticalContext(state, candidates);
  assert.deepEqual(context.criteria.get("discard_0m")!.lost_bonus, { indicator_dora: 2, red_dora: 1 });
  assert.deepEqual(context.criteria.get("discard_5m")!.lost_bonus, { indicator_dora: 2, red_dora: 0 });
  assert.deepEqual(context.criteria.get("discard_5m")!.retained_bonus, { indicator_dora: 2, red_dora: 1 });
  assert.deepEqual(context.criteria.get("discard_0m")!.retained_bonus, { indicator_dora: 2, red_dora: 0 });
  assert.equal(JSON.stringify(state), original);
});

test("discard furiten includes an exhausted wait even when another wait remains live", () => {
  const state = parseGameState({
    hand: ["1m", "2m", "3m", "4m", "5m", "6m", "7p", "8p", "9p", "2s", "3s", "E", "E"],
    draw: "N", ownDiscards: ["1s"], visibleTiles: ["1s", "1s", "1s"],
  });
  const candidates = evaluateDiscards([...state.hand, state.draw!], knownTilesOutsideHand(state));
  assert.deepEqual(candidates.find(candidate => candidate.tile === "N")!.effectiveTiles, [{ tile: "4s", remaining: 4 }]);
  const context = discardTacticalContext(state, candidates);
  const tenpai = context.criteria.get("discard_N")!;
  assert.deepEqual(tenpai.structural_waits, [{ tile: "1s", remaining: 0 }, { tile: "4s", remaining: 4 }]);
  assert.equal(tenpai.discard_furiten, true);
  assert.deepEqual(tenpai.discard_furiten_waits, ["1s"]);
  assert.equal(tenpai.temporary_or_riichi_pass_furiten, "not_observed");
  assert.equal(tenpai.live_structural_wait_copies, 4);
  assert.equal(context.criteria.get("discard_1m")!.breaks_available_tenpai, true);
});

test("missing indicators remain unknown, while red bonus is observable", () => {
  const state = parseGameState({
    hand: ["1m", "2m", "3m", "4m", "0m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"], draw: "N",
  });
  const candidates = evaluateDiscards([...state.hand, state.draw!]);
  const context = discardTacticalContext(state, candidates);
  assert.equal(context.summary.dora_tiles_from_indicators, "unknown");
  assert.deepEqual(context.criteria.get("discard_0m")!.lost_bonus, { indicator_dora: "unknown", red_dora: 1 });
  for (const profile of ["balanced-v2", "hierarchical-v3"] as const) {
    const request = buildJevRequest(state, candidates, "test", profile);
    assert.deepEqual(request.state.tactical_summary, context.summary);
    const criterion = request.questions.action.criteria.discard_0m as Record<string, unknown>;
    assert.deepEqual(criterion.tactical_facts, context.criteria.get("discard_0m"));
    assert.match(JSON.stringify(request.questions.action.instructions), /Dora are bonuses|Dora are bonuses/i);
    assert.match(JSON.stringify(request.questions.action.instructions), /furiten/i);
  }
});

test("retained bonus includes physical meld tiles and indicator wraparound", () => {
  const state = parseGameState({ hand: ["1m", "2m", "3m", "7p", "8p", "9p", "2s", "3s", "E", "E"],
    draw: "N", openMelds: 1, melds: [{ type: "chi", tiles: ["4m", "0m", "6m"] }],
    doraIndicators: ["4m", "N", "C"],
  });
  const candidates = evaluateDiscards([...state.hand, state.draw!], knownTilesOutsideHand(state), 1);
  const context = discardTacticalContext(state, candidates);
  assert.deepEqual(context.summary.dora_tiles_from_indicators, ["5m", "E", "P"]);
  assert.deepEqual(context.criteria.get("discard_N")!.retained_bonus, { indicator_dora: 3, red_dora: 1 });
  assert.equal(context.summary.own_meld_tile_evidence_complete, true);
});
