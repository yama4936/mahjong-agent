import test from 'node:test';import assert from 'node:assert/strict';import {existsSync} from 'node:fs';import {readFile,mkdtemp,writeFile} from 'node:fs/promises';import path from 'node:path';import {tmpdir} from 'node:os';import {createHash} from 'node:crypto';import {evaluate,validateRows} from '../scripts/evaluate-sanma-hand-holdout.js';
const file=path.resolve('artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-28-27-220Z-before.png');
test('holdout manifests require labels, provenance and unique immutable images',()=>{
 const row={image:'a.png',sha256:'a'.repeat(64),matchId:'m1',reviewer:'human',tiles:['1m'],positions:[{x:1,y:2}]};
 assert.equal(validateRows([row]).length,1);assert.throws(()=>validateRows([]));assert.throws(()=>validateRows([row,row]),/duplicate/);
 assert.throws(()=>validateRows([{...row,reviewer:''}]),/required/);assert.throws(()=>validateRows([{...row,tiles:['bad']}]))
 assert.throws(()=>validateRows([{...row,buttons:['skip']}]),/buttons/);
});
test('real reviewed row produces a non-authorizing report and detects changed image', {skip:!existsSync(file)||!existsSync('templates/bootstrap/1m__hf_base.png'),timeout:60000},async()=>{
 const dir=await mkdtemp(path.join(tmpdir(),'sanma-holdout-')),bytes=await readFile(file),sha256=createHash('sha256').update(bytes).digest('hex');
 const positions=[223,317,412,507,602,697,792].map(x=>({x,y:921}));positions.push({x:917,y:873});
 const row={image:file,sha256,matchId:'historical-test-not-independent',reviewer:'fixture-review',tiles:['1p','1p','2p','8p','5s','8s','9s','1m'],positions,buttons:['empty',null,null]};
 const manifest=path.join(dir,'manifest.json'),report=path.join(dir,'report.json');await writeFile(manifest,JSON.stringify([row]));const result=await evaluate(manifest,report);
 assert.equal(result.operationAuthorized,false);assert.equal(result.independence,'caller_declared_not_verified');assert.equal(result.rows[0]?.exactLabels,true);assert.equal(result.rows[0]?.exactPositions,true);assert.equal(result.rows[0]?.observed.safe,false);
 assert.equal(result.rows[0]?.buttonComparison?.[0]?.correct,true);assert.equal(result.rows[0]?.buttonComparison?.[1]?.correct,null);assert.equal(result.rows[0]?.buttonRowComplete,false);
 await assert.rejects(evaluate(manifest,report),/EEXIST/);await writeFile(manifest,JSON.stringify([{...row,sha256:'0'.repeat(64)}]));await assert.rejects(evaluate(manifest,path.join(dir,'bad.json')),/digest mismatch/);
});
