import test from "node:test";
import assert from "node:assert/strict";
import { mapSanmaNorthCandidates } from "../src/recognition/sanmaAutoFrameObservation.js";

test("north seat mapping requires an explicit layout and never invents counts", () => {
  const own = {verified:false as const,complete:false as const,matches:[]};
  const opposite = {verified:false as const,complete:false as const,candidate:null};
  const left = {verified:false as const,complete:false as const,candidate:{x:305,y:712}};
  const positions = {own,opposite,left};
  for (const [seat, next, previous] of [["east","south","west"],["south","west","east"],["west","east","south"]] as const) {
    assert.equal(mapSanmaNorthCandidates(seat,positions),undefined);
    const result = mapSanmaNorthCandidates(seat,positions,"opposite-left")!;
    assert.equal(result[seat],own);
    assert.equal(result[next],opposite);
    assert.equal(result[previous],left);
    assert.ok(Object.values(result).every(value => value.complete === false && !("count" in value)));
  }
  assert.equal(mapSanmaNorthCandidates(undefined,positions),undefined);
  assert.equal(mapSanmaNorthCandidates("east",undefined),undefined);
});
