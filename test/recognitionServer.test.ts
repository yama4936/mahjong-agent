import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

test("resident server rejects cached decision hands and recognizes the physical row", { timeout: 60_000 }, async () => {
  const child = spawn(process.execPath, ["--import", "tsx", "src/recognition/recognitionServer.ts",
    "config/layout.json", "templates/bootstrap", "examples/public-unknown.json"], {
    stdio: ["pipe", "pipe", "pipe"], env: { ...process.env, TYPESAFE_API_KEY: "" },
  });
  const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  const read = async () => JSON.parse((await lines.next()).value!);
  try {
    assert.equal((await read()).ready, true);
    child.stdin.write(JSON.stringify({ id: 1, screenshot: "unused.png", evaluateForceAuto: true,
      drawOnly: true, concealedTiles: ["2s"] }) + "\n");
    assert.match((await read()).error, /fresh recognition of the entire physical hand row/);
    child.stdin.write(JSON.stringify({ id: 2, screenshot: "artifacts/live/cached-hand-drift-20260928.jpg" }) + "\n");
    const response = await read();
    assert.equal(response.id, 2);
    assert.deepEqual(response.result.tiles, ["4m", "0m", "6m", "6m", "7m", "9m",
      "4p", "6p", "7p", "8p", "9p", "7s", "C", "6p"]);
  } finally {
    child.stdin.end();
    child.kill();
  }
});
