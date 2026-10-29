import assert from "node:assert/strict";
import test, { type TestContext } from "node:test";
import { mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setImmediate } from "node:timers/promises";
import { PredictionWorker } from "../src/recognition/predictionWorker.js";

interface Prediction { value: string; pid: number }

async function fixture(t: TestContext, body: string, requestTimeoutMs = 1000) {
  const directory = await mkdtemp(join(tmpdir(), "prediction-worker-"));
  const script = join(directory, "worker.cjs");
  await writeFile(script, `
    const { createInterface } = require('node:readline');
    const { existsSync, writeFileSync } = require('node:fs');
    const marker = ${JSON.stringify(join(directory, "started"))};
    const send = message => process.stdout.write(JSON.stringify(message) + '\\n');
    const respond = request => send({id: request.id, predictions: request.images.map(image => ({
      value: Buffer.from(image, 'base64').toString('hex'), pid: process.pid
    }))});
    const lines = createInterface({input: process.stdin});
    ${body}
  `);
  const worker = new PredictionWorker<Prediction>({
    executable: process.execPath, args: [script], name: "Test worker", requestTimeoutMs,
  });
  t.after(async () => {
    worker.close();
    await rm(directory, { recursive: true, force: true });
  });
  return { worker, directory, script };
}

test("prediction worker shares startup and correlates out-of-order responses", async (t) => {
  const { worker } = await fixture(t, `
    console.log('loading model'); console.log('null'); console.log('[]');
    send({id: 999, predictions: []}); send({ready: true});
    let requests = [];
    lines.on('line', line => {
      const request = JSON.parse(line);
      requests.push(request);
      if (requests.length === 2) { respond(requests[1]); respond(requests[0]); }
      else if (requests.length > 2) respond(request);
    });
  `);
  const [left, right] = await Promise.all([
    worker.predict([Buffer.from([0, 255, 128])]), worker.predict([Buffer.from("right")]),
  ]);
  assert.equal(left[0]?.value, "00ff80");
  assert.equal(right[0]?.value, Buffer.from("right").toString("hex"));
  assert.equal(left[0]?.pid, right[0]?.pid);
  const next = await worker.predict([Buffer.from("next")]);
  assert.equal(next[0]?.pid, left[0]?.pid);
});

test("prediction worker retries after a startup crash and retains diagnostics", async (t) => {
  const { worker } = await fixture(t, `
    if (!existsSync(marker)) {
      writeFileSync(marker, '1'); process.stderr.write('could not load model'); process.exit(7);
    }
    send({ready: true}); lines.on('line', line => respond(JSON.parse(line)));
  `);
  await assert.rejects(worker.predict([]), /Test worker exited with code 7: could not load model/);
  const result = await worker.predict([Buffer.from("retry")]);
  assert.equal(result[0]?.value, Buffer.from("retry").toString("hex"));
});

test("prediction worker rejects every outstanding request on exit and restarts", async (t) => {
  const { worker } = await fixture(t, `
    const first = !existsSync(marker); writeFileSync(marker, '1'); send({ready: true});
    let requests = 0;
    lines.on('line', line => {
      if (first) { if (++requests === 2) process.exit(3); }
      else respond(JSON.parse(line));
    });
  `);
  const outcomes = await Promise.allSettled([worker.predict([]), worker.predict([])]);
  for (const outcome of outcomes) {
    assert.equal(outcome.status, "rejected");
    if (outcome.status === "rejected") assert.match(String(outcome.reason), /Test worker exited with code 3/);
  }
  assert.deepEqual(await worker.predict([]), []);
});

test("request errors and late timed-out replies do not corrupt following predictions", async (t) => {
  const { worker } = await fixture(t, `
    send({ready: true}); let delayed;
    lines.on('line', line => {
      const request = JSON.parse(line);
      const value = Buffer.from(request.images[0], 'base64').toString();
      if (value === 'error') return send({id: request.id, error: 'invalid crop'});
      if (value === 'timeout') { delayed = request; return; }
      if (delayed) { respond(delayed); delayed = undefined; }
      respond(request);
    });
  `, 100);
  await assert.rejects(worker.predict([Buffer.from("error")]), /Test worker: invalid crop/);
  await assert.rejects(worker.predict([Buffer.from("timeout")]), /Test worker timed out/);
  const result = await worker.predict([Buffer.from("following")]);
  assert.equal(result[0]?.value, Buffer.from("following").toString("hex"));
});

test("closing during startup settles callers and allows immediate reuse", async (t) => {
  const { worker } = await fixture(t, `
    send({ready: true}); lines.on('line', line => respond(JSON.parse(line)));
  `);
  const closed = assert.rejects(worker.predict([]), /Test worker is unavailable/);
  worker.close();
  const restarted = worker.predict([]);
  await closed;
  assert.deepEqual(await restarted, []);
});

test("closing pending predictions cannot reject a replacement worker's requests", async (t) => {
  const { worker } = await fixture(t, `
    send({ready: true}); lines.on('line', line => {
      const request = JSON.parse(line);
      if (Buffer.from(request.images[0], 'base64').toString() !== 'hold') respond(request);
    });
  `);
  const first = await worker.predict([Buffer.from("first")]);
  const closed = assert.rejects(worker.predict([Buffer.from("hold")]), /Test worker is unavailable/);
  await setImmediate();
  worker.close();
  const restarted = worker.predict([Buffer.from("replacement")]);
  await closed;
  const replacement = await restarted;
  assert.equal(replacement[0]?.value, Buffer.from("replacement").toString("hex"));
  assert.notEqual(replacement[0]?.pid, first[0]?.pid);
});

test("prediction worker retries when a missing executable becomes available", async (t) => {
  const { directory, script } = await fixture(t, `
    send({ready: true}); lines.on('line', line => respond(JSON.parse(line)));
  `);
  const executable = join(directory, "installed-runtime");
  const worker = new PredictionWorker<Prediction>({ executable, args: [script], name: "Test worker" });
  t.after(() => worker.close());
  await assert.rejects(worker.predict([]), /ENOENT/);
  await symlink(process.execPath, executable);
  assert.deepEqual(await worker.predict([]), []);
});
