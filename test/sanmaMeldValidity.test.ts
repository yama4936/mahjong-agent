import test from 'node:test';
import assert from 'node:assert/strict';
import {parseGameState,parsePublicGameState} from '../src/game/state.js';
import {inspectSanmaDiscardSafety} from '../src/game/sanmaDiscardSafetyExperiment.js';

const meld = {type:'pon',tiles:['0p','5p','5p']};
const state = {rules:'sanma',seat:'east',phase:'self_turn',riichiDeclared:false,
  hand:['1m','9m','1p','2p','3p','1s','2s','3s','S','S'],draw:'E',
  openMelds:1,melds:[meld],visibleTiles:[],ownDiscards:[],doraIndicators:[],ownKitaCount:0,
  opponents:[{seat:'south',openMelds:0,melds:[],discards:[],kitaCount:0},
             {seat:'west',openMelds:0,melds:[],discards:[],kitaCount:0}]};
const input = {state,riichiStatus:'not_declared' as const,ui:{status:'confirmed' as const,actions:[]},
  turnContext:'ordinary_draw_confirmed' as const,handEvidence:'confirmed' as const,
  meldEvidence:'confirmed' as const,visibleEvidence:'confirmed_complete' as const};

test('red-five pon remains a valid sanma physical meld and can reach the discard evaluator',()=>{
  const result = inspectSanmaDiscardSafety(input);
  assert.ok(result.rows.length>0);
  assert.equal(result.operationAuthorized,false);
});

test('illegal own or opponent sanma melds cannot reach decisions',()=>{
  for (const bad of [
    {type:'pon',tiles:['5p','5p','6p']},
    {type:'pon',tiles:['5p','5p','5p','5p']},
    {type:'ankan',tiles:['5p','5p','5p']},
    {type:'minkan',tiles:['5p','5p','5p','6p']},
    {type:'kakan',tiles:['5p','5p','5p']},
  ]) {
    assert.throws(()=>inspectSanmaDiscardSafety({...input,state:{...state,melds:[bad]}}),/Invalid sanma meld/);
    const opposing = {...state,opponents:[{...state.opponents[0],openMelds:1,melds:[bad]},state.opponents[1]]};
    assert.throws(()=>parseGameState(opposing),/Invalid sanma meld/);
    assert.throws(()=>parsePublicGameState(opposing),/Invalid sanma meld/);
  }
});

test('yonma state parsing behavior remains unchanged',()=>{
  const yonma={...state,rules:'yonma',ownKitaCount:undefined,opponents:[],
    melds:[{type:'pon',tiles:['5p','5p','6p']}]};
  assert.doesNotThrow(()=>parseGameState(yonma));
});
