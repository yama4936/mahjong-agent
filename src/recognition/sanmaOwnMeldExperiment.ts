import sharp from "sharp";
import type { ScreenLayout } from "./layout.js";
import { recognizeConfiguredPublicTilesWithVit, recognizeExposedMelds,
  type PublicVitClassifier, type RecognizedMeld } from "./publicTileRecognizer.js";

/** Research output only. The hypothesized melds do not certify state. */
type Result = { status: "unknown"; complete: false; hypotheses: RecognizedMeld[]; reason?: string };

/**
 * The fixed 1920x1080 sanma sample has a seven-tile exposed row extending
 * beyond the yonma own-meld crop. The x=1240 boundary overlaps a possible
 * concealed hand, so the caller must independently establish an inclusive
 * right edge of every concealed tile including a raised tile or drawn tile.
 * This function does not verify that assertion, the screen, or coverage.
 */
export async function sanmaOwnMeldExperiment(screenshot: string | Buffer, layout: ScreenLayout,
  classifier: PublicVitClassifier, assumedHandRightEdge: number | undefined): Promise<Result> {
  const unknown: Result = { status: "unknown", complete: false, hypotheses: [] };
  const metadata = await sharp(screenshot).metadata();
  if (metadata.width !== 1920 || metadata.height !== 1080 || layout.viewport.width !== 1920
      || layout.viewport.height !== 1080 || !layout.publicTileRegions?.ownMelds) {
    return { ...unknown, reason: "uncalibrated" };
  }
  if (!Number.isInteger(assumedHandRightEdge) || assumedHandRightEdge! < 0 || assumedHandRightEdge! > 1920) {
    return { ...unknown, reason: "hand_extent_unknown" };
  }
  if (assumedHandRightEdge! > 1220) return { ...unknown, reason: "hand_overlaps_extended_region" };
  const region = layout.publicTileRegions.ownMelds;
  // Restrict to the one observed calibration. Do not adjust arbitrary layouts.
  if (region.x !== 1560 || region.y !== 930 || region.width !== 290 || region.height !== 135
      || region.rotationToUpright !== 0) return { ...unknown, reason: "uncalibrated" };
  const isolated = { ...layout, publicTileRegions: { ownMelds: { ...region, x: 1240, width: 610 } } };
  const recognized = await recognizeConfiguredPublicTilesWithVit(screenshot, isolated, classifier);
  const detected = recognized.ownMelds;
  const hypotheses = recognizeExposedMelds(detected);
  if (!detected?.classificationSafe || detected.candidateCount === 0
      || detected.candidateCount !== detected.recognized.length
      || hypotheses.some(meld => meld.type === "chi")
      || hypotheses.reduce((sum, meld) => sum + meld.tiles.length, 0) !== detected.candidateCount) {
    return { ...unknown, reason: "incomplete_or_uncertain" };
  }
  return { ...unknown, hypotheses };
}
