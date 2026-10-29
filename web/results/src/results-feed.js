const endpoint = 'https://jantama-live.yama.asia/results/';
export function normalizeResults(data, base) {
  if (!Array.isArray(data.records) || !Number.isFinite(Date.parse(data.generatedAt))) throw Error('Invalid results');
  const image = value => {
    if (!value) return null;
    if (!/^images\/[a-f0-9]{24}\.webp$/.test(value)) throw Error('Invalid result image');
    return new URL(value, base).href;
  };
  return {...data, records:data.records.map(r => ({...r, image:image(r.image),
    rounds:(r.rounds||[]).map(x=>({...x,image:image(x.image)})),
    selfWins:(r.selfWins||[]).map(w=>({...w,frames:w.frames.map(f=>({...f,image:image(f.image)}))})),
    winHistory:(r.winHistory||[]).map(w=>({...w,image:image(w.image)})),
  }))};
}
export function watchResults(onData, onStatus, {interval=30000}={}) {
  let busy=false, stopped=false, current=null, revision=null;
  async function read(url, base) {
    const response=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(15000)});
    if(!response.ok) throw Error(response.status);
    return normalizeResults(await response.json(),base);
  }
  async function refresh() {
    if(busy || stopped || document.hidden) return;
    busy=true;
    try {
      let data, fallback=false;
      try { data=await read(endpoint+'data.json',endpoint); }
      catch(error) {
        if(current) throw error;
        data=await read('data.json',new URL('./',location.href));
        fallback=true;
      }
      if(stopped) return;
      const key=(fallback?'saved:':'live:')+data.generatedAt;
      if(key!==revision) { onData(data); current=data; revision=key; }
      const age=Date.now()-Date.parse(data.generatedAt);
      onStatus(fallback?'配信元に接続できないため、保存済みの記録を表示しています。再接続中です。':
        age>5*60*1000?'記録の更新が遅れています。最後に取得した記録を表示しています。':'30秒ごとに自動更新');
    } catch(error) {
      if(!stopped) onStatus(current?'更新できませんでした。表示中の記録を保持して再接続します。':'記録を読み込めません。自動で再試行します。');
    } finally { busy=false; }
  }
  const timer=setInterval(refresh,interval);
  document.addEventListener('visibilitychange',refresh);
  window.addEventListener('online',refresh);
  refresh();
  return ()=>{stopped=true;clearInterval(timer);document.removeEventListener('visibilitychange',refresh);window.removeEventListener('online',refresh);};
}
