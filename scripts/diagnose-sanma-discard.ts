/** Offline diagnostic only. Never reads or writes the live game or operator state. */
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { layoutSchema } from '../src/recognition/layout.js';
import { HybridTileRecognizer } from '../src/recognition/hybridTileRecognizer.js';
import { inspectSanmaOwnRiverCandidate } from '../src/recognition/sanmaOwnRiverCandidate.js';

const [logPath, outputPath] = process.argv.slice(2);
if (!logPath || !outputPath || logPath === outputPath) throw new Error('usage: diagnose-sanma-discard LOG OUTPUT');
const entries = (await readFile(logPath, 'utf8')).split('\n').filter(Boolean).map(line => JSON.parse(line));
const layout = layoutSchema.parse(JSON.parse(await readFile('config/layout-runtime.json', 'utf8')));
const classifier = new HybridTileRecognizer();
const observations = new Map<string, string>();
const records: unknown[] = [];
async function inspect(path: unknown, digest: unknown) {
  if (typeof path !== 'string' || typeof digest !== 'string' || !/^[0-9a-f]{64}$/.test(digest))
    return {status:'unknown', reason:'missing image or digest', verified:false, complete:false, operationAuthorized:false};
  try {
    const frame = await readFile(path);
    if (createHash('sha256').update(frame).digest('hex') !== digest) throw new Error('image digest mismatch');
    return await inspectSanmaOwnRiverCandidate(frame, layout, classifier);
  } catch (e) { return {status:'unknown', reason:e instanceof Error ? e.message : String(e),
    frameSha256:digest, verified:false, complete:false, operationAuthorized:false}; }
}
try {
  let pending: any;
  for (const entry of entries) {
    if (entry.event === 'sanma_self_turn_observed' && typeof entry.digest === 'string' && typeof entry.screenshot === 'string')
      observations.set(entry.digest, entry.screenshot);
    if (entry.event === 'sanma_friend_action_unconfirmed') {
      if (pending) records.push({scope:'offline_untrusted_sanma_discard_evidence', status:'unknown',
        reason:'transition missing', action:pending.action, timestamp:pending.timestamp, confirmed:false,
        verified:false, complete:false, operationAuthorized:false});
      pending = entry.action === 'discard' ? entry : undefined;
    }
    if (entry.event === 'sanma_friend_transition' && pending) {
      const beforeDigest = entry.beforeDigest;
      const consistent = entry.action === 'discard' && beforeDigest === pending.result?.frameSha256;
      records.push({scope:'offline_untrusted_sanma_discard_evidence', status:'unknown',
        action:'discard', timestamp:pending.timestamp, attemptedTile:pending.result?.tile,
        confirmed:false, verified:false, complete:false, operationAuthorized:false,
        reason:consistent ? 'image hypotheses only; action success is not verified' : 'transition does not match action',
        ...(consistent ? {before:await inspect(observations.get(beforeDigest), beforeDigest),
          after:await inspect(entry.screenshot, entry.afterDigest)} : {})});
      pending = undefined;
    }
  }
  if (pending) records.push({scope:'offline_untrusted_sanma_discard_evidence', status:'unknown',
    reason:'transition missing', action:'discard', timestamp:pending.timestamp,
    confirmed:false, verified:false, complete:false, operationAuthorized:false});
  await writeFile(outputPath, records.map(r => JSON.stringify(r)).join('\n') + (records.length ? '\n' : ''), {flag:'wx', mode:0o600});
} finally { await classifier.close(); }
