import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { parseGameState } from '../src/game/state.js';
import { assessReactionCalls, decide } from '../src/agent/decision.js';
import { generateLegalActions } from '../src/game/actions.js';

test('native four-sou pon cannot claim a strict tanyao speed gain from yakuless tenpai', async () => {
  const fixture = JSON.parse(await readFile('test/fixtures/tanyao-call-shanten-mismatch-20261022.json','utf8'));
  const state = parseGameState(fixture.state);
  const calls = assessReactionCalls(state,generateLegalActions(state));
  const call = calls.find(c=>c.actionId==='pon_4s')!;
  assert.equal(call.currentShanten,1);
  assert.equal(call.resultingShanten,0);
  assert.deepEqual(call.candidateYaku,['tanyao']);
  assert.equal(call.approved,false);
  assert.ok(call.reasons.includes('no_strict_tanyao_shanten_improvement'));
  assert.equal((await decide(state,{mode:'force-auto'})).selectedAction.action,'pass');
  const jev = {chooseReaction:async()=>({actionId:'pon_4s',confidence:.99,probabilities:{pon_4s:.99,pass:.01},model:'test',promptVersion:'mahjong-reaction-v1',latencyMs:1})} as any;
  assert.equal((await decide(state,{mode:'force-auto',jev})).selectedAction.action,'pass');
});
test('confirmed yakuhai and a removable isolated terminal retain their viable calls', async () => {
  const fixture = JSON.parse(await readFile('test/fixtures/tanyao-call-shanten-mismatch-20261022.json','utf8'));
  const yakuhai = parseGameState({...fixture.state,hand:fixture.state.hand.map((t:string)=>t==='4s'?'C':t),pendingDiscard:{tile:'C',fromSeat:'east'},availableUiActions:['pon','pass'],ownDiscards:[],opponents:[],visibleTiles:[]});
  const call = assessReactionCalls(yakuhai,generateLegalActions(yakuhai)).find(c=>c.actionId==='pon_C')!;
  assert.equal(call.approved,true);
  assert.ok(call.confirmedYaku.includes('yakuhai:C'));
  const valid = parseGameState({phase:'reaction',seat:'south',round:'east_1',
    hand:['1m','2m','3m','4m','6p','7p','8p','8p','8p','4s','4s','5s','6s'],
    pendingDiscard:{tile:'4s',fromSeat:'east'},availableUiActions:['pon','pass']});
  const candidate = assessReactionCalls(valid,generateLegalActions(valid)).find(c=>c.actionId==='pon_4s')!;
  assert.equal(candidate.approved,true);
  assert.ok(candidate.candidateYaku.includes('tanyao'));
});

test('late shape tenpai for draw payments retains the existing call assessment', async () => {
  const fixture = JSON.parse(await readFile('test/fixtures/tanyao-call-shanten-mismatch-20261022.json','utf8'));
  const late = parseGameState({...fixture.state,turn:15});
  const call = assessReactionCalls(late,generateLegalActions(late)).find(c=>c.actionId==='pon_4s')!;
  assert.equal(call.approved,true);
  assert.ok(!call.reasons.includes('no_strict_tanyao_shanten_improvement'));
});
