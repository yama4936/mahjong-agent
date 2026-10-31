import { createHash } from 'node:crypto';
import type { ScreenLayout } from './layout.js';
import { recognizeConfiguredPublicTilesWithVit, type PublicVitClassifier } from './publicTileRecognizer.js';

/** Diagnostic image-position candidates; no seat, completeness or legal-state inference. */
export async function inspectSanmaRightRiverCandidate(frame:Buffer, layout:ScreenLayout, classifier:PublicVitClassifier) {
  const region=layout.publicTileRegions?.rightDiscards;
  if(!region) throw new Error('right discard region unavailable');
  const result=await recognizeConfiguredPublicTilesWithVit(frame,{...layout,publicTileRegions:{rightDiscards:region}},classifier,{sanmaBlueFaces:true});
  const observed=result.rightDiscards;
  if(!observed) throw new Error('right discard recognition unavailable');
  return {scope:'offline_untrusted_sanma_right_river' as const,frameSha256:createHash('sha256').update(frame).digest('hex'),
    status:'unknown' as const, verified:false as const, complete:false as const, operationAuthorized:false as const,
    candidates:observed.recognized.map(tile=>({tile:tile.tile,x:tile.x,y:tile.y,width:tile.width,height:tile.height,
      confidence:tile.confidence,verified:false as const})),
    note:'Image-position candidates only; seat, tile availability, order and completeness are unverified.'};
}

/** The left physical river, without a claim about wind or recognition completeness. */
export async function inspectSanmaLeftRiverCandidate(frame:Buffer, layout:ScreenLayout, classifier:PublicVitClassifier) {
  const region=layout.publicTileRegions?.leftDiscards;
  if(!region) throw new Error('left discard region unavailable');
  const result=await recognizeConfiguredPublicTilesWithVit(frame,{...layout,publicTileRegions:{leftDiscards:region}},classifier,{sanmaBlueFaces:true});
  const observed=result.leftDiscards;
  if(!observed) throw new Error('left discard recognition unavailable');
  return {scope:'offline_untrusted_sanma_left_river' as const,frameSha256:createHash('sha256').update(frame).digest('hex'),
    status:'unknown' as const, verified:false as const, complete:false as const, operationAuthorized:false as const,
    candidates:observed.recognized.map(tile=>({tile:tile.tile,x:tile.x,y:tile.y,width:tile.width,height:tile.height,
      confidence:tile.confidence,verified:false as const})),
    note:'Image-position candidates only; seat, tile availability, order and completeness are unverified.'};
}
