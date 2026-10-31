import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import sharp from 'sharp';

async function seedBase(dir:string) {
  const png = await sharp({create:{width:2,height:2,channels:3,background:'white'}}).png().toBuffer();
  const classes = ['m','p','s'].flatMap(suit => Array.from({length:9}, (_, i) => `${i+1}${suit}`)).concat(['E','S','W','N','P','F','C']);
  for (const tile of classes) await writeFile(path.join(dir, `${tile}__hf_base.png`), png);
}


test('client template install is idempotent and preserves conflicting content', async () => {
  const dir = await mkdtemp(path.join(process.cwd(), '.client-template-test-'));
  try {
    await seedBase(dir);
    const run = () => execFileSync(process.execPath, ['scripts/install-client-templates.mjs', dir], {encoding:'utf8', stdio:['ignore','pipe','pipe']});
    const first=JSON.parse(run());
    assert.equal(first.alreadyPresent, false);
    assert.equal(first.bootstrapBaseFilesChecked, 34);
    assert.equal(first.templateIdentityVerified, false);
    assert.equal(first.accuracyVerified, false);
    const target = path.join(dir, '4p__6c_friend.png');
    assert.deepEqual(await readFile(target), await readFile('templates/client/4p__6c_friend.png'));
    assert.equal(JSON.parse(run()).alreadyPresent, true);
    await writeFile(target, 'existing different user file');
    assert.throws(run, /differs; preserved/);
    assert.equal(await readFile(target, 'utf8'), 'existing different user file');
  } finally { await rm(dir, {recursive:true,force:true}); }
});

test('client template install rejects missing bootstrap base', async () => {
  const dir = await mkdtemp(path.join(process.cwd(), '.client-template-test-'));
  try {
    assert.throws(() => execFileSync(process.execPath, ['scripts/install-client-templates.mjs', dir], {stdio:'pipe'}));
  } finally { await rm(dir, {recursive:true,force:true}); }
});

test('client template install rejects malformed bootstrap base', async () => {
  const dir = await mkdtemp(path.join(process.cwd(), '.client-template-test-'));
  try {
    await seedBase(dir);
    await writeFile(path.join(dir, '9s__hf_base.png'), 'not a PNG');
    assert.throws(() => execFileSync(process.execPath, ['scripts/install-client-templates.mjs', dir], {stdio:'pipe'}));
  } finally { await rm(dir, {recursive:true,force:true}); }
});
