import * as fs from "node:fs";
import { spawn } from "node:child_process";
import path from "node:path";

/** Opt in only through the existing explicit --artifacts argument. */
export function explicitOperatorArtifacts(root, args) {
  let directory;
  for (let index = 0; index < args.length; index += 1) {
    if (args[index] === "--artifacts") {
      const value = args[++index];
      if (!value || value.startsWith("--")) return undefined; // Let argparse report malformed options.
      directory = value;
    } else if (args[index].startsWith("--artifacts=")) {
      directory = args[index].slice("--artifacts=".length);
      if (!directory) return undefined;
    }
  }
  return directory === undefined ? undefined : path.resolve(root, directory);
}

/** The child inherits an append-only stderr FD, not a backpressured JS pipe.
 * Parent closes its copy immediately after spawn, including spawn failures.
 * No interception of recognition RPC stdout/stderr and no error suppression.
 */
export function spawnOperatorWithStderr(command, args, options, directory,
  dependencies = { fs, spawn }) {
  if (directory === undefined) return {
    child: dependencies.spawn(command, args, { ...options, stdio: "inherit" }),
    stderrPath: undefined,
  };
  dependencies.fs.mkdirSync(directory, { recursive: true });
  const stderrPath = path.join(directory, "operator-stderr.log");
  const flags = dependencies.fs.constants.O_WRONLY | dependencies.fs.constants.O_CREAT
    | dependencies.fs.constants.O_APPEND | (dependencies.fs.constants.O_NOFOLLOW ?? 0)
    | (dependencies.fs.constants.O_NONBLOCK ?? 0);
  const fd = dependencies.fs.openSync(stderrPath, flags, 0o600);
  try {
    if (!dependencies.fs.fstatSync(fd).isFile()) throw new Error("Operator stderr sink must be a regular file");
    dependencies.fs.fchmodSync(fd, 0o600);
    return { child: dependencies.spawn(command, args, { ...options, stdio: ["inherit", "inherit", fd] }), stderrPath };
  } finally {
    dependencies.fs.closeSync(fd);
  }
}
