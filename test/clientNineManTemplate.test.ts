import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {existsSync} from 'node:fs';
import {mkdtemp, readFile, readdir, rm, symlink, copyFile, mkdir} from 'node:fs/promises';
import path from 'node:path';
import {classifyTile, loadTemplates, matchTile} from '../src/recognition/templateMatcher.js';
import {proposeLiveHandLayout} from '../src/recognition/handLayoutProposal.js';

const base='templates/bootstrap';
const sample='templates/client/9m__cd82_friend.png';
const fixture='test/fixtures/nineman-review/9m-7e-heldout.png';
const hash=(b:Buffer)=>createHash('sha256').update(b).digest('hex');
const high=(x:{confidence:number;runnerUpConfidence:number})=>x.confidence>=.98 && x.confidence-x.runnerUpConfidence>=.1;
const redFiveHash='e0b4794a54e60432338668658032c552f18b5c7b94a9bc13fb0adf4e095b2854';

test('nine-man template improves separate game without new high-confidence errors', {timeout:120_000,skip:!existsSync(base)}, async()=>{
  const dir=await mkdtemp(path.join(process.cwd(),'.ninema-evaluation-'));
  try {
    const files=(await readdir(base)).filter(f=>/\.(png|jpe?g|webp)$/i.test(f));
    const holdouts=files.filter(f=>/(?:holdout|capture|test)/i.test(f));
    assert.ok(holdouts.length>=105);
    const supplemental=['4p__6c_friend.png','3s__e48_friend.png','8s__fourplayer_friend.png'];
    const overrides=new Set([...supplemental,'9m__cd82_friend.png']);
    const beforeDir=path.join(dir,'before'), afterDir=path.join(dir,'after');
    await mkdir(beforeDir);await mkdir(afterDir);
    // Always use the three tracked examples, whether or not the host has
    // installed files with those names. Never write into the host directory.
    const hostDigests=new Map<string,string>();
    for(const name of overrides) if(files.includes(name)) hostDigests.set(name,hash(await readFile(path.join(base,name))));
    for(const f of files.filter(f=>!overrides.has(f))){
      await symlink(path.resolve(base,f),path.join(beforeDir,f));
      await symlink(path.resolve(base,f),path.join(afterDir,f));
    }
    for(const name of supplemental){
      const source=path.join('templates/client',name);
      await copyFile(source,path.join(beforeDir,name));
      await copyFile(source,path.join(afterDir,name));
      assert.equal(hash(await readFile(path.join(beforeDir,name))),hash(await readFile(source)));
      assert.equal(hash(await readFile(path.join(afterDir,name))),hash(await readFile(source)));
    }
    await copyFile(sample,path.join(afterDir,'9m__cd82_friend.png'));
    assert.equal((await readdir(afterDir)).filter(n=>n==='9m__cd82_friend.png').length,1);
    const train=(f:string)=>!/(?:holdout|capture|test)/i.test(f);
    const opt={normalizeFace:true,rejectBlank:true};
    const old=await loadTemplates(beforeDir,train,opt);
    const proposed=await loadTemplates(afterDir,train,opt);
    const sampleData=await readFile(sample), target=await readFile(fixture);
    assert.notEqual(hash(sampleData),hash(target));
    const a=await classifyTile(target,old,opt), b=await classifyTile(target,proposed,opt);
    assert.equal(a.tile,'9m');assert.ok(a.confidence<.98);
    assert.equal(b.tile,'9m');assert.ok(high(b));
    let reviewedRed=0;
    for(const f of files){
      if(overrides.has(f))continue;
      const img=await readFile(path.join(base,f));
      assert.notEqual(hash(img),hash(sampleData),`sample duplicate ${f}`);
      assert.notEqual(hash(img),hash(target),`target duplicate ${f}`);
    }
    for(const f of holdouts){
      const img=await readFile(path.join(base,f));
      const red=hash(img)===redFiveHash;if(red){assert.equal(f,'5m__hf_holdout_037.png');reviewedRed++;}
      const expected=red?'0m':f.split('__')[0];
      const before=await classifyTile(img,old,opt),after=await classifyTile(img,proposed,opt);
      assert.equal(after.tile!==expected&&high(after)&&!(before.tile!==expected&&high(before)),false,`new high-confidence error ${f}`);
    }
    assert.equal(reviewedRed,1);
    const fourPlayer=[
      ['hand-seven-sou-control-a-20261021.jpg',['6m','6m','7m','7m','1p','2p','2p','2p','4s','5s','7s','8s','S','N']],
      ['hand-nine-sou-before-glare-20261021.jpg',['1m','1m','2m','2m','0m','5m','7m','8p','8p','2s','5s','6s','9s','S']],
    ] as const;
    for(const [name,expected] of fourPlayer){
      const imagePath=path.join('test/fixtures',name);const geometry=await proposeLiveHandLayout(imagePath);
      const slots=[...geometry.handSlots,geometry.drawSlot];assert.equal(slots.length,14);
      for(let i=0;i<slots.length;i++){
        const before=await matchTile(imagePath,slots[i]!,old,opt), after=await matchTile(imagePath,slots[i]!,proposed,opt);
        assert.equal(before.tile,expected[i],`${name} baseline ${i}`);
        assert.equal(after.tile,expected[i],`${name} new ${i}`);
        assert.deepEqual(after,before,`${name} changed ${i}`);
      }
    }
    for(const [name,digest] of hostDigests) assert.equal(hash(await readFile(path.join(base,name))),digest,`host file changed: ${name}`);
  } finally {await rm(dir,{recursive:true,force:true});}
});
