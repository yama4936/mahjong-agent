import { createHash } from 'node:crypto';
import type { ScreenLayout } from './layout.js';
import { recognizeConfiguredPublicTilesWithVit, type PublicVitClassifier } from './publicTileRecognizer.js';

/** Image-position hypotheses only. Empty candidates do not prove an empty river. */
export async function inspectSanmaOwnRiverCandidate(frame: Buffer, layout: ScreenLayout, classifier: PublicVitClassifier) {
  const region = layout.publicTileRegions?.ownDiscards;
  if (!region) throw new Error('own discard region unavailable');
  const result = await recognizeConfiguredPublicTilesWithVit(frame,
    {...layout, publicTileRegions: {ownDiscards: region}}, classifier,
    {sanmaBlueFaces: true, includeOwnRiverHybridPrediction: true});
  if (!result.ownDiscards) throw new Error('own discard recognition unavailable');
  return {scope: 'offline_untrusted_sanma_own_river' as const,
    frameSha256: createHash('sha256').update(frame).digest('hex'), status: 'unknown' as const,
    verified: false as const, complete: false as const, operationAuthorized: false as const,
    candidates: result.ownDiscards.recognized.map(tile => ({tile:tile.tile, x:tile.x, y:tile.y,
      width:tile.width, height:tile.height, confidence:tile.confidence,
      ...(tile.ownRiverHybridPrediction ? {hybridPrediction: tile.ownRiverHybridPrediction} : {}),
      verified:false as const})),
    note: 'Screen-position candidates only; order, seat, tile identity and completeness are unverified.'};
}
