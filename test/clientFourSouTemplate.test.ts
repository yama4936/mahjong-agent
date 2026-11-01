import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {existsSync} from 'node:fs';
import {mkdtemp,readFile,readdir,rm,symlink,copyFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
import {classifyTile,loadTemplates,matchTile} from '../src/recognition/templateMatcher.js';
import {proposeLiveHandLayout} from '../src/recognition/handLayoutProposal.js';
const base='templates/bootstrap', sample='templates/client/4s__ff7_friend.png', target='test/fixtures/foursou-review/4s-b388-heldout.png';
const sha=(b:Buffer)=>createHash('sha256').update(b).digest('hex');
const high=(x:{confidence:number;runnerUpConfidence:number})=>x.confidence>=.98 && x.confidence-x.runnerUpConfidence>=.1;
test('four-sou independent example improves heldout without new high-confidence errors',{timeout:120000,skip:!existsSync(base)},async()=>{
 const temp=await mkdtemp(path.join(process.cwd(),'.four-sou-eval-'));
 try{
  const before=path.join(temp,'before'),after=path.join(temp,'after');await mkdir(before);await mkdir(after);
  const files=(await readdir(base)).filter(f=>/\.(png|jpe?g|webp)$/i.test(f));
  const overrides=['4p__6c_friend.png','3s__e48_friend.png','8s__fourplayer_friend.png','9m__cd82_friend.png','4s__ff7_friend.png'];
  const hostHashes=new Map<string,string>();for(const n of overrides)if(files.includes(n))hostHashes.set(n,sha(await readFile(path.join(base,n))));
  for(const f of files.filter(n=>!overrides.includes(n))){await symlink(path.resolve(base,f),path.join(before,f));await symlink(path.resolve(base,f),path.join(after,f));}
  for(const n of overrides.slice(0,4)){await copyFile(path.join('templates/client',n),path.join(before,n));await copyFile(path.join('templates/client',n),path.join(after,n));}
  await copyFile(sample,path.join(after,'4s__ff7_friend.png'));
  const train=(f:string)=>!/(?:holdout|capture|test)/i.test(f), opt={normalizeFace:true,rejectBlank:true};
  const old=await loadTemplates(before,train,opt),next=await loadTemplates(after,train,opt);
  const example=await readFile(sample),held=await readFile(target);assert.notEqual(sha(example),sha(held));
  for(const f of files.filter(n=>!overrides.includes(n))){const h=sha(await readFile(path.join(base,f)));assert.notEqual(h,sha(example),`source overlap ${f}`);assert.notEqual(h,sha(held),`target overlap ${f}`);}
  const first=await classifyTile(held,old,opt),second=await classifyTile(held,next,opt);
  assert.equal(first.tile,'4s');assert.ok(first.confidence<.98);assert.equal(second.tile,'4s');assert.ok(high(second));
  const holdouts=files.filter(f=>/(?:holdout|capture|test)/i.test(f));assert.ok(holdouts.length>=105);
  for(const f of holdouts){const image=await readFile(path.join(base,f));const expected=sha(image)==='e0b4794a54e60432338668658032c552f18b5c7b94a9bc13fb0adf4e095b2854'?'0m':f.split('__')[0];const x=await classifyTile(image,old,opt),y=await classifyTile(image,next,opt);assert.equal(y.tile!==expected&&high(y)&&!(x.tile!==expected&&high(x)),false,`new high-confidence misclassification ${f}`);}
  const controls=[['hand-seven-sou-control-a-20261021.jpg',['6m','6m','7m','7m','1p','2p','2p','2p','4s','5s','7s','8s','S','N']],['hand-nine-sou-before-glare-20261021.jpg',['1m','1m','2m','2m','0m','5m','7m','8p','8p','2s','5s','6s','9s','S']]] as const;
  for(const [name,expected] of controls){const image=path.join('test/fixtures',name);const geometry=await proposeLiveHandLayout(image);const slots=[...geometry.handSlots,geometry.drawSlot];assert.equal(slots.length,14);for(let i=0;i<slots.length;i++){const x=await matchTile(image,slots[i]!,old,opt),y=await matchTile(image,slots[i]!,next,opt);assert.equal(y.tile!==expected[i]&&high(y)&&!(x.tile!==expected[i]&&high(x)),false,`${name} slot ${i}`);}}
  for(const [n,h] of hostHashes)assert.equal(sha(await readFile(path.join(base,n))),h,`host file changed ${n}`);
 }finally{await rm(temp,{recursive:true,force:true});}
});
