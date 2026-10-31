import {recordsForRules} from './record-rules.mjs';
export const jstDay=at=>new Date(at).toLocaleDateString('sv-SE',{timeZone:'Asia/Tokyo'});
export function summarize(records,{category='ranked',from='',to=''}={}){
 const rows=recordsForRules(records,'yonma').filter(r=>r.operation!=='manual-assisted').filter(r=>r.status==='complete'&&r.category===category&&(!from||jstDay(r.at)>=from)&&(!to||jstDay(r.at)<=to)).sort((a,b)=>a.at.localeCompare(b.at));
 const known=rows.filter(r=>Number.isInteger(r.rank)&&r.rank>=1&&r.rank<=4);
 const ranks=[1,2,3,4].map(rank=>({label:`${rank}位`,value:known.filter(r=>r.rank===rank).length}));
 const daily=new Map(),roles=new Map();
 for(const r of rows)daily.set(jstDay(r.at),(daily.get(jstDay(r.at))||0)+1);
 const wins=rows.flatMap(r=>r.winHistory||[]);
 for(const w of wins)for(const y of w.yaku||[])roles.set(y.name,(roles.get(y.name)||0)+1);
 // A full ten-match window is required; missing ranks produce a gap.
 const trend=rows.map((r,i)=>{const window=rows.slice(Math.max(0,i-9),i+1);return {label:`${i+1}戦目`,date:jstDay(r.at),matchId:r.id,value:window.length===10&&window.every(x=>Number.isInteger(x.rank)&&x.rank>=1&&x.rank<=4)?window.reduce((s,x)=>s+x.rank,0)/10:null};});
 return {rows,known,ranks,trend,daily:[...daily].map(([label,value])=>({label,value})),roles:[...roles].map(([label,value])=>({label,value})).sort((a,b)=>b.value-a.value),wins,partial:wins.filter(w=>w.status==='partial').length};
}
