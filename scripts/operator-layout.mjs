import path from "node:path";

/** Saved hand-only layouts can omit entire opponent rivers and melds. */
export function defaultOperatorLayoutArgs(root, forwarded) {
  if (forwarded.some((argument) => argument === "--layout" || argument.startsWith("--layout="))) return [];
  return ["--layout", path.join(root, "config", "layout-runtime.json")];
}
