import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { evaluateDiscards } from "../src/game/ukeire.js";
import { sanmaStructuralPositions } from "../src/recognition/sanmaStructuralPositions.js";

const frame = Buffer.from("frame");
const tiles = ["1m","9m","9m","4p","0p","5p","6p","8p","2s","6s","S","S","N","E"];
const report = {
  digest:createHash("sha256").update(frame).digest("hex"),
  hand:{status:"candidate",value:{tiles,candidateMelds:0}},
  handGeometry:{status:"candidate",value:{handSlots:tiles.slice(0,-1).map((_,i)=>({x:i,y:0,width:1,height:1})),
    drawSlot:{x:13,y:0,width:1,height:1},clickPoints:tiles.map((_,i)=>({x:i,y:0})),requiresHoldoutValidation:true}}
} as any;

test("hand-only shapes bind all same-tile slots without guessing visible tile counts",()=>{
  const result = sanmaStructuralPositions(frame,report);
  assert.equal(result.operationAuthorized,false);
  assert.equal(result.status,"blocked");
  const pair = result.candidates.find(row=>row.tile==="9m")!;
  assert.deepEqual(pair.positions.map(p=>p.index),[1,2]);
  assert.equal("ukeire" in pair,false);
  assert.match(result.reason,/visible tiles and danger unknown/);
});

test("mismatched frame, impossible hand and missing geometry are blocked",()=>{
  assert.match(sanmaStructuralPositions(Buffer.from("different"),report).reason,/digest/);
  const impossible = {...report,hand:{...report.hand,value:{...report.hand.value,tiles:["2m",...tiles.slice(1)]}}};
  assert.match(sanmaStructuralPositions(frame,impossible).reason,/invalid/);
  assert.match(sanmaStructuralPositions(frame,{...report,handGeometry:{status:"unresolved"}}).reason,/unavailable/);
  const short = {...report,handGeometry:{...report.handGeometry,value:{...report.handGeometry.value,clickPoints:[]}}};
  assert.match(sanmaStructuralPositions(frame,short).reason,/counts differ/);
});


test("unknown visible tiles produce upper bounds, never an assumed live count",()=>{
  const result = sanmaStructuralPositions(frame,report);
  for (const visible of [[],["1p","1s","F"],["N","N","4p"]]) {
    const exact = evaluateDiscards(tiles,visible,0,"sanma");
    for (const row of result.candidates) {
      const complete = exact.find(entry=>entry.tile===row.tile)!;
      assert.equal(row.shanten,complete.shanten);
      assert.ok(row.maximumUnseenTotal >= complete.ukeire);
      assert.ok(row.improvingDraws.every(draw=>!(/^[2-8]m$/.test(draw.tile))));
      for (const draw of complete.effectiveTiles) {
        const bound = row.improvingDraws.find(entry=>entry.tile===draw.tile);
        assert.ok(bound && bound.maximumUnseen>=draw.remaining);
      }
    }
  }
  assert.ok("assumptions" in result && result.assumptions.some(item=>item.includes("upper bounds")));
  assert.equal(result.operationAuthorized,false);
});

test("observed river candidates tighten only a conditional upper bound",()=>{
  const observed = ["1p","1s","F"];
  const publicTiles={status:"candidate",value:{observation:{doraIndicators:["1p"],ownDiscards:["1s"],
    opponentDiscards:[{discards:["F"]},{discards:[]}]}}};
  const result=sanmaStructuralPositions(frame,{...report,publicTiles});
  assert.ok("conditionalPublicEvidence" in result);
  if (!("conditionalPublicEvidence" in result) || !result.conditionalPublicEvidence) throw new Error("missing evidence");
  assert.equal(result.conditionalPublicEvidence.verified,false);
  assert.equal(result.conditionalPublicEvidence.complete,false);
  const complete=evaluateDiscards(tiles,observed,0,"sanma");
  for(const row of result.candidates){
    const exact=complete.find(item=>item.tile===row.tile)!;
    assert.equal(row.maximumUnseenTotalIfObservedTilesCorrect,exact.ukeire);
    assert.ok(row.maximumUnseenTotalIfObservedTilesCorrect! <= row.maximumUnseenTotal);
  }
  assert.equal(result.operationAuthorized,false);
});

test("contradictory or absent public candidates do not tighten the bound",()=>{
  const missing=sanmaStructuralPositions(frame,report);
  assert.ok(!("conditionalPublicEvidence" in missing));
  const publicTiles={status:"candidate",value:{observation:{doraIndicators:["9m","9m","9m"],ownDiscards:[],opponentDiscards:[]}}};
  const contradiction=sanmaStructuralPositions(frame,{...report,publicTiles});
  assert.ok("conditionalPublicEvidence" in contradiction);
  if (!("conditionalPublicEvidence" in contradiction) || !contradiction.conditionalPublicEvidence) throw new Error("missing conflict");
  assert.equal(contradiction.conditionalPublicEvidence.reason,"hand and observed public candidates conflict");
  assert.deepEqual(contradiction.candidates.map(row=>row.maximumUnseenTotal),missing.candidates.map(row=>row.maximumUnseenTotal));
  assert.ok(contradiction.candidates.every(row=>!("maximumUnseenTotalIfObservedTilesCorrect" in row)));
});
