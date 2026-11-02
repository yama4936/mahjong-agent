import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { once } from 'node:events';
import sharp from 'sharp';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

async function probe(rules: 'sanma' | 'yonma') {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'public-rules-'));
  const image = path.join(dir, 'empty.png');
  await writeFile(image, await sharp({create:{width:1920,height:1080,channels:3,background:'#000'}}).png().toBuffer());
  const child = spawn(process.execPath, ['--import','tsx','src/recognition/publicRecognitionServer.ts','config/layout-runtime.json','east',rules], {stdio:['pipe','pipe','pipe']});
  const lines = createInterface({input:child.stdout})[Symbol.asyncIterator]();
  try {
    assert.equal(JSON.parse((await lines.next()).value!).ready, true);
    child.stdin.write(JSON.stringify({id:1,screenshot:image})+'\n');
    const response = JSON.parse((await lines.next()).value!);
    assert.equal(response.id,1);
    assert.equal(response.error,undefined);
    return response.result;
  } finally {
    child.stdin.end();
    if (child.exitCode === null) await once(child,'exit');
    await rm(dir,{recursive:true,force:true});
  }
}

test('public server preserves rules and excludes nonexistent right seat for sanma', async () => {
  const observation = await probe('sanma');
  assert.equal(observation.rules,'sanma');
  assert.equal(observation.opponentDiscards.length,2);
  assert.equal(observation.ownDiscardsObserved,false);
  assert.ok(observation.opponentDiscards.every((p: any) => p.discardsObserved === false));
  assert.ok(!observation.configuredRegions.includes('rightDiscards'));
  assert.ok(!observation.configuredRegions.includes('rightMelds'));
});

test('public server retains four player default semantics for yonma', async () => {
  const observation = await probe('yonma');
  assert.equal(observation.rules,undefined);
  assert.equal(observation.opponentDiscards.length,3);
  assert.ok(observation.configuredRegions.includes('rightDiscards'));
});

test('public observation CLI fallback carries sanma constraints', async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'public-cli-rules-'));
  const image = path.join(dir, 'empty.png');
  await writeFile(image, await sharp({create:{width:1920,height:1080,channels:3,background:'#000'}}).png().toBuffer());
  try {
    const { execFile } = await import('node:child_process');
    const { promisify } = await import('node:util');
    const run = promisify(execFile);
    const cli = ['--import','tsx','src/cli.ts','public-observation',image,'config/layout-runtime.json','templates/bootstrap'];
    const {stdout} = await run(process.execPath,[...cli,'--backend=hybrid','--rules=sanma']);
    const o = JSON.parse(stdout);
    assert.equal(o.rules,'sanma');
    assert.equal(o.opponentDiscards.length,2);
    assert.equal(o.ownDiscardsObserved,false);
    await assert.rejects(run(process.execPath,[...cli,'--rules=sanma']));
    await assert.rejects(run(process.execPath,[...cli,'--backend=hybrid','--rules=sanma','--seat=north']));
  } finally {
    await rm(dir,{recursive:true,force:true});
  }
});
