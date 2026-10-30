import * as fs from "node:fs";
import path from "node:path";

export function operatorLifecycleDirectory(root, explicitDirectory) {
  return explicitDirectory ?? path.resolve(root, "artifacts/python-auto");
}

/**
 * Use synchronous append-only records so a signal handler can preserve the
 * launcher/child relationship before forwarding the signal.  This is
 * diagnostic evidence only; a logging failure must not change game control.
 */
export function recordOperatorLifecycle(directory, event, fields = {}, dependencies = fs) {
  try {
    dependencies.mkdirSync(directory, { recursive: true });
    const record = JSON.stringify({ timestamp: new Date().toISOString(), event, ...fields }) + "\n";
    dependencies.appendFileSync(path.join(directory, "operator-lifecycle.jsonl"), record, {
      encoding: "utf8", mode: 0o600,
    });
  } catch {
    // The operator stderr/JSONL evidence paths retain their existing behavior
    // even when this supplementary lifecycle sink cannot be written.
  }
}
