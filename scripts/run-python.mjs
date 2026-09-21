import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const python = process.platform === "win32"
  ? path.join(root, ".runtime", "python-auto-venv", "Scripts", "python.exe")
  : path.join(root, ".runtime", "python-auto-venv", "bin", "python");

if (!existsSync(python)) {
  console.error("Python operator environment is missing. Run npm run operator:setup first.");
  process.exit(1);
}

const result = spawnSync(python, process.argv.slice(2), { cwd: root, stdio: "inherit" });
if (result.error) throw result.error;
process.exit(result.status ?? 1);
