import { readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { loadTemplates, classifyTile, type MatcherOptions } from "../src/recognition/templateMatcher.js";
import { normalizeTileFace } from "../src/recognition/normalizeTileFace.js";
import { VitTileRecognizer } from "../src/recognition/vitRecognizer.js";
import { combineTileEvidence } from "../src/recognition/consensus.js";

const directory = "templates/live-verified", output = "artifacts/recognition-ablation";
await mkdir(output, { recursive: true });
const manifest = (await readFile(path.join(directory,"manifest.jsonl"),"utf8")).trim().split("\n").map(s=>JSON.parse(s));
const hash = (data: Buffer) => createHash("sha256").update(data).digest("hex");
const images = new Map<string, Buffer>();
for (const row of manifest) images.set(row.crop, await readFile(path.join(directory,row.crop)));
const groups = [...new Set<string>(manifest.filter(r=>r.sourceSha256).map(r=>r.sourceSha256))];
const variants: Record<string, MatcherOptions> = { baseline: {rejectBlank:false}, normalized: {normalizeFace:true,rejectBlank:true}, normalized_all: {normalizeFace:true,allClasses:true,rejectBlank:true} };
const results: Record<string, any[]> = {};
for (const [name, options] of Object.entries(variants)) {
  const rows = [];
  for (const group of groups) {
    const tests = manifest.filter(r=>r.sourceSha256 === group);
    const heldHashes = new Set(tests.map(r=>hash(images.get(r.crop)!)));
    const training = new Set(manifest.filter(r=>r.sourceSha256 !== group && !heldHashes.has(hash(images.get(r.crop)!))).map(r=>r.crop));
    const templates = await loadTemplates(directory, f=>training.has(f),options);
    for (const row of tests) {
      const match = await classifyTile(images.get(row.crop)!, templates, options);
      rows.push({...row, predicted:match.tile, score:match.confidence, runnerUpConfidence:match.runnerUpConfidence, accepted:match.confidence >= .98 && match.confidence-match.runnerUpConfidence >= .01});
    }
  }
  results[name]=rows;
  console.log(name, rows.filter(r=>r.predicted===r.label).length, rows.length);
}
const vit = new VitTileRecognizer();
try {
  const rows = results.normalized_all!;
  const predictions = await vit.classifyTileImages(rows.map(r=>images.get(r.crop)!));
  results.vit = rows.map((r,i)=>({...r,predicted:predictions[i]!.tile,score:predictions[i]!.confidence,accepted:predictions[i]!.confidence>=.98}));
  results.agreement = rows.map((r,i)=>{
    const combined = combineTileEvidence({tile:r.predicted,confidence:r.score,runnerUpConfidence:r.runnerUpConfidence},predictions[i]!);
    return {...r,...combined,predicted:combined.accepted ? r.predicted : null};
  });
} finally {await vit.close();}
const summaries = Object.fromEntries(Object.entries(results).map(([name,rows])=>{
  const accepted=rows.filter(r=>r.accepted);
  const frames=groups.map(g=>rows.filter(r=>r.sourceSha256===g)).filter(r=>r.length===14);
  return [name,{total:rows.length,correct:rows.filter(r=>r.label===r.predicted).length,accuracy:rows.filter(r=>r.label===r.predicted).length/rows.length,
    accepted:accepted.length,acceptedErrors:accepted.filter(r=>r.label!==r.predicted).length,
    fullHandFrames:frames.length,fullHandCorrect:frames.filter(rs=>rs.every(r=>r.label===r.predicted)).length,
    fullHandAccepted:frames.filter(rs=>rs.every(r=>r.accepted)).length,rows}];
}));
await writeFile(path.join(output,"live-report.json"),JSON.stringify({notes:["Leave-one-source-frame-out, excluding exact held-out image bytes from training.","All six frames come from the existing session: NOT independent match generalization.","Only previously labeled crops; red-man and red-pin absent. No certificate."],summaries},null,2));
// Normalized supervised dataset for the 37-output local model experiment.
const normalizedDir = path.join(output,"normalized-live"); await mkdir(normalizedDir,{recursive:true});
for (const row of manifest) await writeFile(path.join(normalizedDir,row.crop),await normalizeTileFace(images.get(row.crop)!));
await writeFile(path.join(normalizedDir,"manifest.json"),JSON.stringify(manifest,null,2));
console.log(JSON.stringify(summaries, (key,value)=>key==="rows"?undefined:value,2));
