import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
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
