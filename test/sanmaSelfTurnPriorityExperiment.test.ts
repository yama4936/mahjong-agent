import { test } from "node:test";
import assert from "node:assert/strict";
import { inspectSanmaSelfTurnPriority } from "../src/game/sanmaSelfTurnPriorityExperiment.js";
const base = {rules:"sanma", phase:"self_turn", riichiDeclared:false, seat:"west", scores:{west:35000}, melds:[], openMelds:0};
const state = {...base, hand:["1m","9m","9m","4p","0p","5p","6p","8p","2s","6s","S","S","N"], draw:"E"};
const input = {state,riichiStatus:"not_declared" as const,ui:{status:"confirmed" as const,actions:["kita","pass"] as const}};
test("actual pre-riichi north prompt is held for choice before ordinary discard", () => {
 const r=inspectSanmaSelfTurnPriority(input);
 assert.equal(r.stage,"action_choice_required"); assert.ok(r.candidates.some(x=>x.action==="kita")); assert.equal(r.operationAuthorized,false);
});
test("actual riichi-prompt hand identifies tenpai discards", () => {
 const stateR={...base,hand:["9m","9m","4p","0p","5p","6p","7p","8p","2s","4s","S","S","S"],draw:"5p"};
 const r=inspectSanmaSelfTurnPriority({...input,state:stateR,ui:{status:"confirmed",actions:["riichi","pass"]}});
 assert.equal(r.stage,"action_choice_required"); assert.ok(r.riichiDiscards.length); assert.equal(r.operationAuthorized,false);
});
test("offered complete win has priority, unresolved and illegal observations reject", () => {
 const won={...base,hand:["1p","2p","3p","4p","5p","6p","1s","2s","3s","4s","5s","W","W"],draw:"6s"};
 assert.equal(inspectSanmaSelfTurnPriority({...input,state:won,ui:{status:"confirmed",actions:["tsumo","pass"]}}).stage,"win_candidate");
 assert.throws(()=>inspectSanmaSelfTurnPriority({...input,state:{...won,scores:{west:900}},ui:{status:"confirmed",actions:["riichi"]}}));
 assert.throws(()=>inspectSanmaSelfTurnPriority({...input,ui:{status:"confirmed",actions:["tsumo"]}}));
 assert.throws(()=>inspectSanmaSelfTurnPriority({...input,ui:{status:"confirmed",actions:["kita","kita"]}}));
 assert.throws(()=>inspectSanmaSelfTurnPriority({...input,state:{...state,riichiDeclared:true}}));
 assert.throws(()=>inspectSanmaSelfTurnPriority({...input,state:{...state,draw:undefined}}));
});

test("a hypothetical simultaneous win outranks north extraction; competing kita and riichi stay undecided", () => {
 const won={...base,hand:["1p","2p","3p","4p","5p","6p","1s","2s","3s","4s","5s","N","N"],draw:"6s"};
 const win=inspectSanmaSelfTurnPriority({...input,state:won,ui:{status:"confirmed",actions:["tsumo","kita","pass"]}});
 assert.equal(win.stage,"win_candidate"); assert.ok(win.candidates.some(c=>c.action==="kita"));
 const waiting={...base,hand:["N","N","4p","0p","5p","6p","7p","8p","2s","4s","S","S","S"],draw:"5p"};
 const both=inspectSanmaSelfTurnPriority({...input,state:waiting,ui:{status:"confirmed",actions:["riichi","kita","pass"]}});
 assert.equal(both.stage,"action_choice_required"); assert.ok(both.riichiDiscards.length);
});
