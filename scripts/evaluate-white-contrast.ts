/** Offline diagnostic only. Neither the source labels nor output authorize play. */
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { classifyTile, loadTemplates } from "../src/recognition/templateMatcher.js";

type Entry = { name: string; label: string; output: string; output_sha256: string; relationship: string };
const manifest = process.argv[2];
if (!manifest) throw new Error("Pass the contrast-set manifest path");
const entries: Entry[] = JSON.parse(await readFile(manifest, "utf8"));
const templates = await loadTemplates("templates/bootstrap", f => !/(?:holdout|capture|test)/i.test(f), { normalizeFace: true });
for (const entry of entries) {
  const image = await readFile(entry.output);
  const sha256 = createHash("sha256").update(image).digest("hex");
  if (sha256 !== entry.output_sha256) throw new Error(`Hash mismatch: ${entry.name}`);
  const guarded = await classifyTile(image, templates, { normalizeFace: true, allClasses: false, rejectBlank: true });
  const unguarded = await classifyTile(image, templates, { normalizeFace: true, allClasses: false, rejectBlank: false });
  console.log(JSON.stringify({ name: entry.name, label: entry.label, relationship: entry.relationship, sha256, guarded, unguarded }));
}
