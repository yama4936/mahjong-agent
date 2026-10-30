import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { existsSync } from "node:fs";

const sanma = "artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-05-55-331Z-before.png";
const yonma = "/home/yama1/projects/jantama-auto/artifacts/live/cached-hand-drift-20260928.jpg";
const available = existsSync(sanma) && existsSync(yonma) && existsSync(".runtime/python-auto-venv/bin/python") &&
  existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar") && existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt") &&
  existsSync("templates/bootstrap/1m__hf_base.png");

test("one resident server handles yonma and read-only sanma without mixing execution", {skip:!available,timeout:90000}, async () => {
  const child = spawn(process.execPath,["--import","tsx","src/recognition/recognitionServer.ts",
    "config/layout.json","templates/bootstrap","examples/public-unknown.json"], {stdio:["pipe","pipe","pipe"],env:{...process.env,TYPESAFE_API_KEY:""}});
  const lines=createInterface({input:child.stdout})[Symbol.asyncIterator]();
  const read=async()=>JSON.parse((await lines.next()).value!);
  const send=(data:unknown)=>child.stdin.write(JSON.stringify(data)+"\n");
  try {
    assert.equal((await read()).ready,true);
    send({id:1,screenshot:yonma});
    const before=await read();
    assert.equal(before.id,1);
    assert.equal(before.error,undefined);
    send({id:2,screenshot:sanma,observeSanma:true,evaluateForceAuto:true});
    const invalid=await read();
    assert.match(invalid.error,/cannot be combined/);
    send({id:3,screenshot:sanma,observeSanma:true});
    const observation=await read();
    assert.equal(observation.id,3);
    assert.equal(observation.error,undefined);
    assert.equal(observation.result.operationAuthorized,false);
    assert.equal(observation.result.report.decision.status,"blocked");
    assert.equal(observation.result.candidates.status,"hypotheses");
    send({id:4,screenshot:yonma});
    const after=await read();
    assert.equal(after.id,4);
    assert.equal(after.error,undefined);
    assert.deepEqual(after.result,before.result);
  } finally { child.stdin.end(); child.kill(); }
});
