import {test} from 'node:test';
import assert from 'node:assert/strict';
import {summarize,jstDay} from './src/chart-data.mjs';
test('separates categories, missing ranks, unfinished results and partial yaku',()=>{
 const rows=Array.from({length:12},(_,i)=>({id:String(i),at:`2026-10-${String(i+1).padStart(2,'0')}T00:00:00Z`,status:'complete',category:'ranked',rank:i===10?null:2,winHistory:[]}));
 rows[0].winHistory=[{status:'partial',yaku:[{name:'立直',han:1}],bonus:[{name:'ドラ',han:3}]},{status:'unreadable',yaku:null}];
 rows.push({...rows[0],category:'friend',rank:1},{...rows[0],status:'unfinished',rank:1});
 const m=summarize(rows);assert.equal(m.rows.length,12);assert.equal(m.known.length,11);assert.equal(m.trend[8].value,null);assert.equal(m.trend[9].value,2);assert.equal(m.trend[10].value,null);assert.equal(m.trend[11].value,null);assert.deepEqual(m.roles,[{label:'立直',value:1}]);assert.equal(m.partial,1);assert.equal(m.wins.length,2);
 assert.equal(summarize(rows,{category:'friend'}).known.length,1);assert.equal(summarize(rows,{from:'2026-10-02',to:'2026-10-03'}).rows.length,2);assert.equal(summarize([]).known.length,0);assert.equal(jstDay('2026-10-01T16:00:00Z'),'2026-10-02');
});
