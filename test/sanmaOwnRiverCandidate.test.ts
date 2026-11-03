import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import sharp from 'sharp';
import {layoutSchema} from '../src/recognition/layout.js';
import {inspectSanmaOwnRiverCandidate} from '../src/recognition/sanmaOwnRiverCandidate.js';
import {recognizeConfiguredPublicTilesWithVit} from '../src/recognition/publicTileRecognizer.js';

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
test('hybrid details follow the accepted retry and never certify the candidate',async()=>{
 const predictions=[
  {tile:'8m' as const,confidence:.6,runnerUpTile:'2m' as const,runnerUpConfidence:.3,selectedBy:'normal' as const,
   normalPrediction:{tile:'8m' as const,label:'8m',confidence:.6,runnerUpLabel:'2m',runnerUpConfidence:.3},
   redPrediction:{label:'x',confidence:.99,runnerUpLabel:'5p-',runnerUpConfidence:.01}},
  {tile:'2m' as const,confidence:.99,runnerUpTile:'8m' as const,runnerUpConfidence:.001,selectedBy:'normal' as const,
   normalPrediction:{tile:'2m' as const,label:'2m',confidence:.99,runnerUpLabel:'8m',runnerUpConfidence:.001},
   redPrediction:{label:'x',confidence:.98,runnerUpLabel:'5s-',runnerUpConfidence:.02}},
 ];
 let calls=0;
 const hybrid={backend:'hybrid' as const,async classifyTileImages(images:Buffer[]){return images.map(()=>predictions[Math.min(calls++,1)]!);}};
 const result=await inspectSanmaOwnRiverCandidate(await frame('after'),layout,hybrid);
 assert.ok(calls>=2);
 assert.equal(result.candidates.length,1);
 assert.equal(result.candidates[0]!.tile,'2m');
 assert.deepEqual(result.candidates[0]!.hybridPrediction,predictions[1]);
 assert.equal(result.candidates[0]!.verified,false);
 assert.equal(result.operationAuthorized,false);
});
test('malformed auxiliary values remain untrusted and JSON nonfinite scores become null',async()=>{
 const hybrid={backend:'hybrid' as const,async classifyTileImages(images:Buffer[]){return images.map(()=>({
  tile:'8p' as const, confidence:.99, runnerUpTile:'2s' as const, runnerUpConfidence:.001, selectedBy:'normal' as const,
  normalPrediction:{tile:'8p' as const,label:'8p',confidence:.99,runnerUpLabel:'invalid',runnerUpConfidence:NaN},
  redPrediction:{label:'invalid',confidence:Infinity,runnerUpLabel:'x',runnerUpConfidence:0},
 }));}};
 const result=await inspectSanmaOwnRiverCandidate(await frame('after'),layout,hybrid);
 const serialized=JSON.parse(JSON.stringify(result));
 assert.equal(serialized.candidates[0].hybridPrediction.normalPrediction.runnerUpConfidence,null);
 assert.equal(serialized.candidates[0].hybridPrediction.redPrediction.confidence,null);
 assert.equal(serialized.candidates[0].hybridPrediction.redPrediction.label,'invalid');
 assert.equal(serialized.candidates[0].verified,false);
 assert.equal(serialized.operationAuthorized,false);
});
test('ordinary public recognition does not expose diagnostic model details',async()=>{
 const hybrid={backend:'hybrid' as const,async classifyTileImages(images:Buffer[]){return images.map(()=>({
  tile:'8p' as const, confidence:.99, runnerUpTile:'2s' as const, runnerUpConfidence:.001, selectedBy:'normal' as const,
  normalPrediction:{tile:'8p' as const,label:'8p',confidence:.99},redPrediction:{label:'x',confidence:.99},
 }));}};
 const result=await recognizeConfiguredPublicTilesWithVit(await frame('after'),layout,hybrid,{sanmaBlueFaces:true});
 assert.ok(result.ownDiscards!.recognized.length);
 assert.equal('ownRiverHybridPrediction' in result.ownDiscards!.recognized[0]!,false);
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

// The labels below were read from retained river-only crops, not generated from
// the recognition receipts. All four images are from one game and are not
// independent samples. A passing result does not certify absence of tiles.
test('real classifier measures detection and labels on a saved sanma river sequence', {
 skip:!((await import('node:fs')).existsSync('.runtime/hybrid-vision/cvmaj-pretrained.tar') && (await import('node:fs')).existsSync('.runtime/hybrid-vision/automajsoul-best-model.pt')),
 timeout:60000,
},async()=>{
 const {HybridTileRecognizer}=await import('../src/recognition/hybridTileRecognizer.js');
 const recognizer=new HybridTileRecognizer();
 const west={tile:'W',x:799,y:571}, one={tile:'1p',x:860,y:571}, nine={tile:'9s',x:922,y:571};
 const cases=[['run116-empty',[]],['run116-west',[west]],['run116-west-1p',[west,one]],['run116-west-1p-9s',[west,one,nine]]] as const;
 try {
  for(const [name,expected] of cases){
   const result=await inspectSanmaOwnRiverCandidate(await frame(name),layout,recognizer);
   const remaining=[...result.candidates]; let missed=0, mislabeled=0;
   for(const target of expected){
    const i=remaining.findIndex(c=>Math.abs(c.x+c.width/2-target.x)<=12 && Math.abs(c.y+c.height/2-target.y)<=15);
    if(i<0){missed++;continue;}
    if(remaining.splice(i,1)[0]!.tile!==target.tile)mislabeled++;
   }
   assert.deepEqual({missed,extra:remaining.length,mislabeled},{missed:0,extra:0,mislabeled:0},name);
   assert.equal(result.verified,false);assert.equal(result.complete,false);assert.equal(result.operationAuthorized,false);
  }
 }finally{await recognizer.close()}
});
