import { existsSync, readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");

function latestLiveLayout() {
  const directory = path.join(root, "artifacts", "live");
  if (!existsSync(directory)) return path.join(root, "config", "layout.json");
  const layouts = readdirSync(directory)
    .filter((name) => name.endsWith(".layout.json"))
    .sort()
    .reverse();
  return layouts[0] ? path.join(directory, layouts[0]) : path.join(root, "config", "layout.json");
}

const python = process.platform === "win32"
  ? path.join(root, ".runtime", "python-auto-venv", "Scripts", "python.exe")
  : path.join(root, ".runtime", "python-auto-venv", "bin", "python");

if (!existsSync(python)) {
  console.error("Python operator environment is missing. Run ./scripts/setup-python-operator.sh first.");
  process.exit(1);
}

const defaults = [
  path.join(root, "python", "auto_operator.py"),
  "--layout", latestLiveLayout(),
  "--templates", path.join(root, "templates", "bootstrap"),
  "--state", path.join(root, "examples", "public-unknown.json"),
  "--mode", "force-auto",
  "--resume-away",
];

const actionTemplates = path.join(root, "templates", "actions");
if (existsSync(actionTemplates)) defaults.push("--action-templates", actionTemplates);

const result = spawnSync(python, [...defaults, ...process.argv.slice(2)], {
  cwd: root,
  stdio: "inherit",
});

if (result.error) throw result.error;
process.exit(result.status ?? 1);
