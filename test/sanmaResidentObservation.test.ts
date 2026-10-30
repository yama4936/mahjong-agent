import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { existsSync } from "node:fs";
import {readFile, mkdtemp, writeFile, rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import sharp from "sharp";

const sanma = "artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-05-55-331Z-before.png";
const yonma = "/home/yama1/projects/jantama-auto/artifacts/live/cached-hand-drift-20260928.jpg";
const available = existsSync(sanma) && existsSync(yonma) && existsSync(".runtime/python-auto-venv/bin/python") &&
  existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar") && existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt") &&
  existsSync("templates/bootstrap/1m__hf_base.png");

test("one resident server handles yonma and read-only sanma without mixing execution", {skip:!available,timeout:90000}, async () => {
  const child = spawn(process.execPath,["--import","tsx","src/recognition/recognitionServer.ts",
    "config/layout-runtime.json","templates/bootstrap","examples/public-unknown.json"], {stdio:["pipe","pipe","pipe"],env:{...process.env,TYPESAFE_API_KEY:""}});
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
    assert.equal(observation.result.assembly.status,"blocked");
    assert.equal(observation.result.assembly.operationAuthorized,false);
    assert.equal(observation.result.assembly.partial.seat,"west");
    assert.equal("ownKitaCount" in observation.result.assembly.partial,false);
    assert.equal(observation.result.assembly.evaluation.status,"blocked");
    assert.equal(observation.result.assembly.priority.status,"blocked");
    assert.ok(observation.result.assembly.priority.reasons.includes("complete independent review missing"));
    assert.ok(observation.result.assembly.evaluation.reasons.includes("complete independent review missing"));
    assert.equal(observation.result.report.decision.status,"blocked");
    assert.equal(observation.result.candidates.status,"hypotheses");
    const open = "artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-21-44-430Z-before.png";
    send({id:5,screenshot:open,observeSanma:true});
    const openResponse = await read();
    assert.equal(openResponse.error,undefined);
    assert.equal(openResponse.result.assembly.status,"blocked");
    const row = openResponse.result.assembly.partial.possibleOpenHand;
    assert.equal(row.melds,1);
    assert.equal(row.draw,"N");
    assert.deepEqual(row.concealed,["1p","1p","2p","3p","7p","7p","8p","5s","8s","9s"]);
    assert.equal(row.slotClassificationSafe,false);
    assert.equal(row.verified,false);
    assert.equal(openResponse.result.assembly.priority.status,"blocked");
    assert.equal(openResponse.result.operationAuthorized,false);
    const win = "artifacts/sanma-manual-e48c562-20261031/actions/2026-10-30T16-14-57-162Z-before.png";
    send({id:6,screenshot:win,observeSanma:true});
    const winResponse = await read();
    assert.equal(winResponse.error,undefined);
    assert.equal(winResponse.result.assembly.priority.status,"blocked");
    assert.ok(winResponse.result.candidates.candidates.some((item:any)=>item.action === "tsumo"));
    assert.equal(winResponse.result.operationAuthorized,false);
    // Synthetic composition: only the ron row is from a second four-player
    // game; the underlying screenshot is sanma. This tests routing, not sanma accuracy.
    const directory = await mkdtemp(path.join(tmpdir(), "sanma-ron-routing-"));
    try {
      const image = await sharp(await readFile(sanma)).composite([{input:await readFile("test/fixtures/ron-button-rows/ron2.png"),left:600,top:785}]).png().toBuffer();
      const file = path.join(directory,"frame.png");
      await writeFile(file,image);
      send({id:7,screenshot:file,observeSanma:true});
      const ron = await read();
      assert.equal(ron.error,undefined);
      assert.ok(ron.result.candidates.candidates.some((item:any)=>item.action === "ron"));
      assert.ok(ron.result.candidates.missing.includes("sanma ron reference not independently verified"));
      assert.equal(ron.result.operationAuthorized,false);
      assert.equal(ron.result.assembly.priority.status,"blocked");
    } finally { await rm(directory,{recursive:true,force:true}); }
    send({id:4,screenshot:yonma});
    const after=await read();
    assert.equal(after.id,4);
    assert.equal(after.error,undefined);
    assert.deepEqual(after.result,before.result);
  } finally { child.stdin.end(); child.kill(); }
});
