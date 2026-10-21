import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { isAllLastRound, parseGameState, parsePublicGameState } from "../src/game/state.js";
import { deterministicAdvice } from "../src/evaluation/advisor.js";
import { buildJevDeclarationRequest, buildJevReactionRequest, buildJevRequest } from "../src/jev/client.js";
import type { ClosedWaitReport } from "../src/evaluation/closedWaitScorer.js";

test("explicit match length distinguishes scheduled final hands and extensions", () => {
  for (const [matchLength, round, expected] of [
    ["east", "east_3", false], ["east", "east_4", true], ["east", "south_1", true],
    ["south", "east_4", false], ["south", "south_3", false], ["south", "south_4", true],
    ["south", "west_1", true], ["east", "unknown", false],
    [undefined, "east_4", false], [undefined, "south_4", true],
  ] as const) {
    const state = parsePublicGameState({ round, match_length: matchLength });
    assert.equal(isAllLastRound(state), expected, `${matchLength}/${round}`);
  }
});

test("verified format reaches discard, reaction and declaration model context", async () => {
  const fixture = JSON.parse(await readFile("test/fixtures/east-only-final-round-20261021.json", "utf8"));
  for (const matchLength of ["east", "south", undefined] as const) {
    const live = parseGameState({ ...fixture.state, matchLength });
    const tile = live.hand[0]!;
    const report: ClosedWaitReport = { library: "mahjong==2.0.0", discard: tile,
      scope: "closed_hand_scoring_not_policy_ev", assumptions: { furiten_not_checked: true }, rows: [] };
    const requests = [
      buildJevRequest(live, deterministicAdvice(live).candidates, "test", "hierarchical-v3"),
      buildJevReactionRequest({ ...live, pendingDiscard: { tile, fromSeat: "east" } }, [{ id: "pass", action: "pass" }], "test"),
      buildJevDeclarationRequest(live, [
        { id: `discard_${tile}`, action: "discard", tile },
        { id: `riichi_discard_${tile}`, action: "riichi", tile },
      ], report, "test"),
    ];
    for (const request of requests) {
      assert.equal(request.state.round, "east_4");
      assert.equal(request.state.matchLength, matchLength);
      assert.equal(request.state.allLast, matchLength === undefined ? undefined : matchLength === "east");
    }
  }
});
