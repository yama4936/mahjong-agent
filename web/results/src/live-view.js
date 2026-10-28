'use strict';
const screen = document.querySelector('#screen');
const placeholder = document.querySelector('#placeholder');
const status = document.querySelector('#status');
const updated = document.querySelector('#updated');
const toggle = document.querySelector('#toggle');
let socket, retry, paused = false, lastFrame = 0, metadata = null, objectUrl = null, generation = 0;
const states = {match:'対局中 · LIVE',round_result:'局結果 · LIVE',match_result:'対局結果 · LIVE'};
function hide(message, detail='対局画面を確認できたら、自動で表示します。') {
  generation++;
  screen.hidden = true;
  screen.removeAttribute('src');
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = null;
  placeholder.hidden = false;
  placeholder.querySelector('strong').textContent = message;
  placeholder.querySelector('p').textContent = detail;
  status.textContent = message;
}
function connect() {
  if(paused || document.hidden) return;
  clearTimeout(retry);
  const ws = new WebSocket('wss://jantama-live.yama.asia/ws');
  socket = ws;
  ws.binaryType = 'blob';
  ws.onopen = () => {if(socket===ws) hide('対局画面を待っています');};
  ws.onmessage = event => {
    if(socket !== ws || paused) return;
    if(typeof event.data === 'string') {
      try {metadata = JSON.parse(event.data);} catch {ws.close();return;}
      if(!states[metadata.state]) hide(metadata.state==='offline'?'配信元に再接続しています':'対局画面を待っています');
      return;
    }
    if(!metadata || !states[metadata.state] || !Number.isFinite(metadata.capturedAt)) return;
    const version = ++generation;
    const incoming = URL.createObjectURL(event.data);
    const frame = new Image();
    const meta = metadata;
    frame.onload = () => {
      if(version !== generation || socket !== ws || paused){URL.revokeObjectURL(incoming);return;}
      if(objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = incoming;
      screen.src = incoming;
      screen.hidden = false;
      placeholder.hidden = true;
      lastFrame = performance.now();
      status.textContent = states[meta.state];
      updated.textContent = '撮影 '+new Date(meta.capturedAt*1000).toLocaleTimeString('ja-JP',{timeZone:'Asia/Tokyo'})+' JST';
    };
    frame.onerror = () => URL.revokeObjectURL(incoming);
    frame.src = incoming;
  };
  ws.onclose = () => {
    if(socket!==ws) return;
    socket = null;metadata = null;
    if(!paused && !document.hidden){hide('接続が切れました','3秒後に自動で再接続します。');retry=setTimeout(connect,3000);}
  };
  ws.onerror = () => ws.close();
}
function disconnect(message) {
  clearTimeout(retry);const old=socket;socket=null;metadata=null;if(old)old.close();hide(message);
}
toggle.onclick = () => {
  paused = !paused;toggle.textContent=paused?'観戦を再開':'観戦を一時停止';
  if(paused) disconnect('観戦を一時停止中');else connect();
};
document.querySelector('#fullscreen').onclick = async () => {
  try {if(document.fullscreenElement) await document.exitFullscreen();else await document.querySelector('.player').requestFullscreen();}
  catch {status.textContent='このブラウザは全画面表示に対応していません';}
};
document.addEventListener('visibilitychange',()=>{if(document.hidden)disconnect('観戦は非表示のため停止中');else if(!paused)connect();});
setInterval(()=>{if(!screen.hidden && performance.now()-lastFrame>4000)hide('映像の更新が止まっています','最新の映像を受信すると再開します。');},1000);
window.addEventListener('pagehide',()=>disconnect('観戦を終了しました'));
connect();
