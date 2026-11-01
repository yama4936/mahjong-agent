import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import sharp from 'sharp';
import {layoutSchema} from '../src/recognition/layout.js';
import {inspectSanmaOwnRiverCandidate} from '../src/recognition/sanmaOwnRiverCandidate.js';

const layout = layoutSchema.parse(JSON.parse(await readFile('config/layout-runtime.json','utf8')));
const classifier = {async classifyTileImages(images:Buffer[]) {return images.map(() => ({tile:'8p' as const, confidence:.99,runnerUpTile:'2s' as const,runnerUpConfidence:.001}));}};
async function frame(name:string) {
 const crop=await readFile(`test/fixtures/sanma-own-river-portable/${name}.png`);
 return sharp({create:{width:1920,height:1080,channels:3,background:'black'}}).composite([{input:crop,left:750,top:535}]).png().toBuffer();
}
test('own river observations remain unknown and bind to the input bytes',async()=>{
 for(const [name,count] of [['before',0],['after',1]] as const){
  const bytes=await frame(name), result=await inspectSanmaOwnRiverCandidate(bytes,layout,classifier);
  assert.equal(result.candidates.length,count);
  assert.equal(result.frameSha256,createHash('sha256').update(bytes).digest('hex'));
  assert.equal(result.status,'unknown');assert.equal(result.verified,false);assert.equal(result.complete,false);assert.equal(result.operationAuthorized,false);
  assert.ok(result.candidates.every(x=>x.verified===false));
 }
});
test('image and recognizer errors cannot become an empty candidate',async()=>{
 await assert.rejects(inspectSanmaOwnRiverCandidate(Buffer.from('broken'),layout,classifier));
 const broken={async classifyTileImages():Promise<never>{throw new Error('classifier unavailable')}};
 await assert.rejects(inspectSanmaOwnRiverCandidate(await frame('after'),layout,broken));
 await assert.rejects(inspectSanmaOwnRiverCandidate(await frame('after'),{...layout,publicTileRegions:{}},classifier));
});
test('same tile appearing twice, moving, or disappearing never proves action',async()=>{
 const empty=await frame('before'), full=await frame('after');
 const tile=await sharp(full).extract({left:766,top:540,width:66,height:85}).png().toBuffer();
 const blank=await sharp(empty).extract({left:766,top:540,width:66,height:85}).png().toBuffer();
 const repeated=await sharp(full).composite([{input:tile,left:832,top:540}]).png().toBuffer();
 const moved=await sharp(repeated).composite([{input:blank,left:766,top:540}]).png().toBuffer();
 const [a,b,c]=await Promise.all([inspectSanmaOwnRiverCandidate(repeated,layout,classifier), inspectSanmaOwnRiverCandidate(moved,layout,classifier), inspectSanmaOwnRiverCandidate(empty,layout,classifier)] as const);
 assert.equal(a.candidates.length,2);assert.equal(b.candidates.length,1);assert.equal(c.candidates.length,0);
 for(const item of [a,b,c]) {assert.equal(item.verified,false);assert.equal(item.complete,false);assert.equal(item.operationAuthorized,false);}
});
test('real classifier observes saved 8p only as an unverified candidate', {skip:!((await import('node:fs')).existsSync('.runtime/hybrid-vision/cvmaj-pretrained.tar') && (await import('node:fs')).existsSync('.runtime/hybrid-vision/automajsoul-best-model.pt')),timeout:60000},async()=>{
 const {HybridTileRecognizer}=await import('../src/recognition/hybridTileRecognizer.js');const h=new HybridTileRecognizer();
 try {const result=await inspectSanmaOwnRiverCandidate(await frame('after'),layout,h);assert.deepEqual(result.candidates.map(x=>x.tile),['8p']);assert.equal(result.verified,false);assert.equal(result.complete,false);assert.equal(result.operationAuthorized,false)}finally{await h.close()}
});
