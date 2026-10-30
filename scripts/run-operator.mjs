import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
import path from "node:path";
import { windowsCaEnvironment } from "./windows-ca.mjs";
import { defaultOperatorLayoutArgs } from "./operator-layout.mjs";
import { explicitOperatorArtifacts, spawnOperatorWithStderr } from "./operator-stderr.mjs";

const root = path.resolve(import.meta.dirname, "..");
const mode = process.argv[2];
const modes = new Set(["observer", "advisor", "auto", "force-auto"]);
if (!modes.has(mode)) {
  console.error("Usage: node scripts/run-operator.mjs <observer|advisor|auto|force-auto> [options]");
  process.exit(2);
}

const python = process.platform === "win32"
  ? path.join(root, ".runtime", "python-auto-venv", "Scripts", "python.exe")
  : path.join(root, ".runtime", "python-auto-venv", "bin", "python");
if (!existsSync(python)) {
  console.error("Python operator environment is missing. Run npm run operator:setup first.");
  process.exit(1);
}

const forwarded = process.argv.slice(3);
const defaults = [
  path.join(root, "python", "auto_operator.py"),
  ...defaultOperatorLayoutArgs(root, forwarded),
  "--templates", path.join(root, "templates", "bootstrap"),
  "--state", path.join(root, "examples", "public-unknown.json"),
  "--mode", mode,
];
if (mode !== "observer") defaults.push("--resume-away");
const actionTemplates = path.join(root, "templates", "actions");
if (existsSync(actionTemplates)) defaults.push("--action-templates", actionTemplates);

const dashboardDisabled = forwarded.includes("--no-dashboard");
const operatorArgs = forwarded.filter((value) => value !== "--no-dashboard");
const artifactsIndex = operatorArgs.findIndex((value) => value === "--artifacts");
const artifactsEquals = operatorArgs.find((value) => value.startsWith("--artifacts="));
const artifacts = artifactsIndex >= 0 && operatorArgs[artifactsIndex + 1]
  ? operatorArgs[artifactsIndex + 1]
  : artifactsEquals?.slice("--artifacts=".length) || "artifacts/python-auto";
const operatorLog = path.resolve(root, artifacts, "python-operator.jsonl");

let references;
for (let index = 0; index < operatorArgs.length; index += 1) {
  if (operatorArgs[index] === "--screen-references") references = operatorArgs[++index];
  else if (operatorArgs[index].startsWith("--screen-references=")) {
    references = operatorArgs[index].slice("--screen-references=".length);
  }
}

let dashboard;
if (!dashboardDisabled) {
  dashboard = spawn(python, [
    path.join(root, "python", "dashboard.py"),
    "--operator-log", operatorLog,
    ...(references ? ["--screen-references", references] : []),
  ], { cwd: root, stdio: "inherit", windowsHide: true });
  dashboard.on("error", (error) => console.error(`Dashboard failed to start: ${error.message}`));
}

const { child: operator } = spawnOperatorWithStderr(python, [...defaults, ...operatorArgs], {
  cwd: root, env: windowsCaEnvironment(root),
}, explicitOperatorArtifacts(root, operatorArgs));
const stopChildren = (signal) => {
  if (!operator.killed) operator.kill(signal);
  if (dashboard && !dashboard.killed) dashboard.kill(signal);
};
process.once("SIGINT", () => stopChildren("SIGINT"));
process.once("SIGTERM", () => stopChildren("SIGTERM"));
operator.on("error", (error) => {
  stopChildren("SIGTERM");
  throw error;
});
operator.on("exit", (code, signal) => {
  if (dashboard && !dashboard.killed) dashboard.kill("SIGTERM");
  process.exitCode = code ?? (signal ? 1 : 0);
});
