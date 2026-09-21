import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const environment = path.join(root, ".runtime", "python-auto-venv");
const python = process.platform === "win32"
  ? path.join(environment, "Scripts", "python.exe")
  : path.join(environment, "bin", "python");

function run(command, args) {
  const result = spawnSync(command, args, { cwd: root, stdio: "inherit" });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

if (!existsSync(python)) {
  if (process.platform === "win32") {
    const launcher = spawnSync("py", ["-3.12", "-m", "venv", environment], {
      cwd: root,
      stdio: "inherit",
    });
    if (launcher.error?.code === "ENOENT") run("python", ["-m", "venv", environment]);
    else if (launcher.status !== 0) process.exit(launcher.status ?? 1);
  } else {
    const uv = spawnSync("uv", ["venv", environment], { cwd: root, stdio: "inherit" });
    if (uv.error?.code === "ENOENT") run("python3", ["-m", "venv", environment]);
    else if (uv.status !== 0) process.exit(uv.status ?? 1);
  }
}

if (!existsSync(python)) {
  console.error(`Python environment was not created: ${python}`);
  process.exit(1);
}
run(python, ["-m", "pip", "install", "-r", path.join(root, "python", "requirements.txt")]);
console.log(`Python operator ready: ${python}`);
