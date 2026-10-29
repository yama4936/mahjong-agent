import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import sharp from 'sharp';
test('win frames belong only to their completed match; unfinished wins stay unpublished',async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'jantama-win-export-'));
 try{
  const run=path.join(root,'artifacts','friend-300-test'),frames=path.join(run,'frames');fs.mkdirSync(frames,{recursive:true});
  const image=path.join(frames,'win.png');await sharp({create:{width:8,height:8,channels:3,background:'#234'}}).png().toFile(image);
  const final=path.join(frames,'final.png');await sharp({create:{width:8,height:8,channels:3,background:'#abc'}}).png().toFile(final);
  const at='2026-10-27T00:00:00Z',win=(id)=>({timestamp:at,event:'self_win_frame',winId:id,action:'ron',evidence:{observedAt:at,screenshot:image,elapsedMs:6000}});
  fs.writeFileSync(path.join(run,'python-operator.jsonl'),[{timestamp:at,event:'reaction_win',execution:{clicked:true,action:'ron'}},{timestamp:at,event:'outcome_observed',kind:'round',evidence:{screenshot:image}},win('first'),{timestamp:at,event:'outcome_observed',kind:'match',evidence:{screenshot:final}},{timestamp:'2026-10-27T01:00:00Z',event:'decision',execution:{clicked:true,action:'tsumo'}},win('unfinished')].map(JSON.stringify).join('\n'));
  const out=path.join(root,'out');execFileSync(process.execPath,[new URL('./export.mjs',import.meta.url).pathname,root,out]);
  for (const asset of ['E.png', '5m.png', 'P.png', 'LICENSE', 'NOTICE.md']) {
    assert(fs.existsSync(path.join(out, 'tiles', asset)), `Missing tile asset: ${asset}`);
  }
  const data=JSON.parse(fs.readFileSync(path.join(out,'data.json')));assert.equal(data.records.length,1);assert.equal(data.records[0].winHistory.length,1);assert.equal(data.records[0].winHistory[0].status,'not_reviewed');assert.equal(data.records[0].winHistory[0].yaku,null);assert(data.records[0].winHistory[0].image);assert.equal(data.records[0].winHistory[0].action,'ron');assert.equal(data.records[0].selfWins.length,1);assert.equal(data.records[0].selfWins[0].id,'first');assert.equal(data.records[0].selfWins[0].frames[0].elapsedMs,6000);assert(fs.existsSync(path.join(out,data.records[0].selfWins[0].frames[0].image)));
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
