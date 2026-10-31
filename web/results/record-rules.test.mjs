import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {recordRules,recordsForRules,rankSummary} from './src/record-rules.mjs';
import {summarize} from './src/chart-data.mjs';
test('separates rules and quarantines unverified sanma runs in old feeds',()=>{
 const rows=[{run:'ranked-old'},{run:'sanma-candidate'},{rules:'sanma',rank:3},{rules:'yonma',rank:4},{rules:'unknown'}];
 assert.equal(recordRules(rows[0]),'yonma');assert.equal(recordRules(rows[1]),'unknown');
 assert.equal(recordRules({rules:'unexpected'}),'unknown');
 assert.equal(recordsForRules(rows,'sanma').length,1);assert.equal(recordsForRules(rows,'yonma').length,2);
 const s=rankSummary([{rank:1},{rank:3},{rank:4}],'sanma');
 assert.equal(s.last,3);assert.equal(s.known.length,2);assert.equal(s.rate(3),0.5);
 assert.equal(rankSummary([],'sanma').average,null);
});
test('four-player chart excludes sanma, unknown rules, and manual collections',()=>{
 const base={at:'2026-10-31T00:00:00Z',status:'complete',category:'friend',rank:1};
 assert.equal(summarize([base,{...base,rules:'sanma'},{...base,rules:'unknown'},
 {...base,operation:'manual-assisted'}],{category:'friend'}).rows.length,1);
});
test('navigation and three-player rank choices',()=>{
 for(const name of ['index','analysis','charts','live','how-it-works','sanma'])
  assert.match(fs.readFileSync(new URL(`./src/${name}.html`,import.meta.url),'utf8'),/href="sanma.html"/);
 const html=fs.readFileSync(new URL('./src/sanma.html',import.meta.url),'utf8');
 assert.match(html,/data-rules="sanma"/);assert.match(html,/data-mode="friend" class="active"/);
 assert.doesNotMatch(html,/<option value="4">/);
});
