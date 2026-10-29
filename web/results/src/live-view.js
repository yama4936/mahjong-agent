'use strict';
const screen = document.querySelector('#screen');
const placeholder = document.querySelector('#placeholder');
const status = document.querySelector('#status');
const updated = document.querySelector('#updated');
const toggle = document.querySelector('#toggle');
let socket, retry, paused = false, lastFrame = 0, metadata = null, objectUrl = null, generation = 0;
const states = {live:'雀魂画面 · LIVE',match:'対局中 · LIVE',round_result:'局結果 · LIVE',match_result:'対局結果 · LIVE'};
const decisionPanel = document.querySelector('.decision-panel');
const logs = document.querySelector('#logs');
const logIds = new Set();
let lastDecision = null;
let eventSocket = null, eventRetry, eventsOpen = false;
const latestButton = document.querySelector('#logs-latest');
const actionLabels = {discard:'打牌',riichi:'リーチ',ron:'ロン',tsumo:'ツモ',chi:'チー',pon:'ポン',kan:'カン',pass:'見送り',skip:'見送り'};
function text(selector, value) { const target = document.querySelector(selector); if (target.textContent !== value) target.textContent = value; }
function probability(value) { return Number.isFinite(value) && value >= 0 && value <= 1 ? (value * 100).toFixed(1) + '%' : '—'; }
function timeLabel(value) {
  const time = typeof value === 'string' ? Date.parse(value) : NaN;
  return Number.isFinite(time) ? new Date(time).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo',hour12:false}) + ' JST' : '時刻不明';
}
function updateFreshness(reason) {
  const age = lastDecision ? Date.now() - Date.parse(lastDecision.timestamp) : NaN;
  const connected = eventsOpen || (!screen.hidden && socket && ['live', 'match'].includes(metadata?.state));
  const current = !reason && connected && !paused && !document.hidden &&
    Number.isFinite(age) && age >= -5000 && age < 15000 && !['round_result', 'match_result'].includes(metadata?.state);
  if (decisionPanel.dataset.current !== String(current)) decisionPanel.dataset.current = String(current);
  text('#decision-freshness', !lastDecision ? '判断データ待ち' : current ? '直近の判断（15秒以内）' : '過去の判断 · ' + (reason || '更新待ち'));
}
function renderTelemetry(telemetry) {
  lastDecision = telemetry?.decision && typeof telemetry.decision === 'object' ? telemetry.decision : null;
  const d = lastDecision;
  const action = typeof d?.action === 'string' ? (actionLabels[d.action] || d.action) : '—';
  text('#decision-action', action + (typeof d?.tile === 'string' ? ' ' + d.tile : ''));
  text('#decision-win', probability(d?.winProbability));
  text('#decision-deal-in', probability(d?.dealInProbability));
  text('#decision-confidence', probability(d?.recognitionConfidence));
  text('#decision-shanten', Number.isInteger(d?.shanten) ? String(d.shanten) : '—');
  text('#decision-source', '判断元 ' + (typeof d?.source === 'string' ? d.source : '—'));
  text('#decision-safety', '認識安全判定 ' + (d?.recognitionSafe === true ? 'safe=true' : d?.recognitionSafe === false ? 'safe=false（要確認）' : '—'));
  text('#decision-time', d ? '判断 ' + timeLabel(d.timestamp) : '判断受信前');
  updateFreshness();
  const follow = logs.scrollHeight - logs.scrollTop - logs.clientHeight < 32;
  let removedHeight = 0;
  for (const entry of Array.isArray(telemetry?.logs) ? telemetry.logs : []) {
    if (!entry || typeof entry.id !== 'string' || logIds.has(entry.id)) continue;
    logIds.add(entry.id);
    text('#log-latest', '最新ログ ' + timeLabel(entry.timestamp));
    const row = document.createElement('li');
    row.dataset.id = entry.id;
    const time = document.createElement('time');
    time.textContent = timeLabel(entry.timestamp);
    if (typeof entry.timestamp === 'string' && Number.isFinite(Date.parse(entry.timestamp))) time.dateTime = entry.timestamp;
    const event = document.createElement('span');
    event.className = 'log-event';
    event.textContent = typeof entry.event === 'string' ? entry.event : 'ログ';
    const message = document.createElement('span');
    message.className = 'log-message';
    message.textContent = typeof entry.message === 'string' ? entry.message : '';
    row.append(time, event, message);
    logs.append(row);
    while (logs.children.length > 100) {
      removedHeight += logs.firstElementChild.getBoundingClientRect().height;
      logs.firstElementChild.remove();
    }
  }
  // Retain a bounded history beyond the visible rows to ignore reconnect snapshots.
  while (logIds.size > 1000) logIds.delete(logIds.values().next().value);
  document.querySelector('#log-empty').hidden = logs.children.length > 0;
  if (follow) logs.scrollTop = logs.scrollHeight;
  else if (removedHeight) logs.scrollTop = Math.max(0, logs.scrollTop - removedHeight);
  updateLogFollow();
}
function updateLogFollow() {
  latestButton.hidden = logs.scrollHeight - logs.scrollTop - logs.clientHeight < 32;
}
logs.addEventListener('scroll', updateLogFollow, { passive: true });
latestButton.onclick = () => { logs.scrollTop = logs.scrollHeight; updateLogFollow(); };
function eventStatus(label) {
  text('#events-status', label);
  document.querySelector('#events-status').dataset.live = String(eventsOpen);
}
function connectEvents() {
  if (paused || document.hidden || eventSocket) return;
  clearTimeout(eventRetry);
  const ws = new WebSocket('wss://jantama-live.yama.asia/events');
  eventSocket = ws;
  ws.onopen = () => {
    if (eventSocket !== ws) return;
    eventsOpen = true;
    eventStatus('LIVE');
    updateFreshness();
  };
  ws.onmessage = event => {
    if (eventSocket !== ws || paused || document.hidden) return;
    let message;
    try { message = JSON.parse(event.data); } catch { ws.close(); return; }
    if (message?.type !== 'telemetry') return;
    text('#events-received', 'データ受信 ' + timeLabel(new Date().toISOString()));
    renderTelemetry(message.telemetry);
  };
  ws.onclose = () => {
    if (eventSocket !== ws) return;
    eventSocket = null;
    eventsOpen = false;
    eventStatus(paused || document.hidden ? '停止' : '再接続中');
    updateFreshness('ログ接続待ち');
    if (!paused && !document.hidden) eventRetry = setTimeout(connectEvents, 3000);
  };
  ws.onerror = () => ws.close();
}
function hide(message, detail='雀魂タブの映像を受信できたら、自動で表示します。') {
  generation++;
  screen.hidden = true;
  screen.removeAttribute('src');
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = null;
  placeholder.hidden = false;
  placeholder.querySelector('strong').textContent = message;
  placeholder.querySelector('p').textContent = detail;
  status.textContent = message;
  updateFreshness(eventsOpen && !paused && !document.hidden ? undefined : message);
}
function connect() {
  if(paused || document.hidden) return;
  clearTimeout(retry);
  const ws = new WebSocket('wss://jantama-live.yama.asia/ws');
  socket = ws;
  ws.binaryType = 'blob';
  ws.onopen = () => {if(socket===ws) hide('雀魂タブの映像を待っています');};
  ws.onmessage = event => {
    if(socket !== ws || paused) return;
    if(typeof event.data === 'string') {
      try {metadata = JSON.parse(event.data);} catch {ws.close();return;}
      if (!metadata || typeof metadata !== 'object') {ws.close();return;}
      if (!eventsOpen) renderTelemetry(metadata.telemetry);
      else updateFreshness();
      if(!states[metadata.state]) hide(metadata.state==='offline'?'配信元に再接続しています':'雀魂タブの映像を待っています');
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
      updateFreshness();
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
  clearTimeout(eventRetry);
  const oldEvents = eventSocket; eventSocket = null; eventsOpen = false;
  if (oldEvents) oldEvents.close();
  eventStatus('停止');
  clearTimeout(retry);const old=socket;socket=null;metadata=null;if(old)old.close();hide(message);
}
toggle.onclick = () => {
  paused = !paused;toggle.textContent=paused?'観戦を再開':'観戦を一時停止';
  if(paused) disconnect('観戦を一時停止中');else { connect(); connectEvents(); }
};
document.querySelector('#fullscreen').onclick = async () => {
  try {if(document.fullscreenElement) await document.exitFullscreen();else await document.querySelector('.player').requestFullscreen();}
  catch {status.textContent='このブラウザは全画面表示に対応していません';}
};
document.addEventListener('visibilitychange',()=>{if(document.hidden)disconnect('観戦は非表示のため停止中');else if(!paused){connect();connectEvents();}});
setInterval(()=>{if(!screen.hidden && performance.now()-lastFrame>4000)hide('映像の更新が止まっています','最新の映像を受信すると再開します。');else updateFreshness(screen.hidden && !eventsOpen ? status.textContent : undefined);},1000);
window.addEventListener('pagehide',()=>disconnect('観戦を終了しました'));
connect();
connectEvents();
