import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile, readdir, rm, symlink, copyFile } from 'node:fs/promises';
import path from 'node:path';
import { classifyTile, loadTemplates, matchTile } from '../src/recognition/templateMatcher.js';
import { proposeLiveHandLayout } from '../src/recognition/handLayoutProposal.js';

const base = 'templates/bootstrap';
const fixture = 'templates/client/4p__6c_friend.png';
const hash = (data: Buffer) => createHash('sha256').update(data).digest('hex');
const threshold = (x: {confidence:number;runnerUpConfidence:number}) => x.confidence >= .98 && x.confidence - x.runnerUpConfidence >= .1;

test('four-pin candidate improves independent crop without new high-confidence holdout errors', {timeout: 120_000, skip: !existsSync(base)}, async () => {
  const temporary = await mkdtemp(path.join(process.cwd(), '.fourpin-evaluation-'));
  try {
    const allFiles = (await readdir(base)).filter(f => /\.(png|jpe?g|webp)$/i.test(f));
    const holdouts = allFiles.filter(f => /(?:holdout|capture|test)/i.test(f));
    assert.ok(holdouts.length >= 105);
    for (const file of allFiles.filter(f => f !== '4p__6c_friend.png')) await symlink(path.resolve(base, file), path.join(temporary, file));
    await copyFile(fixture, path.join(temporary, '4p__6c_friend.png'));
    const options = {normalizeFace:true, rejectBlank:true};
    const train = (name:string) => !/(?:holdout|capture|test)/i.test(name);
    const original = await loadTemplates(base, name => train(name) && name !== '4p__6c_friend.png', options);
    const proposed = await loadTemplates(temporary, train, options);
    const sample = await readFile(fixture);
    const heldout = await readFile('test/fixtures/fourpin-review/4p-ba2-heldout.png');
    assert.notEqual(hash(sample), hash(heldout));
    const before = await classifyTile(heldout, original, options);
    const after = await classifyTile(heldout, proposed, options);
    assert.equal(before.tile, '4p'); assert.ok(before.confidence < .98);
    assert.equal(after.tile, '4p'); assert.ok(threshold(after));
    for (const file of holdouts) {
      const img = await readFile(path.join(base, file));
      assert.notEqual(hash(sample), hash(img), `candidate overlaps ${file}`);
      const expected = file.split('__')[0];
      const old = await classifyTile(img, original, options);
      const next = await classifyTile(img, proposed, options);
      // Existing false positives are not hidden by this incremental check.
      assert.equal(next.tile !== expected && threshold(next) && !(old.tile !== expected && threshold(old)), false, file);
    }
    // Two four-player captures with manually reviewed expected tile labels.
    // Neither frame contains 4p, and cross-game independence is not proven.
    const fourPlayer = [
      ['hand-seven-sou-control-a-20261021.jpg', ['6m','6m','7m','7m','1p','2p','2p','2p','4s','5s','7s','8s','S','N']],
      ['hand-nine-sou-before-glare-20261021.jpg', ['1m','1m','2m','2m','0m','5m','7m','8p','8p','2s','5s','6s','9s','S']],
    ] as const;
    for (const [name, expected] of fourPlayer) {
      const imagePath = path.join('test/fixtures', name);
      const geometry = await proposeLiveHandLayout(imagePath);
      const rectangles = [...geometry.handSlots, geometry.drawSlot];
      assert.equal(rectangles.length, 14);
      for (let i = 0; i < rectangles.length; i++) {
        const old = await matchTile(imagePath, rectangles[i]!, original, options);
        const next = await matchTile(imagePath, rectangles[i]!, proposed, options);
        assert.equal(old.tile, expected[i], `${name} baseline ${i}`);
        assert.equal(next.tile, expected[i], `${name} with candidate ${i}`);
        assert.deepEqual(next, old, `${name} changed result ${i}`);
      }
    }
    const image = 'test/fixtures/fourpin-review/hand-independent-heldout.png';
    const xs = [223,318,413,508,603,698,792,887,982,1077,1172];
    for (const x of xs) {
      const rect = {x:x-223,y:15,width:91,height:135};
      const old = await matchTile(image,rect,original,options);
      const next = await matchTile(image,rect,proposed,options);
      assert.equal(next.tile,old.tile, `independent hand slot ${x}`);
    }
  } finally { await rm(temporary, {recursive:true, force:true}); }
});
