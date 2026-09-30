import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { mkdtemp, readFile, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

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

test("resident force-auto evaluation preserves complete own pon and rejects mismatched counts", { timeout: 60_000 }, async () => {
  const directory = await mkdtemp(join(tmpdir(), "resident-own-meld-"));
  // This tests the resident request/state pipeline with the normal
  // calibration; a confirmed open meld selects its compact-row rectangles.
  const layout = JSON.parse(await readFile("config/layout.json", "utf8"));
  const layoutPath = join(directory, "layout.json");
  await writeFile(layoutPath, JSON.stringify(layout));
  const child = spawn(process.execPath, ["--import", "tsx", "src/recognition/recognitionServer.ts",
    layoutPath, "templates/bootstrap", "examples/public-unknown.json"], {
    stdio: ["pipe", "pipe", "pipe"], env: { ...process.env, TYPESAFE_API_KEY: "" },
  });
  const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  const read = async () => JSON.parse((await lines.next()).value!);
  try {
    assert.equal((await read()).ready, true);
    const observation = {
      capturedAt: new Date().toISOString(), recognizedAt: new Date().toISOString(), recognitionLatencyMs: 0,
      configuredRegions: ["ownMelds"], doraIndicators: [], ownDiscards: [], opponentDiscards: [],
      ownMeldTiles: ["F", "F", "F"], ownMelds: [{ type: "pon", tiles: ["F", "F", "F"], confidence: 0.98 }],
      acceptedTiles: 3, detectedCandidates: 3, complete: false,
    };
    for (const [id, ownMelds] of [[1, observation.ownMelds], [2, []]] as const) {
      child.stdin.write(JSON.stringify({ id, screenshot: "artifacts/live/cached-hand-drift-20260928.jpg",
        evaluateForceAuto: true, openMelds: 1, publicObservation: { ...observation, ownMelds } }) + "\n");
      const response = await read();
      assert.equal(response.error, undefined);
      const result = response.result;
      assert.equal(result.concealedCount, 11);
      assert.equal(result.publicCache.applied, true);
      assert.equal(result.publicCache.rejectedTiles, 0);
      assert.equal(result.state.openMelds, 1);
      assert.deepEqual(result.state.melds, id === 1 ? [{ type: "pon", tiles: ["F", "F", "F"] }] : []);
      assert.deepEqual(result.state.visibleTiles, id === 1 ? [] : ["F", "F", "F"]);
      assert.ok(result.decision);
    }
  } finally {
    child.stdin.end();
    child.kill();
    await rm(directory, { recursive: true, force: true });
  }
});
