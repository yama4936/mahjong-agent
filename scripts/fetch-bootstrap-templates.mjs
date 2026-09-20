import { mkdir, readdir, unlink, writeFile } from "node:fs/promises";
import path from "node:path";

const revision = "8c0f22e7c6b64be55bb1d2767fe1a63981788de7";
const repository = "pjura/mahjong_souls_tiles";
const outputDirectory = path.resolve("templates/bootstrap");
const suits = { b: "s", n: "m", p: "p" };
const honors = { ew: "E", sw: "S", ww: "W", nw: "N", wd: "P", gd: "F", rd: "C" };

const classes = [];
for (const [sourceSuit, targetSuit] of Object.entries(suits)) {
  for (let rank = 1; rank <= 9; rank += 1) classes.push({ source: `${rank}${sourceSuit}`, target: `${rank}${targetSuit}` });
}
for (const [source, target] of Object.entries(honors)) classes.push({ source, target });

await mkdir(outputDirectory, { recursive: true });
for (const file of await readdir(outputDirectory)) {
  if (/__(?:hf)(?:_|\.)/.test(file)) await unlink(path.join(outputDirectory, file));
}
const variants = [null, ...Array.from({ length: 20 }, (_, index) => index)];
const jobs = classes.flatMap(({ source, target }) => variants.map((variant) => ({ source, target, variant })));
for (let offset = 0; offset < jobs.length; offset += 8) {
  await Promise.all(jobs.slice(offset, offset + 8).map(async ({ source, target, variant }) => {
  const sourceName = variant === null ? source : `${source}_aug_${variant}`;
  const url = `https://huggingface.co/datasets/${repository}/resolve/${revision}/dataset/test/${source}/${sourceName}.png`;
  let response;
  for (let attempt = 1; attempt <= 4; attempt += 1) {
    try {
      response = await fetch(url);
      break;
    } catch (error) {
      if (attempt === 4) throw error;
      await new Promise((resolve) => setTimeout(resolve, attempt * 500));
    }
  }
  if (!response) throw new Error(`No response: ${url}`);
  if (!response.ok) throw new Error(`Failed ${response.status}: ${url}`);
  const data = Buffer.from(await response.arrayBuffer());
  if (data.length < 100) throw new Error(`Unexpectedly small template: ${source}`);
  const suffix = variant === null ? "base" : `aug_${variant}`;
  await writeFile(path.join(outputDirectory, `${target}__hf_${suffix}.png`), data);
  }));
}

const metadataResponse = await fetch(`https://huggingface.co/api/datasets/${repository}`);
if (!metadataResponse.ok) throw new Error(`Failed to read dataset metadata: ${metadataResponse.status}`);
const metadata = await metadataResponse.json();
if (metadata.sha !== revision) throw new Error(`Dataset revision changed: expected ${revision}, got ${metadata.sha}`);
const sourceToTarget = Object.fromEntries(classes.map(({ source, target }) => [source, target]));
const screenshots = metadata.siblings.flatMap(({ rfilename }) => {
  const match = rfilename.match(/^dataset\/(train|test)\/([^/]+)\/(Screenshot[^/]+\.png)$/);
  if (!match || !sourceToTarget[match[2]]) return [];
  return [{ split: match[1], source: match[2], target: sourceToTarget[match[2]], rfilename }];
}).sort((a, b) => a.rfilename.localeCompare(b.rfilename));
const grouped = new Map();
for (const job of screenshots) {
  const key = `${job.split}/${job.source}`;
  const values = grouped.get(key) ?? [];
  values.push(job);
  grouped.set(key, values);
}
const realTrainingJobs = [];
const holdoutJobs = [];
for (const { source } of classes) {
  const train = grouped.get(`train/${source}`) ?? [];
  const test = grouped.get(`test/${source}`) ?? [];
  realTrainingJobs.push(...train.slice(0, 8));
  holdoutJobs.push(...train.slice(8, 10), ...test.slice(0, 2));
}

async function downloadScreenshotJobs(jobs, suffix) {
  for (let offset = 0; offset < jobs.length; offset += 8) {
    await Promise.all(jobs.slice(offset, offset + 8).map(async ({ target, rfilename }, localIndex) => {
      const response = await fetch(`https://huggingface.co/datasets/${repository}/resolve/${revision}/${rfilename}`);
      if (!response.ok) throw new Error(`Failed ${response.status}: ${rfilename}`);
      const data = Buffer.from(await response.arrayBuffer());
      const index = offset + localIndex;
      await writeFile(path.join(outputDirectory, `${target}__hf_${suffix}_${String(index).padStart(3, "0")}.png`), data);
    }));
  }
}

await downloadScreenshotJobs(realTrainingJobs, "real");
await downloadScreenshotJobs(holdoutJobs, "holdout");
console.log(JSON.stringify({
  repository,
  revision,
  classes: classes.length,
  syntheticVariants: variants.length,
  realTrainingVariants: realTrainingJobs.length,
  holdoutVariants: holdoutJobs.length,
  files: classes.length * variants.length + realTrainingJobs.length + holdoutJobs.length,
  outputDirectory,
}, null, 2));
