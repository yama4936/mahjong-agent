import {watchResults} from './results-feed.js';
const $=id=>document.getElementById(id),esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names={ranked:'段位戦',friend:'友人戦・練習',unknown:'種別未確認'};
const date=at=>new Date(at).toLocaleDateString('sv-SE',{timeZone:'Asia/Tokyo'});
const time=at=>new Date(at).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo'});
const labels=items=>items?.map(v=>`${v.name} ${v.han}翻`).join(' / ')||'未確認';
let all=[],filtered=[];
function counts(key){const map=new Map();for(const w of filtered)for(const v of w[key]||[])if(v.han>0)map.set(v.name,(map.get(v.name)||0)+1);return [...map].sort((a,b)=>b[1]-a[1]).map(([k,n])=>`<span>${esc(k)} <b>${n}件</b></span>`).join('')||'<p class="muted">確認できた記録はありません</p>';}
function render(){filtered=all.filter(w=>($('category').value==='all'||w.category===$('category').value)&&(!$('date').value||date(w.at)===$('date').value)&&($('yaku').value==='all'||w.yaku?.some(v=>v.name===$('yaku').value))&&($('status').value==='all'||($('status').value==='partial'?w.status==='partial':w.status!=='partial')));
 const n=filtered.filter(w=>w.status==='partial').length;
 $('coverage').textContent=`和了操作 ${filtered.length}件 ｜ 役の一部確認 ${n}件 ｜ 役未確認 ${filtered.length-n}件`;
 $('counts').innerHTML=counts('yaku');$('bonus').innerHTML=counts('bonus');
 $('rows').innerHTML=filtered.map(w=>`<tr><td><a href="index.html#match/${esc(w.matchId)}">${esc(time(w.at))}</a></td><td>${names[w.category]} / ${esc(w.round||'局不明')} / ${w.action==='ron'?'ロン':'ツモ'}</td><td>${w.status==='partial'?'一部確認':w.status==='unreadable'?'未確認（表示途中）':'未確認（未レビュー）'}</td><td>${esc(labels(w.yaku))}</td><td>${esc(labels(w.bonus))}</td><td>${w.observedTotalHan??'—'} / ${w.observedFu??'—'} / ${w.points??'—'}</td><td>${w.image?`<a target="_blank" rel="noopener" href="${esc(w.image)}">画像 ↗</a>`:'画像なし'}</td></tr>`).join('')||'<tr><td colspan="7">該当する記録はありません</td></tr>';
}
for(const id of ['category','date','yaku','status'])$(id).addEventListener('change',render);
$('download').onclick=()=>{
 const header=['win_id','match_id','timestamp','category','round','action_log','review_status','observed_yaku','observed_bonus','observed_total_han','observed_fu','points','image','image_sha256'];
 const csv=[header,...filtered.map(w=>[w.id,w.matchId,w.at,w.category,w.round,w.action,w.status,w.yaku?.map(v=>`${v.name}:${v.han}`).join('|'),w.bonus?.map(v=>`${v.name}:${v.han}`).join('|'),w.observedTotalHan,w.observedFu,w.points,w.image?new URL(w.image,location.href).href:'',w.imageHash])].map(row=>row.map(v=>'"'+String(v??'').replace(/"/g,'""')+'"').join(',')).join('\r\n');
 const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='jantama-yaku-analysis.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
watchResults(data=>{
  all=data.records.flatMap(r=>(r.winHistory||[]).map(w=>({...w,matchId:r.id,category:r.category}))).sort((a,b)=>b.at.localeCompare(a.at));
  const existing=new Set([...$('yaku').options].map(o=>o.value));
  for(const name of [...new Set(all.flatMap(w=>(w.yaku||[]).map(v=>v.name)))].sort()){
    if(existing.has(name)) continue;
    const o=document.createElement('option');o.value=o.textContent=name;$('yaku').append(o);
  }
  $('updated').textContent=' 更新: '+time(data.generatedAt);render();
},message=>{$('refresh-status').textContent=message;});
