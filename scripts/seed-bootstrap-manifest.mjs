import { appendFile, readFile, readdir } from "node:fs/promises";
import path from "node:path";

const directory = path.resolve(process.argv[2] ?? "templates/live-verified");
const manifestPath = path.join(directory, "manifest.jsonl");
let existing = "";
try {
  existing = await readFile(manifestPath, "utf8");
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
const recorded = new Set(existing.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line).crop));
const revision = "8c0f22e7c6b64be55bb1d2767fe1a63981788de7";
const records = (await readdir(directory))
  .filter((file) => file.endsWith("__hf_base.png") && !recorded.has(file))
  .map((file) => ({
    schemaVersion: 1,
    crop: file,
    label: file.split("__")[0],
    split: "train",
    sourceDataset: "pjura/mahjong_souls_tiles",
    sourceRevision: revision,
    sourcePath: `dataset/test/${file.split("__")[0]}`,
    provenance: "pinned-bootstrap",
  }));
if (records.length > 0) {
  await appendFile(manifestPath, records.map((record) => JSON.stringify(record)).join("\n") + "\n", "utf8");
}
console.log(JSON.stringify({ directory, added: records.length, totalRecorded: recorded.size + records.length }));
