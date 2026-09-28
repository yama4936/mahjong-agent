import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

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
