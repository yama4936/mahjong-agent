import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

test('missing and mismatched evidence stays unknown without modifying the input log',async()=>{
 const directory=await mkdtemp(path.join(os.tmpdir(),'sanma-discard-test-'));
 try{
  const log=path.join(directory,'operator.jsonl'),out=path.join(directory,'evidence.jsonl');
  const digest='a'.repeat(64), absent=path.join(directory,'absent.png');
  const lines=[{event:'sanma_self_turn_observed',digest,screenshot:absent},
   {event:'sanma_friend_action_unconfirmed',action:'discard',timestamp:'t',result:{tile:'8p',frameSha256:digest}},
   {event:'sanma_friend_transition',action:'discard',beforeDigest:digest,afterDigest:digest,screenshot:absent},
   {event:'sanma_friend_action_unconfirmed',action:'discard',timestamp:'u',result:{tile:'8p',frameSha256:digest}},
   {event:'sanma_friend_transition',action:'discard',beforeDigest:'b'.repeat(64),afterDigest:digest,screenshot:absent},
   {event:'sanma_friend_action_unconfirmed',action:'discard',timestamp:'v',result:{tile:'8p',frameSha256:digest}}];
  const data=lines.map(x=>JSON.stringify(x)).join('\n')+'\n';await writeFile(log,data);
  const result=spawnSync(process.execPath,['--import','tsx','scripts/diagnose-sanma-discard.ts',log,out],{encoding:'utf8',timeout:30000});
  assert.equal(result.status,0,result.stderr);assert.equal(await readFile(log,'utf8'),data);
  const evidence=(await readFile(out,'utf8')).trim().split('\n').map(x=>JSON.parse(x));assert.equal(evidence.length,3);
  for(const x of evidence){assert.equal(x.status,'unknown');assert.equal(x.confirmed,false);assert.equal(x.verified,false);assert.equal(x.complete,false);assert.equal(x.operationAuthorized,false)}
  assert.equal(evidence[0].before.status,'unknown');assert.equal(evidence[0].after.status,'unknown');
  assert.equal(evidence[1].reason,'transition does not match action');assert.equal(evidence[2].reason,'transition missing');
  const again=spawnSync(process.execPath,['--import','tsx','scripts/diagnose-sanma-discard.ts',log,out],{encoding:'utf8',timeout:30000});assert.notEqual(again.status,0);
 }finally{await rm(directory,{recursive:true,force:true})}
});
