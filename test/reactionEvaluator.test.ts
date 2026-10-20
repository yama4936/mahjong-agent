import test from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdtemp, writeFile, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const exec = promisify(execFile);
test("reaction entrypoint preserves CLI policy and copy validation, including compact hands", { timeout: 60_000 }, async () => {
  const dir = await mkdtemp(join(tmpdir(), "reaction-evaluation-"));
  const state = { round: "east_1", seat: "west", scores: { east: 25000, south: 25000, west: 25000, north: 25000 },
    honba: 0, riichiSticks: 0, remainingTiles: 50, phase: "self_turn", openMelds: 0 };
  const observation = { doraIndicators: [], ownDiscards: ["9m"], ownMelds: [],
    opponentDiscards: [{ seat: "east", discards: ["E"] }] };
  const recognition = { tiles: ["E", "E", "1m", "2m", "3m", "4m", "5m", "6m", "1p", "2p", "3p", "9s", "9s"],
    confidence: 0.9, ambiguityMargin: 0.1, safe: false };
  const paths = ["state", "observation", "recognition"].map(name => join(dir, name + ".json"));
  const env = { ...process.env, TYPESAFE_API_KEY: "", JEV_FORCE_AUTO_DEADLINE_MS: "1" };
  const write = async (obs = observation, rec = recognition) => {
    await Promise.all([state, obs, rec].map((value, i) => writeFile(paths[i]!, JSON.stringify(value))));
  };
  const run = async (legacy = false, entry = "src/recognition/reactionEvaluator.ts") => {
    const args = legacy ? ["src/cli.ts", "evaluate-frame", "unused.png", "config/layout.json", "templates/bootstrap",
      `--state=${paths[0]}`, `--public-observation=${paths[1]}`, `--recognition-file=${paths[2]}`,
      "--pending-discard=E,east", "--available-ui-actions=pon,pass", "--mode=force-auto"]
      : [entry, ...paths, "E", "east", "pon,pass"];
    const { stdout } = await exec(process.execPath, ["--import", "tsx", ...args], { env });
    return JSON.parse(stdout);
  };
  try {
    await write();
    const [legacy, current] = await Promise.all([run(true), run()]);
    assert.equal(current.status, "decision");
    assert.deepEqual(current.state, legacy.state);
    assert.deepEqual(current.decision.selectedAction, legacy.decision.selectedAction);
    assert.deepEqual(current.decision.legalActions, legacy.decision.legalActions);
    assert.ok(current.decision.legalActions.some((action: { action: string }) => action.action === "pon"));
    if (process.platform !== "win32") {
      const linkedEntry = join(dir, "reaction-entry.ts");
      await symlink(join(process.cwd(), "src/recognition/reactionEvaluator.ts"), linkedEntry);
      // Previously exited0 with empty stdout, causing Python JSON decoding
      // to stop every live reaction in a symlinked frozen checkout.
      const linked = await run(false, linkedEntry);
      assert.deepEqual(linked.state, current.state);
      assert.deepEqual(linked.decision.selectedAction, current.decision.selectedAction);
      await assert.rejects(exec(process.execPath, ["--import", "tsx", linkedEntry], { env }), /Usage: reactionEvaluator/);
    }
    await write({ ...observation, ownDiscards: ["E", "E"] });
    await assert.rejects(run(), /More than four copies of E/);
    await assert.rejects(run(true), /More than four copies of E/);
    const compact = { ...observation, ownMelds: [{ type: "pon", tiles: ["F", "F", "F"] }] };
    await write(compact as any, { ...recognition, tiles: recognition.tiles.filter(tile => !["4m", "5m", "6m"].includes(tile)) });
    const opened = await run();
    assert.equal(opened.state.hand.length, 10);
    assert.equal(opened.state.openMelds, 1);
    assert.ok(opened.decision.legalActions.some((action: { action: string }) => action.action === "pon"));
    await write(compact as any);
    assert.equal((await run()).status, "not_ready");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
