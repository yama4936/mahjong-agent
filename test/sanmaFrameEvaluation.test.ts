import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { evaluateSanmaFrameCandidate, type ReviewedFrameEvidence } from "../src/recognition/sanmaFrameEvaluation.js";

const frame = Buffer.from("synthetic fixture, not a screenshot");
const digest = createHash("sha256").update(frame).digest("hex");
const hand = ["1m","9m","9m","4p","0p","5p","6p","8p","2s","6s","S","S","N"];
const state = { rules: "sanma", riichiDeclared: false, phase: "self_turn", hand, draw: "E", seat: "east",
  openMelds: 0, melds: [], visibleTiles: [], ownDiscards: [], doraIndicators: ["1p"], ownKitaCount: 0,
  opponents: [{seat:"south",discards:[],melds:[],openMelds:0,kitaCount:0},{seat:"west",discards:[],melds:[],openMelds:0,kitaCount:0}] };
const review: ReviewedFrameEvidence = { digest, source:"external_review", state, riichiStatus:"not_declared",
  ui:{status:"confirmed", actions:[]}, turnContext:"ordinary_draw_confirmed", handEvidence:"confirmed",
  meldEvidence:"confirmed", visibleEvidence:"confirmed_complete" };
const report = { digest, hand:{status:"candidate", value:{safe:true,tiles:[...hand,"E"]}},
  publicTiles:{status:"candidate",value:{observation:{ownDiscards:[], doraIndicators:["1p"], ownMelds:[],
    opponentDiscards:[{seat:"south",discards:[],melds:[]},{seat:"west",discards:[],melds:[]}]}}},
  button:{status:"unresolved",reason:"empty or unrecognized"} } as unknown as Parameters<typeof evaluateSanmaFrameCandidate>[0]["report"];

test("complete same-frame reviewed evidence reaches offline sanma evaluator", () => {
  const result = evaluateSanmaFrameCandidate({frame, report, review});
  assert.equal(result.status, "offline_evaluation");
  if (result.status === "offline_evaluation") assert.ok(result.rows.length > 0);
  assert.equal(result.operationAuthorized, false);
});

test("unknown fields, inconsistent frame, recognition and priority prompt reject", () => {
  const cases = [
    {frame,report},
    {frame:Buffer.from("another frame"),report,review},
    {frame,report,review:{...review,digest:"wrong"}},
    {frame,report,review:{...review,state:{...state,ownKitaCount:undefined}}},
    {frame,report,review:{...review,state:{...state,opponents:[{...state.opponents[0],kitaCount:undefined},state.opponents[1]]}}},
    {frame,report,review:{...review,state:{...state,hand:[...hand.slice(0,12),"W"]}}},
    {frame,report,review:{...review,state:{...state,seat:"south"}}},
    {frame,report,review:{...review,state:{...state,doraIndicators:[]}}},
    {frame,report,review:{...review,ui:{status:"confirmed" as const,actions:["kita" as const]}}},
    {frame,report:{...report,button:{status:"candidate" as const,value:{status:"matched" as const,action:"kita" as const,confidence:1,margin:1}}},review},
    {frame,report:{...report,hand:{status:"unresolved" as const,reason:"unknown"}},review},
  ];
  for (const value of cases) {
    const result = evaluateSanmaFrameCandidate(value);
    assert.equal(result.status, "blocked");
    if (result.status === "blocked") assert.ok(result.reasons.length);
    assert.equal(result.operationAuthorized, false);
  }
});
