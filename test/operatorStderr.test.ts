import assert from "node:assert/strict";
import test from "node:test";
import * as fs from "node:fs";
import { spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import { tmpdir } from "node:os";
import path from "node:path";
// @ts-ignore Local launcher modules are JavaScript.
import { explicitOperatorArtifacts, spawnOperatorWithStderr } from "../scripts/operator-stderr.mjs";
// @ts-ignore Local launcher modules are JavaScript.
import { operatorLifecycleDirectory, recordOperatorLifecycle } from "../scripts/operator-lifecycle.mjs";

test("only explicit artifacts flags select the canonical stderr sink, with argparse last-option precedence", () => {
  assert.equal(explicitOperatorArtifacts("/work", []), undefined);
  assert.equal(explicitOperatorArtifacts("/work", ["--artifacts", "evidence"]), "/work/evidence");
  assert.equal(explicitOperatorArtifacts("/work", ["--artifacts=evidence"]), "/work/evidence");
  assert.equal(explicitOperatorArtifacts("/work", ["--artifacts", "one", "--artifacts=two"]), "/work/two");
  assert.equal(explicitOperatorArtifacts("/work", ["--artifacts"]), undefined);
  assert.equal(explicitOperatorArtifacts("/work", ["--artifacts", "--ranked-loop"]), undefined);
});

test("lifecycle records use the explicit artifact directory and preserve append-only signal evidence", (context) => {
  const root = fs.mkdtempSync(path.join(tmpdir(), "operator-lifecycle-root-"));
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const directory = operatorLifecycleDirectory(root, path.join(root, "evidence"));
  assert.equal(directory, path.join(root, "evidence"));
  recordOperatorLifecycle(directory, "launcher_started", { launcherPid: 1, operatorPid: 2 });
  recordOperatorLifecycle(directory, "launcher_signal_received", { launcherPid: 1, signal: "SIGHUP" });
  const records = fs.readFileSync(path.join(directory, "operator-lifecycle.jsonl"), "utf8")
    .trim().split("\n").map((line: string) => JSON.parse(line));
  assert.deepEqual(records.map((record: any) => record.event), ["launcher_started", "launcher_signal_received"]);
  assert.equal(records[1].signal, "SIGHUP");
  assert.equal(operatorLifecycleDirectory(root, undefined), path.join(root, "artifacts/python-auto"));
});

test("default inheritance, environment and child exit remain unchanged", () => {
  const child = new EventEmitter();
  let received: any;
  const result = spawnOperatorWithStderr("python", ["operator.py"], { cwd: "/work", env: { SAMPLE: "ok" } }, undefined,
    { fs, spawn: (...args: any[]) => { received = args; return child; } });
  assert.equal(result.child, child);
  assert.equal(result.stderrPath, undefined);
  assert.deepEqual(received, ["python", ["operator.py"], { cwd: "/work", env: { SAMPLE: "ok" }, stdio: "inherit" }]);
  let exit: any;
  result.child.on("exit", (code: number, signal: string) => { exit = [code, signal]; });
  child.emit("exit", 17, null);
  assert.deepEqual(exit, [17, null]);
});

test("explicit sink is secure append-only, passed directly as stderr FD and parent FD closes", (context) => {
  const directory = fs.mkdtempSync(path.join(tmpdir(), "operator-stderr-test-"));
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const target = path.join(directory, "operator-stderr.log");
  fs.writeFileSync(target, "earlier\n", { mode: 0o644 });
  let fd: number = -1;
  const child = new EventEmitter();
  const result = spawnOperatorWithStderr("python", [], { cwd: directory }, directory,
    { fs, spawn: (_command: any, _args: any, options: any) => {
      assert.deepEqual(options.stdio.slice(0, 2), ["inherit", "inherit"]);
      fd = options.stdio[2];
      fs.writeSync(fd, "child traceback\n");
      return child;
    } });
  assert.equal(result.child, child);
  assert.equal(result.stderrPath, target);
  assert.equal(fs.readFileSync(target, "utf8"), "earlier\nchild traceback\n");
  if (process.platform !== "win32") assert.equal(fs.statSync(target).mode & 0o777, 0o600);
  assert.throws(() => fs.fstatSync(fd), { code: "EBADF" });
});

test("a real child writes stderr after parent FD closes and preserves its nonzero exit", async (context) => {
  const directory = fs.mkdtempSync(path.join(tmpdir(), "operator-stderr-child-"));
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const result = spawnOperatorWithStderr(process.execPath,
    ["-e", "process.stderr.write('primary failure\\n');process.exitCode=7"], {}, directory);
  const code = await new Promise(resolve => result.child.once("exit", resolve));
  assert.equal(code, 7);
  assert.equal(fs.readFileSync(result.stderrPath, "utf8"), "primary failure\n");
});

test("spawn and permission failures surface and still close the parent FD", (context) => {
  const directory = fs.mkdtempSync(path.join(tmpdir(), "operator-stderr-failure-"));
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  let opened: number = -1;
  const injectedFs = { ...fs, openSync: (...args: any[]) => { opened = (fs.openSync as any)(...args); return opened; } };
  const failure = new Error("spawn failed");
  assert.throws(() => spawnOperatorWithStderr("python", [], {}, directory,
    { fs: injectedFs, spawn: () => { throw failure; } }), error => error === failure);
  assert.throws(() => fs.fstatSync(opened), { code: "EBADF" });
  const denial = Object.assign(new Error("chmod failed"), { code: "EPERM" });
  assert.throws(() => spawnOperatorWithStderr("python", [], {}, directory,
    { fs: { ...injectedFs, fchmodSync: () => { throw denial; } }, spawn }), error => error === denial);
  assert.throws(() => fs.fstatSync(opened), { code: "EBADF" });
});

test("symlink sink is not followed or chmodded", { skip: process.platform === "win32" }, (context) => {
  const directory = fs.mkdtempSync(path.join(tmpdir(), "operator-stderr-symlink-"));
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const target = path.join(directory, "untouched.txt");
  fs.writeFileSync(target, "keep", { mode: 0o644 });
  fs.symlinkSync(target, path.join(directory, "operator-stderr.log"));
  assert.throws(() => spawnOperatorWithStderr("python", [], {}, directory), { code: "ELOOP" });
  assert.equal(fs.readFileSync(target, "utf8"), "keep");
  assert.equal(fs.statSync(target).mode & 0o777, 0o644);
});
