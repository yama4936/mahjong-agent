import fs from 'node:fs';
import assert from 'node:assert/strict';
import path from 'node:path';
const dir=path.join(path.dirname(new URL(import.meta.url).pathname),'dist');
const d=JSON.parse(fs.readFileSync(path.join(dir,'data.json')));
assert(d.records.length>0);assert.equal(new Set(d.records.map(r=>r.id)).size,d.records.length);
const finals=d.records.filter(r=>r.image);assert.equal(new Set(finals.map(r=>r.image)).size,finals.length);
for(const r of d.records){assert(Number.isFinite(Date.parse(r.at)));assert(['ranked','friend','unknown'].includes(r.category));assert(r.rank===null||(Number.isInteger(r.rank)&&r.rank>=1&&r.rank<=4));if(r.status!=='complete')assert.equal(r.rank,null);for(const img of [r.image,...r.rounds.map(x=>x.image)].filter(Boolean))assert(fs.existsSync(path.join(dir,img)),img);}
const recent=d.records.filter(r=>r.category==='ranked'&&r.at>='2026-10-25T15:00:00'&&r.at<'2026-10-26T15:00:00'&&r.rank);
assert.equal(recent.length,8);assert.equal(recent.reduce((s,r)=>s+r.rank,0),26);
console.log(JSON.stringify({records:d.records.length,images:finals.length,recentAverage:26/8,verified:true}));
