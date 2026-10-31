import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { assembleSanmaEvaluation, evaluateSanmaFrameCandidate, type ReviewedFrameEvidence } from "../src/recognition/sanmaFrameEvaluation.js";

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
    {frame,report:{...report,buttonRow:{status:"candidate" as const,value:{scope:"offline_untrusted_sanma_button_row" as const,
      slots:[{status:"candidate" as const, action:"pon" as const,slot:0,confidence:1}],complete:false as const,operationAuthorized:false as const}}},review},
    {frame,report:{...report,ownMelds:{status:"candidate" as const,value:{status:"unknown" as const,complete:false as const,
      hypotheses:[{type:"pon" as const,tiles:["7p" as const,"7p" as const,"7p" as const],confidence:1}]}}},review},
  ];
  for (const value of cases) {
    const result = evaluateSanmaFrameCandidate(value);
    assert.equal(result.status, "blocked");
    if (result.status === "blocked") assert.ok(result.reasons.length);
    assert.equal(result.operationAuthorized, false);
  }
});


test("reviewed complete river evidence is attached to each candidate without authorizing operation", () => {
  const opponents = [
    {...state.opponents[0], discards:["4p", "N"]},
    {...state.opponents[1], discards:["4p"]},
  ];
  const candidateReport = {...report, publicTiles: {status:"candidate" as const, value:{observation:{
    ownDiscards:[],doraIndicators:["1p"],ownMelds:[],
    opponentDiscards:[{seat:"south",discards:["4p"],melds:[]},{seat:"west",discards:["4p"],melds:[]}],
  }}}} as unknown as typeof report;
  const result = evaluateSanmaFrameCandidate({frame,report:candidateReport,review:{...review,state:{...state,opponents}}});
  assert.equal(result.status,"offline_evaluation");
  if (result.status === "offline_evaluation") {
    const four = result.rows.find(row => row.tile === "4p")!;
    assert.deepEqual(four.byOpponent.map(item=>item.status),["genbutsu_candidate","genbutsu_candidate"]);
    assert.equal(four.allOpponentsGenbutsuCandidate,true);
    const north = result.rows.find(row=>row.tile === "N")!;
    assert.deepEqual(north.byOpponent.map(item=>item.status),["genbutsu_candidate","unknown"]);
    assert.equal(north.allOpponentsGenbutsuCandidate,false);
  }
  assert.equal(result.operationAuthorized,false);
  const missing = evaluateSanmaFrameCandidate({frame,report:candidateReport,review:{...review,state:{...state,opponents:[{...opponents[0],discards:undefined},opponents[1]]}}});
  assert.equal(missing.status,"blocked");
});


test("assembly preserves unknowns and only evaluates with matching explicit review", () => {
  const observation = {digest,report, board:{verified:false,candidate:{seat:"east"}},
    ownSeat:{status:"candidate",value:"east",verified:false},north:{status:"unknown",complete:false,verified:false},
    candidates:{status:"unresolved",candidates:[],missing:[],operationAuthorized:false},operationAuthorized:false} as unknown as Parameters<typeof assembleSanmaEvaluation>[0]["observation"];
  const absent = assembleSanmaEvaluation({frame,observation});
  assert.equal(absent.status,"blocked");
  assert.equal(absent.operationAuthorized,false);
  if ("partial" in absent) {
    assert.equal(absent.partial.seat,"east");
    assert.equal("ownKitaCount" in absent.partial,false);
    assert.equal("ownRiverCandidates" in absent.partial,false);
    assert.equal(absent.evaluation?.status,"blocked");
  }
  const reviewed = assembleSanmaEvaluation({frame,observation,review});
  assert.equal(reviewed.status,"blocked");
  if ("evaluation" in reviewed) assert.equal(reviewed.evaluation?.status,"offline_evaluation");
  assert.equal(reviewed.operationAuthorized,false);
  const disputed = {...observation,north:{...observation.north,positions:{own:{verified:false as const,complete:false as const,matches:[{x:1395,y:775}]},
    left:{verified:false as const,complete:false as const},opposite:{verified:false as const,complete:false as const}}}};
  const conflict = assembleSanmaEvaluation({frame,observation:disputed,review});
  if ("evaluation" in conflict) {
    assert.equal(conflict.evaluation?.status,"blocked");
    if (conflict.evaluation?.status === "blocked") assert.ok(conflict.evaluation.reasons.includes("reviewed zero north count conflicts with visual candidate"));
  }
  const partialOwn = {...disputed,north:{...disputed.north,positions:{...disputed.north.positions,
    own:{verified:false as const,complete:false as const,matches:[],partialObservation:{candidate:{x:1390,y:765},verified:false,complete:false}}}}};
  const partialConflict = assembleSanmaEvaluation({frame,observation:partialOwn,review});
  if ("evaluation" in partialConflict) {
    assert.equal(partialConflict.evaluation?.status,"blocked");
    if (partialConflict.evaluation?.status === "blocked") assert.ok(partialConflict.evaluation.reasons.includes("reviewed zero north count conflicts with visual candidate"));
  }
  const badFrame = assembleSanmaEvaluation({frame:Buffer.from("other"),observation,review});
  assert.equal(badFrame.status,"blocked");
  assert.deepEqual("reasons" in badFrame && badFrame.reasons,["frame evidence digest mismatch"]);
  const otherDigest = {...observation,north:{...observation.north,positions:{own:{verified:false as const,complete:false as const,frame_sha256:"wrong"},
    left:{verified:false as const,complete:false as const},opposite:{verified:false as const,complete:false as const}}}};
  assert.deepEqual((assembleSanmaEvaluation({frame,observation:otherDigest}) as {reasons:string[]}).reasons,["frame evidence digest mismatch"]);
});

test("reviewed same-frame priority, structural and discard safety paths remain read-only", () => {
  const priorityReport = {...report,
    button:{status:"candidate" as const,value:{status:"matched" as const,action:"kita" as const,confidence:1,margin:1}},
    buttonRow:{status:"candidate" as const,value:{scope:"offline_untrusted_sanma_button_row" as const,complete:false as const,operationAuthorized:false as const,
      slots:[{status:"candidate" as const,action:"kita" as const,slot:1,confidence:1},
             {status:"candidate" as const,action:"skip" as const,slot:2,confidence:1}]}}} as unknown as typeof report;
  const priorityReview = {...review,ui:{status:"confirmed" as const,actions:["kita" as const,"pass" as const]}};
  const candidate = evaluateSanmaFrameCandidate({frame,report:priorityReport,review:priorityReview,priorityOnly:true});
  assert.equal(candidate.status,"offline_priority");
  if (candidate.status === "offline_priority") {
    assert.equal(candidate.priority.stage,"action_choice_required");
    assert.ok(candidate.priority.candidates.some(action=>action.action === "kita"));
    assert.ok(candidate.priority.candidates.some(action=>action.action === "discard"));
  }
  assert.equal(candidate.operationAuthorized,false);
  const incomplete = evaluateSanmaFrameCandidate({frame,report:priorityReport,review,priorityOnly:true});
  assert.equal(incomplete.status,"blocked");
  const reaction = evaluateSanmaFrameCandidate({frame,report:priorityReport,
    review:{...priorityReview,ui:{status:"confirmed",actions:["kita","pass","pon"]}},priorityOnly:true});
  assert.equal(reaction.status,"blocked");
  const ordinary = evaluateSanmaFrameCandidate({frame,report,review,priorityOnly:true});
  assert.equal(ordinary.status,"offline_priority");
  if (ordinary.status === "offline_priority") assert.equal(ordinary.priority.stage,"discard_candidate");
  const riichiHand = ["9m","9m","4p","0p","5p","6p","7p","8p","2s","4s","S","S","S"];
  const riichiState = {...state,hand:riichiHand,draw:"5p",scores:{east:35000}};
  const riichiReport = {...report, hand:{status:"candidate" as const,value:{...((report.hand as any).value),tiles:[...riichiHand,"5p"]}},
    button:{status:"candidate" as const,value:{status:"matched" as const,action:"riichi" as const,confidence:1,margin:1}}} as typeof report;
  const riichi = evaluateSanmaFrameCandidate({frame,report:riichiReport,review:{...review,state:riichiState,
    ui:{status:"confirmed",actions:["riichi"]}},priorityOnly:true});
  assert.equal(riichi.status,"offline_priority");
  if (riichi.status === "offline_priority") assert.ok(riichi.priority.riichiDiscards.length);
  const safety = evaluateSanmaFrameCandidate({frame,report,review});
  assert.equal(safety.status,"offline_evaluation");
});

test("reviewed compact hand connects draw and exposed meld to sanma evaluation", () => {
  const compact = ["1p","1p","2p","3p","7p","7p","8p","5s","8s","9s"];
  const openState = {...state,hand:compact,draw:"N",openMelds:1,melds:[{type:"minkan",tiles:["F","F","F","F"]}]};
  const openReport = {...report,hand:{status:"candidate" as const,value:{...((report.hand as any).value),
    safe:false,slotClassificationSafe:true,candidateMelds:1,tiles:[...compact,"N"]}}} as typeof report;
  const openReview = {...review,state:openState};
  const result = evaluateSanmaFrameCandidate({frame,report:openReport,review:openReview});
  assert.equal(result.status,"offline_evaluation");
  if(result.status === "offline_evaluation") {
    assert.ok(result.rows.length > 0);
    assert.ok(result.rows.every(row=>row.effectiveTiles.every(tile=>!(/^[2-8]m$/.test(tile.tile)))));
  }
  assert.equal(result.operationAuthorized,false);
  for (const changed of [
    {...openReview,state:{...openState,draw:"9s"}},
    {...openReview,state:{...openState,openMelds:0}},
    {...openReview,state:{...openState,melds:[]}},
    {...openReview,state:{...openState,ownKitaCount:undefined}},
  ]) assert.equal(evaluateSanmaFrameCandidate({frame,report:openReport,review:changed}).status,"blocked");
  const unknownRow = {...openReport,hand:{...openReport.hand,value:{...(openReport.hand as any).value,slotClassificationSafe:false}}} as typeof report;
  assert.equal(evaluateSanmaFrameCandidate({frame,report:unknownRow,review:openReview}).status,"blocked");
});

test("post-riichi priority binds only the physical draw and refuses unknown prompts", () => {
  const closed = ["1p","2p","3p","4p","5p","6p","1s","2s","3s","4s","5s","W","W"];
  const riichiState = {...state,hand:closed,draw:"9s",riichiDeclared:true};
  const riichiReport = {...report,hand:{status:"candidate" as const,value:{...((report.hand as any).value),tiles:[...closed,"9s"]}}} as typeof report;
  const riichiReview = {...review,state:riichiState,riichiStatus:"declared" as const};
  const result = evaluateSanmaFrameCandidate({frame,report:riichiReport,review:riichiReview,priorityOnly:true});
  assert.equal(result.status,"offline_priority");
  if(result.status === "offline_priority") {
    assert.equal(result.priority.stage,"draw_discard_candidate");
    assert.deepEqual(result.priority.candidates,[{action:"discard",tile:"9s",physicalPosition:"draw"}]);
  }
  assert.equal(result.operationAuthorized,false);
  for(const broken of [
    {...riichiReview,state:{...riichiState,draw:undefined}},
    {...riichiReview,handEvidence:undefined} as unknown as typeof riichiReview,
    {...riichiReview,turnContext:undefined} as unknown as typeof riichiReview,
    {...riichiReview,state:{...riichiState,riichiDeclared:false}},
    {...riichiReview,ui:{status:"confirmed" as const,actions:["kita" as const]}},
    {...riichiReview,ui:{status:"confirmed" as const,actions:["kan" as const]}},
    {...riichiReview,ui:{status:"confirmed" as const,actions:["tsumo" as const]}},
  ]) assert.equal(evaluateSanmaFrameCandidate({frame,report:riichiReport,review:broken,priorityOnly:true}).status,"blocked");
  assert.equal(evaluateSanmaFrameCandidate({frame,report:riichiReport,review:riichiReview}).status,"blocked");
  const wonReport = {...riichiReport,hand:{status:"candidate" as const,value:{...((riichiReport.hand as any).value),tiles:[...closed,"6s"]}},
    button:{status:"candidate" as const,value:{status:"matched" as const,action:"tsumo" as const,confidence:1,margin:1}}} as typeof report;
  const win = evaluateSanmaFrameCandidate({frame,report:wonReport,review:{...riichiReview,state:{...riichiState,draw:"6s"},
    ui:{status:"confirmed",actions:["tsumo"]}},priorityOnly:true});
  assert.equal(win.status,"offline_priority");
  if(win.status === "offline_priority") assert.equal(win.priority.stage,"win_candidate");
});
