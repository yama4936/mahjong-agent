import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";

test("stopped chi frame reacquires public rivers and reaches reaction evaluation", {
  skip: !existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar") || !existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt"),
}, async () => {
  const directory = await mkdtemp(join(tmpdir(), "reaction-reacquire-"));
  const frame = "artifacts/live/left-river-three-man-border-20260928.png";
  try {
    const observation = spawnSync(process.execPath, ["--import", "tsx", "src/cli.ts", "public-observation",
      frame, "config/layout-300-regression.json", "templates/bootstrap", "--seat=north",
      "--backend=hybrid", "--reaction-highlight"], { encoding: "utf8", timeout: 20000 });
    assert.equal(observation.status, 0, observation.stderr);
    const board = JSON.parse(observation.stdout);
    assert.deepEqual(board.highlightedDiscard, { tile: "8s", fromSeat: "west" });
    assert.equal(board.opponentDiscards.find((opponent: any) => opponent.seat === "south").discards.length, 18);
    assert.equal(board.opponentDiscards.find((opponent: any) => opponent.seat === "west").discards[13], "3m");
    const statePath = join(directory, "state.json");
    const observationPath = join(directory, "public.json");
    const recognitionPath = join(directory, "recognition.json");
    await writeFile(statePath, JSON.stringify({ seat: "north", round: "south_2", turn: 0,
      honba: 0, riichiSticks: 1, remainingTiles: 1,
      opponents: [{ seat: "west", discards: [], riichi: true, openMelds: 0 }],
      scores: { north: 55600, east: 18700, south: 9700, west: 15000 } }));
    await writeFile(observationPath, observation.stdout);
    // Preserve the original unsafe hand recognition: this test is not click authorization.
    await writeFile(recognitionPath, JSON.stringify({ tiles: ["2p", "6p", "7p", "8p", "1s",
      "2s", "3s", "3s", "3s", "4s", "6s", "7s", "N"],
      safe: false, confidence: 0.8735332695481259, ambiguityMargin: 0.1948253512445206 }));
    const result = spawnSync(process.execPath, ["--import", "tsx", "src/cli.ts", "evaluate-frame",
      frame, "config/layout-300-regression.json", "templates/bootstrap", `--state=${statePath}`,
      `--public-observation=${observationPath}`, `--recognition-file=${recognitionPath}`,
      "--pending-discard=8s,west", "--available-ui-actions=chi,pass", "--mode=force-auto"],
      { encoding: "utf8", timeout: 15000, env: { ...process.env, TYPESAFE_API_KEY: "" } });
    assert.equal(result.status, 0, result.stderr);
    const output = JSON.parse(result.stdout);
    assert.equal(output.state.phase, "reaction");
    assert.equal(output.state.turn, 16);
    assert.equal(output.state.opponents.find((opponent: any) => opponent.seat === "west").riichi, true);
    assert.ok(output.decision);
    assert.equal(output.decision.handPlan.phase, "late_tenpai_defense");
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("reaction CLI refreshes strategy phase from observed river rather than stale turn", async () => {
  const directory = await mkdtemp(join(tmpdir(), "reaction-turn-"));
  try {
    const statePath = join(directory, "state.json");
    const observationPath = join(directory, "public.json");
    const recognitionPath = join(directory, "recognition.json");
    await writeFile(statePath, JSON.stringify({ seat: "east", round: "south_1", turn: 0,
      scores: { east: 55600, south: 18700, west: 10700, north: 15000 } }));
    await writeFile(recognitionPath, JSON.stringify({ tiles: ["7m", "8m", "8m", "2p", "2p",
      "6p", "7p", "8p", "3s", "4s", "0s", "6s", "8s"],
      safe: true, confidence: 1, ambiguityMargin: 1 }));
    for (const [count, phase] of [[0, "early_efficiency"], [8, "middle_balance"],
                                 [12, "late_tenpai_defense"]] as const) {
      await writeFile(observationPath, JSON.stringify({ doraIndicators: [], ownMelds: [],
        ownDiscards: ["E", "E", "E", "E", "S", "S", "S", "S", "W", "W", "W", "W"].slice(0, count),
        opponentDiscards: [] }));
      const result = spawnSync(process.execPath, ["--import", "tsx", "src/cli.ts", "evaluate-frame",
        "artifacts/live/opposite-eight-man-pon-pending-missed-20260928.png",
        "config/layout-300-regression.json", "templates/bootstrap", `--state=${statePath}`,
        `--public-observation=${observationPath}`, `--recognition-file=${recognitionPath}`,
        "--pending-discard=8m,west", "--available-ui-actions=pon,pass", "--mode=force-auto"],
        { encoding: "utf8", timeout: 15000, env: { ...process.env, TYPESAFE_API_KEY: "" } });
      assert.equal(result.status, 0, result.stderr);
      const output = JSON.parse(result.stdout);
      assert.equal(output.state.phase, "reaction");
      assert.equal(output.state.turn, count);
      assert.equal(output.decision.handPlan.phase, phase);
    }
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
