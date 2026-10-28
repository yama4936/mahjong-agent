import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import crypto from 'node:crypto';
import sharp from 'sharp';
const root=path.resolve(process.argv[2]||'.');
const here=path.dirname(new URL(import.meta.url).pathname), out=path.resolve(process.argv[3]||path.join(here,'dist'));
fs.mkdirSync(path.join(out,'images'),{recursive:true});
for(const f of ['index.html','app.js','style.css','analysis.html','analysis.js','charts.html','charts.js','charts.css','chart-data.mjs','how-it-works.html','how-it-works.css','live.html','live-view.js','live-view.css','shell.js','shell.css'])fs.copyFileSync(path.join(here,'src',f),path.join(out,f));
fs.cpSync(path.join(here,'src/vendor'),path.join(out,'vendor'),{recursive:true});
function walk(dir,depth=0){return fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory() ? (['frames','replays','node_modules','.git'].includes(e.name)||depth>4 ? []:walk(path.join(dir,e.name),depth+1)):[path.join(dir,e.name)]);}
const files=walk(path.join(root,'artifacts')), labels=new Map();
function label(r){const e=r.outcomeEvidence||r.outcome||r.nativeFinal?.evidence||{};const screen=e.screenshot||r.nativePath;const v=r.result||r.finalResult||r;if(screen)labels.set(path.basename(screen),{rank:v.rank??v.finalRank??v.selfRank??v.selfPlacement??v.placement,points:v.points??v.selfPoints??v.selfScore,room:r.room,interrupted:r.operationallyInterrupted,deadline:r.actionDeadlineMs,commit:r.implementationCommit});}
for(const f of files.filter(f=>/\/matches\/.*\.json$|ranked-match-results\.jsonl$/.test(f))){try{if(f.endsWith('jsonl'))for(const l of fs.readFileSync(f,'utf8').trim().split('\n'))label(JSON.parse(l));else label(JSON.parse(fs.readFileSync(f)));}catch{}}
// Native result screens reviewed on 2026-10-27; these are final points, never inferred from board state.
const reviewed=[['2026-10-25T15-30-52',4,15100],['2026-10-25T15-53-59',4,10700],['2026-10-25T16-13-05',3,18000],['2026-10-25T16-34-04',3,25000],['2026-10-25T16-48-20',3,23500],['2026-10-25T18-32-04',4,10100],['2026-10-25T18-59-21',1,39100],['2026-10-25T21-14-13',4,1100]];
const yakuReviews=JSON.parse(fs.readFileSync(path.join(here,'yaku-reviewed.json')));
const records=[],seen=new Set();let malformed=0,logs=0;
async function asset(p){if(!p)return null;let local=path.join(root,'artifacts',p.split('/artifacts/')[1]||'');if(!fs.existsSync(local)||!fs.statSync(local).isFile())return null;const buf=fs.readFileSync(local),hash=crypto.createHash('sha256').update(buf).digest('hex');const name=hash.slice(0,24)+'.webp',target=path.join(out,'images',name);if(!fs.existsSync(target))await sharp(buf).resize({width:1280,withoutEnlargement:true}).webp({quality:78}).toFile(target);return {url:'images/'+name,hash};}
for(const f of files.filter(f=>path.basename(f)==='python-operator.jsonl').sort()){
 logs++;const run=path.relative(root,path.dirname(f));let rounds=[],selfWins=new Map(),lastFinal=0,deadline=null,pendingWins=[],currentWin=null,roundName=null;
 for await(const line of readline.createInterface({input:fs.createReadStream(f),crlfDelay:Infinity})){
  let r;try{r=JSON.parse(line);}catch{malformed++;continue;}
  deadline??=r.actionDeadlineMs??r.evaluation?.actionTiming?.deadlineMs;
  const state=r.evaluation?.state;
  if(state?.round)roundName=state.round+' / '+(state.honba??0);
  const ex=r.execution;
  if(ex?.clicked && ['ron','tsumo'].includes(ex.action) && ['reaction_win','decision'].includes(r.event)){
   currentWin={id:crypto.createHash('sha256').update(run+'|'+r.timestamp).digest('hex').slice(0,16),at:r.timestamp,action:ex.action,round:roundName,screenshot:null};pendingWins.push(currentWin);
  }
  if(r.event==='self_win_frame' && r.winId && ['ron','tsumo'].includes(r.action)){
   const img=await asset(r.evidence?.screenshot);
   if(img){if(!selfWins.has(r.winId))selfWins.set(r.winId,{id:r.winId,action:r.action,frames:[]});selfWins.get(r.winId).frames.push({at:r.evidence.observedAt,image:img.url,elapsedMs:r.evidence.elapsedMs});}
   continue;
  }
  if(r.event!=='outcome_observed')continue;
  const e=r.evidence||{},p=e.screenshot;if(!p)continue;
  if(r.kind==='round'){if(currentWin&&!currentWin.screenshot)currentWin.screenshot=p;rounds.push({at:r.timestamp,screenshot:p});continue;}
  if(r.kind!=='match')continue;
  const at=r.timestamp||e.observedAt;
  if(Date.parse(at)-lastFinal<60000){rounds=[];pendingWins=[];currentWin=null;selfWins.clear();continue;}lastFinal=Date.parse(at);
  const a=await asset(p);if(a&&seen.has(a.hash)){rounds=[];pendingWins=[];currentWin=null;selfWins.clear();continue;}if(a)seen.add(a.hash);
  let meta=labels.get(path.basename(p))||{};const v=reviewed.find(v=>path.basename(p).startsWith(v[0]));if(v)meta={...meta,rank:v[1],points:v[2]};
  const category=/ranked/.test(run)?'ranked':/friend|practice|cpu/.test(run)?'friend':'unknown';
  const roundRows=[];for(const rr of rounds){const img=await asset(rr.screenshot);roundRows.push({at:rr.at,image:img?.url||null});}
  const winHistory=[];
  for(const w of pendingWins){
   const img=await asset(w.screenshot),review=yakuReviews[w.id];
   const verified=img&&review?.imageHash===img.hash?review:null;
   const {screenshot,...entry}=w;
   winHistory.push({...entry,image:img?.url??null,...(verified||{status:'not_reviewed',yaku:null,bonus:null,observedTotalHan:null,observedFu:null,points:null})});
  }
  records.push({id:crypto.createHash('sha256').update(p).digest('hex').slice(0,16),at,run,category,status:'complete',rank:Number.isInteger(meta.rank)&&meta.rank>=1&&meta.rank<=4?meta.rank:null,points:Number.isFinite(meta.points)?meta.points:null,image:a?.url||null,rounds:roundRows,selfWins:[...selfWins.values()],winHistory,room:meta.room||null,setting:/300/.test(run)&&category==='friend'?'300+0':/5plus20|5-20/.test(run)&&category==='friend'?'5+20':'未確認',deadline:meta.deadline??deadline,commit:meta.commit||run.match(/-([0-9a-f]{7})-/)?.[1]||null,interrupted:meta.interrupted??null});rounds=[];selfWins.clear();pendingWins=[];currentWin=null;roundName=null;
 }
}
records.sort((a,b)=>String(b.at).localeCompare(String(a.at)));
const data={generatedAt:new Date().toISOString(),logs,malformed,records};fs.writeFileSync(path.join(out,'data.json'),JSON.stringify(data));console.log(JSON.stringify({logs,malformed,records:records.length,completed:records.filter(r=>r.status==='complete').length,rankedKnown:records.filter(r=>r.category==='ranked'&&r.rank).length}));
