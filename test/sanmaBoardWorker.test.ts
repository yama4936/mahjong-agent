import test from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { createHash } from "node:crypto";
import { SanmaBoardWorker } from "../src/recognition/sanmaBoardWorker.js";
const run = promisify(execFile);
const frame = "artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-05-55-331Z-before.png";
const python = ".runtime/python-auto-venv/bin/python";
const available = existsSync(frame) && existsSync(python);
function withoutSource(data: any) { const copy = structuredClone(data); delete copy.board.source; delete copy.frame_sha256; return copy; }

test("resident board probe matches isolated OCR on sanma and four-player images and restarts", {skip: !available}, async () => {
  const worker = new SanmaBoardWorker();
  try {
    for (const file of [frame, frame, "test/fixtures/board-cache-score-25400-20261020.jpg"]) {
      const bytes = await readFile(file);
      const original = JSON.parse((await run(python, ["python/sanma_board_image.py", file, "--with-north"], {timeout:30_000})).stdout);
      const resident = await worker.observe(bytes) as any;
      assert.equal(resident.frame_sha256, createHash("sha256").update(bytes).digest("hex"));
      assert.deepEqual(withoutSource(resident), withoutSource(original));
      assert.equal(resident.board.verified, false);
      assert.equal(resident.north.status, "unknown");
      assert.equal(resident.north.complete, false);
    }
    worker.close();
    const afterRestart = await worker.observe(await readFile(frame)) as any;
    assert.equal(afterRestart.board.verified, false);
    assert.equal(afterRestart.north.status, "unknown");
  } finally { worker.close(); }
});

test("real sanma frame retains the OCR wall count only as an unverified candidate", {skip: !available}, async () => {
  const worker = new SanmaBoardWorker();
  try {
    const image = "artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-21-44-430Z-before.png";
    const data = await worker.observe(await readFile(image)) as any;
    assert.equal(data.board.candidate.remainingTiles, 48);
    assert.equal(data.board.verified, false);
    assert.equal(data.north.status, "unknown");
    assert.equal(data.north.complete, false);
  } finally { worker.close(); }
});

test("resident recognition server returns separate unchanged safe candidate snapshots", {skip: !available, timeout: 60_000}, async () => {
  const { spawn } = await import("node:child_process");
  const { createInterface } = await import("node:readline");
  const child = spawn(process.execPath, ["--import", "tsx", "src/recognition/recognitionServer.ts",
    "config/layout-runtime.json", "templates/bootstrap"], { stdio: ["pipe", "pipe", "pipe"] });
  const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  const read = async () => JSON.parse((await lines.next()).value!);
  try {
    assert.equal((await read()).ready, true);
    for (const [id, screenshot] of [[1, frame], [2, "test/fixtures/board-cache-score-25400-20261020.jpg"]] as const) {
      child.stdin.write(`${JSON.stringify({id, screenshot, observeSanma:true})}\n`);
      const reply = await read();
      assert.equal(reply.id, id);
      assert.equal(reply.error, undefined);
      assert.equal(reply.result.digest, createHash("sha256").update(await readFile(screenshot)).digest("hex"));
      assert.equal(reply.result.north.status, "unknown");
      assert.equal(reply.result.north.complete, false);
      assert.equal(reply.result.operationAuthorized, false);
      if (id === 2) assert.equal(reply.result.ownSeat.status, "unknown");
    }
  } finally { child.stdin.end(); await new Promise<void>(resolve => child.once("exit", () => resolve())); }
});

test("worker errors and wrong digest leave the board and action state unknown", {skip: !available, timeout: 30_000}, async () => {
  const { observeSanmaFrameAutomatically } = await import("../src/recognition/sanmaAutoFrameObservation.js");
  const { layoutSchema } = await import("../src/recognition/layout.js");
  const { EXPERIMENTAL_BUTTONS } = await import("../src/recognition/sanmaButtonExperiment.js");
  const sharp = (await import("sharp")).default;
  const layout = layoutSchema.parse(JSON.parse(await readFile("config/layout-runtime.json", "utf8")));
  const buttonTemplates = Object.fromEntries(await Promise.all(EXPERIMENTAL_BUTTONS.map(async name =>
    [name, await readFile(`test/fixtures/sanma-buttons/${name}.png`)]))) as any;
  const row = await readFile("test/fixtures/sanma-button-rows/kita.png");
  const buttonRowReferences = {skip: await sharp(row).extract({left:580,top:0,width:245,height:90}).png().toBuffer(),
    emptyRow: await readFile("test/fixtures/sanma-button-rows/empty.png")};
  const blank = await sharp({create:{width:1920,height:1080,channels:3,background:"black"}}).png().toBuffer();
  const publicClassifier = { async classifyTileImages() { throw new Error("unexpected public inference"); } };
  for (const boardObserver of [
    {async observe() { throw new Error("worker stopped"); }},
    {async observe() { return {frame_sha256:"wrong",board:{verified:false,candidate:{seat:"east"}},north:{status:"unknown",verified:false,complete:false}}; }},
  ]) {
    const result = await observeSanmaFrameAutomatically({frame:blank,layout,templates:"templates/bootstrap",
      buttonTemplates,buttonRowReferences,publicClassifier,boardObserver});
    assert.equal(result.ownSeat.status, "unknown");
    assert.equal(result.north.status, "unknown");
    assert.equal(result.north.complete, false);
    assert.equal(result.north.bySeat, undefined);
    assert.equal(result.candidates.status, "unresolved");
    assert.deepEqual(result.candidates.candidates, []);
    assert.equal(result.operationAuthorized, false);
  }
});
