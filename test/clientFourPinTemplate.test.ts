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
    for (const file of allFiles.filter(f => f !== '4p__6c_friend.png' && f !== '3s__e48_friend.png' && f !== '8s__fourplayer_friend.png')) await symlink(path.resolve(base, file), path.join(temporary, file));
    await copyFile(fixture, path.join(temporary, '4p__6c_friend.png'));
    const options = {normalizeFace:true, rejectBlank:true};
    const train = (name:string) => !/(?:holdout|capture|test)/i.test(name);
    const original = await loadTemplates(base, name => train(name) && name !== '4p__6c_friend.png' && name !== '3s__e48_friend.png' && name !== '8s__fourplayer_friend.png', options);
    const proposed = await loadTemplates(temporary, train, options);
    await copyFile('templates/client/3s__e48_friend.png', path.join(temporary, '3s__e48_friend.png'));
    const proposedThree = await loadTemplates(temporary, train, options);
    await copyFile('templates/client/8s__fourplayer_friend.png', path.join(temporary, '8s__fourplayer_friend.png'));
    const proposedEight = await loadTemplates(temporary, train, options);
    const eightSample = await readFile('templates/client/8s__fourplayer_friend.png');
    for (const name of ['8s-cd-heldout.png', '8s-bf-heldout.png', '8s-6c-heldout.png']) {
      const heldoutEight = await readFile(path.join('test/fixtures/eightsou-review', name));
      assert.notEqual(hash(eightSample), hash(heldoutEight));
      const beforeEight = await classifyTile(heldoutEight, proposedThree, options);
      const afterEight = await classifyTile(heldoutEight, proposedEight, options);
      assert.equal(beforeEight.tile, '8s'); assert.equal(afterEight.tile, '8s');
      assert.ok(threshold(afterEight));
      if (name === '8s-cd-heldout.png') assert.ok(beforeEight.confidence < .98);
    }
    const threeSample = await readFile('templates/client/3s__e48_friend.png');
    for (const name of ['3s-ba2-heldout.png', '3s-dd-heldout.png']) {
      const heldoutThree = await readFile(path.join('test/fixtures/threesou-review', name));
      assert.notEqual(hash(threeSample), hash(heldoutThree));
      const oldThree = await classifyTile(heldoutThree, proposed, options);
      const newThree = await classifyTile(heldoutThree, proposedThree, options);
      assert.equal(oldThree.tile, '3s'); assert.ok(oldThree.confidence < .98);
      assert.equal(newThree.tile, '3s'); assert.ok(threshold(newThree));
    }
    const sample = await readFile(fixture);
    const heldout = await readFile('test/fixtures/fourpin-review/4p-ba2-heldout.png');
    assert.notEqual(hash(sample), hash(heldout));
    const before = await classifyTile(heldout, original, options);
    const after = await classifyTile(heldout, proposed, options);
    assert.equal(before.tile, '4p'); assert.ok(before.confidence < .98);
    assert.equal(after.tile, '4p'); assert.ok(threshold(after));
    for (const file of holdouts) {
      const img = await readFile(path.join(base, file));
      assert.notEqual(hash(sample), hash(img), `4p candidate overlaps ${file}`);
      assert.notEqual(hash(threeSample), hash(img), `3s candidate overlaps ${file}`);
      assert.notEqual(hash(eightSample), hash(img), `8s candidate overlaps ${file}`);
      const expected = file.split('__')[0];
      const old = await classifyTile(img, original, options);
      const next = await classifyTile(img, proposed, options);
      // Existing false positives are not hidden by this incremental check.
      assert.equal(next.tile !== expected && threshold(next) && !(old.tile !== expected && threshold(old)), false, file);
      const nextThree = await classifyTile(img, proposedThree, options);
      assert.equal(nextThree.tile !== expected && threshold(nextThree) && !(next.tile !== expected && threshold(next)), false, `3s ${file}`);
      const nextEight = await classifyTile(img, proposedEight, options);
      assert.equal(nextEight.tile !== expected && threshold(nextEight) && !(nextThree.tile !== expected && threshold(nextThree)), false, `8s ${file}`);
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
        const nextThree = await matchTile(imagePath, rectangles[i]!, proposedThree, options);
        assert.equal(nextThree.tile, expected[i], `${name} with 3s ${i}`);
        assert.deepEqual(nextThree, next, `${name} changed by 3s ${i}`);
        // The first frame supplied the 8s template: never count it as holdout.
        if (name !== 'hand-seven-sou-control-a-20261021.jpg') {
          const nextEight = await matchTile(imagePath, rectangles[i]!, proposedEight, options);
          assert.deepEqual(nextEight, nextThree, `${name} changed by 8s ${i}`);
        }
      }
    }
    const image = 'test/fixtures/fourpin-review/hand-independent-heldout.png';
    const xs = [223,318,413,508,603,698,792,887,982,1077,1172];
    for (const x of xs) {
      const rect = {x:x-223,y:15,width:91,height:135};
      const old = await matchTile(image,rect,original,options);
      const next = await matchTile(image,rect,proposed,options);
      assert.equal(next.tile,old.tile, `independent hand slot ${x}`);
      const nextThree = await matchTile(image,rect,proposedThree,options);
      assert.equal(nextThree.tile,next.tile, `independent hand with 3s ${x}`);
      const nextEight = await matchTile(image,rect,proposedEight,options);
      assert.equal(nextEight.tile,nextThree.tile, `independent hand with 8s ${x}`);
    }
  } finally { await rm(temporary, {recursive:true, force:true}); }
});
