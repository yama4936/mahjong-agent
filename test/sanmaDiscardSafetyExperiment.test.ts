import { test } from "node:test";
import assert from "node:assert/strict";
import { inspectSanmaDiscardSafety } from "../src/game/sanmaDiscardSafetyExperiment.js";

// Hand based on 16:05:55 friend frame; rivers and no-prompt state are hypothetical.
const hand = ["1m","9m","9m","4p","0p","5p","6p","8p","2s","6s","S","S","N"];
const opponent = (seat: string, discards: string[]) => ({seat, discards, openMelds: 0, melds: [], kitaCount: 0});
const state = {rules:"sanma",riichiDeclared:false,phase:"self_turn",hand,draw:"E",seat:"east",openMelds:0,melds:[],visibleTiles:[],ownDiscards:[],doraIndicators:[],ownKitaCount:0,opponents:[opponent("south",["5p","N"]),opponent("west",["0p"]) ]};
const input = {state,riichiStatus:"not_declared" as const,ui:{status:"confirmed" as const,actions:[]},turnContext:"ordinary_draw_confirmed" as const,handEvidence:"confirmed" as const,meldEvidence:"confirmed" as const,visibleEvidence:"confirmed_complete" as const};
test("observed opponent rivers identify direct furiten without asserting other safety", () => {
 const result=inspectSanmaDiscardSafety(input);
 for (const name of ["0p","5p"]) {
  const row=result.rows.find(r=>r.tile===name)!;
  assert.deepEqual(row.byOpponent.map(x=>x.status),["genbutsu_candidate","genbutsu_candidate"]);
  assert.equal(row.allOpponentsGenbutsuCandidate,true);
 }
 const north=result.rows.find(r=>r.tile==="N")!;
 assert.deepEqual(north.byOpponent.map(x=>x.status),["genbutsu_candidate","unknown"]);
 assert.equal(north.allOpponentsGenbutsuCandidate,false);
 assert.equal(result.operationAuthorized,false);
});
test("unverified UI or inconsistent game evidence prevents evaluation", () => {
 assert.throws(()=>inspectSanmaDiscardSafety({...input,ui:{status:"confirmed",actions:["kita"]}}));
 assert.throws(()=>inspectSanmaDiscardSafety({...input,state:{...state,opponents:[state.opponents[0]]}}));
 assert.throws(()=>inspectSanmaDiscardSafety({...input,visibleEvidence:"unknown"} as unknown as typeof input));
});
