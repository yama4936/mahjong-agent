/** Offline diagnostic: caller labels and match independence are not verified. */
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { layoutSchema } from '../src/recognition/layout.js';
import { inspectSanmaFrame } from '../src/recognition/sanmaFrameExperiment.js';
import { EXPERIMENTAL_BUTTONS, type ExperimentalTemplates } from '../src/recognition/sanmaButtonExperiment.js';
import { fingerprintTemplateDirectory } from '../src/recognition/templateValidator.js';
import { parseGameTile } from '../src/game/tiles.js';

type Row = {image:string; sha256:string; matchId:string; reviewer:string; tiles:string[]; positions:{x:number;y:number}[]};
const digest=(data:Buffer)=>createHash('sha256').update(data).digest('hex');
export function validateRows(input:unknown): Row[] {
  if (!Array.isArray(input) || input.length===0) throw new Error('manifest must contain at least one labeled frame');
  const seen=new Set<string>();
  return input.map((raw):Row=>{
    if(!raw || typeof raw!=='object' || Array.isArray(raw)) throw new Error('invalid labeled frame');
    const r=raw as Record<string,unknown>;
    if(typeof r.image!=='string'||!r.image||typeof r.sha256!=='string'||!/^[0-9a-f]{64}$/.test(r.sha256)||
       typeof r.matchId!=='string'||!r.matchId.trim()||typeof r.reviewer!=='string'||!r.reviewer.trim()||
       !Array.isArray(r.tiles)||!Array.isArray(r.positions)||r.tiles.length<1||r.tiles.length!==r.positions.length)
      throw new Error('image, sha256, matchId, reviewer, labels and positions are required');
    if(seen.has(r.sha256)) throw new Error('duplicate frame digest');
    seen.add(r.sha256);
    const tiles=r.tiles.map(v=>{if(typeof v!=='string')throw new Error('invalid tile');return parseGameTile(v)});
    const positions=r.positions.map(v=>{if(!v||typeof v!=='object')throw new Error('invalid position');const p=v as Record<string,unknown>;
      if(!Number.isInteger(p.x)||!Number.isInteger(p.y))throw new Error('position must contain integer x and y');
      return {x:p.x as number,y:p.y as number};});
    return {image:r.image,sha256:r.sha256,matchId:r.matchId,reviewer:r.reviewer,tiles,positions};
  });
}
export async function evaluate(manifestPath:string, outputPath:string) {
  const manifest=validateRows(JSON.parse(await readFile(manifestPath,'utf8'))), base=path.dirname(path.resolve(manifestPath));
  const layout=layoutSchema.parse(JSON.parse(await readFile('config/layout-runtime.json','utf8')));
  const templates='templates/bootstrap';
  const buttonTemplates=Object.fromEntries(await Promise.all(EXPERIMENTAL_BUTTONS.map(async n=>[n,await readFile(`test/fixtures/sanma-buttons/${n}.png`)]))) as ExperimentalTemplates;
  const rows=[];
  for(const r of manifest){
    const frame=await readFile(path.resolve(base,r.image));
    if(digest(frame)!==r.sha256)throw new Error(`frame digest mismatch: ${r.image}`);
    const report=await inspectSanmaFrame({frame,layout,templates,buttonTemplates,
      publicClassifier:{async classifyTileImages(){throw new Error('not evaluated')}}});
    const hand=report.hand.status==='candidate'?report.hand.value:undefined;
    const geometry=report.handGeometry.status==='candidate'?report.handGeometry.value:undefined;
    const positions=geometry?[...geometry.handSlots,geometry.drawSlot].map(s=>({x:s.x,y:s.y})):undefined;
    rows.push({image:r.image,sha256:r.sha256,matchId:r.matchId,reviewer:r.reviewer,
      expected:{tiles:r.tiles,positions:r.positions}, observed:{status:report.hand.status,tiles:hand?.tiles,positions,
        turnReady:hand?.turnReady,safe:hand?.safe,reason:report.hand.status==='unresolved'?report.hand.reason:undefined},
      exactLabels:hand?JSON.stringify(hand.tiles)===JSON.stringify(r.tiles):false,
      exactPositions:positions?JSON.stringify(positions)===JSON.stringify(r.positions):false});
  }
  const result={scope:'offline_untrusted_sanma_hand_holdout', createdAt:new Date().toISOString(),
    commit:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),templateFingerprint:await fingerprintTemplateDirectory(templates),
    matchIds:[...new Set(manifest.map(r=>r.matchId))],independence:'caller_declared_not_verified',
    operationAuthorized:false,notes:['Labels and match IDs are reviewer assertions.', 'No automatic certification or threshold change.',
      'Correlated frames from one match are not independent matches.', 'Public tiles, buttons, red identity beyond the labeled tiles, and rank performance are not evaluated.'],rows};
  await writeFile(outputPath,JSON.stringify(result,null,2)+'\n',{flag:'wx'});
  return result;
}
if(process.argv[1] && path.resolve(process.argv[1])===path.resolve('scripts/evaluate-sanma-hand-holdout.ts')){
  if(process.argv.length!==4)throw new Error('Usage: tsx scripts/evaluate-sanma-hand-holdout.ts <manifest.json> <new-report.json>');
  await evaluate(process.argv[2]!,process.argv[3]!);
}
