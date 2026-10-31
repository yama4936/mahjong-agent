import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';

test('client template install is idempotent and preserves conflicting content', async () => {
  const dir = await mkdtemp(path.join(process.cwd(), '.client-template-test-'));
  try {
    await writeFile(path.join(dir, '1m__hf_base.png'), 'baseline marker');
    const run = () => execFileSync(process.execPath, ['scripts/install-client-templates.mjs', dir], {encoding:'utf8', stdio:['ignore','pipe','pipe']});
    assert.equal(JSON.parse(run()).alreadyPresent, false);
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
