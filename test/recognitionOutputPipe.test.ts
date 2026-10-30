import assert from "node:assert/strict";
import { once } from "node:events";
import { spawn } from "node:child_process";
import test from "node:test";

test("resident recognition output exits cleanly when its parent closes stdout", { timeout: 10_000 }, async () => {
  const child = spawn(process.execPath, ["--import", "tsx", "--input-type=module", "-e", `
    import { exitWhenOutputPipeBreaks } from "./src/recognition/outputPipe.ts";
    exitWhenOutputPipeBreaks();
    process.stdout.write("ready\\n");
    setTimeout(() => process.stdout.write("late response\\n"), 30);
    setInterval(() => {}, 1_000);
  `], { cwd: process.cwd(), stdio: ["ignore", "pipe", "pipe"] });
  let stderr = "";
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", chunk => { stderr += chunk; });
  await once(child.stdout, "data");
  child.stdout.destroy();
  const [code, signal] = await once(child, "exit") as [number | null, NodeJS.Signals | null];
  assert.equal(signal, null);
  assert.equal(code, 0);
  assert.doesNotMatch(stderr, /write EPIPE/);
});
