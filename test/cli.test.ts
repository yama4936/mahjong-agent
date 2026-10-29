import assert from "node:assert/strict";
import test from "node:test";
import { spawnSync } from "node:child_process";
import { runCli } from "../src/cli/router.js";

test("CLI routes existing commands and aliases to their argument validation", async () => {
  for (const command of [
    "advise", "jev-tune", "recognize", "evaluate-frame", "verify-discard-frame", "detect-regions",
    "recognize-regions", "public-observation", "recognize-center", "recognize-actions", "propose-hand-layout",
    "analyze-screenshot", "replay", "attach-result", "benchmark", "policy-compare", "collect-templates",
    "validate-templates", "certify-layout", "turn", "watch",
  ]) {
    await assert.rejects(runCli([command]), /^Error: Usage:/, command);
  }
  for (const command of ["watch-hand-layout", "live-advisor"]) {
    await assert.rejects(runCli([command, "--poll=0", "--poll=100"]), /--poll must be at least 100ms/);
  }
  await assert.rejects(runCli([]), /^Error: Commands:/);
  await assert.rejects(runCli(["toString"]), /^Error: Commands:/);
  await assert.rejects(runCli(["unknown"]), /^Error: Commands:/);
});

test("CLI entry point preserves JSON output and nonzero error exits", () => {
  const advise = spawnSync(process.execPath, ["--import", "tsx", "src/cli.ts", "advise", "examples/state.json"], {
    encoding: "utf8", timeout: 10000,
  });
  assert.equal(advise.status, 0, advise.stderr);
  assert.ok(JSON.parse(advise.stdout).candidates.length > 0);
  assert.equal(advise.stderr, "");
  const smoke = spawnSync(process.execPath, ["--import", "tsx", "src/cli.ts", "jev-smoke"], {
    encoding: "utf8", timeout: 10000, env: { ...process.env, TYPESAFE_API_KEY: "" },
  });
  assert.equal(smoke.status, 1);
  assert.equal(smoke.stdout, "");
  assert.equal(smoke.stderr.trim(), "TYPESAFE_API_KEY is required");
});
