import { createHash } from "node:crypto";
import { calculateShanten } from "../game/shanten.js";
import { assertTilesAvailable, tileAvailableInRules, tileFromIndex, TILE_NAMES, toCounts } from "../game/tiles.js";
import type { inspectSanmaFrame } from "./sanmaFrameExperiment.js";

/** Hand-only shanten hypotheses and their physical positions; never a policy. */
export function sanmaStructuralPositions(frame: Buffer, report: Awaited<ReturnType<typeof inspectSanmaFrame>>) {
  const digest = createHash("sha256").update(frame).digest("hex");
  const blocked = (reason: string) => ({status:"blocked" as const, digest, reason,
    candidates:[], operationAuthorized:false as const});
  if (digest !== report.digest) return blocked("frame digest mismatch");
  if (report.hand.status !== "candidate" || report.handGeometry.status !== "candidate") return blocked("hand or geometry unavailable");
  const hand = report.hand.value;
  const geometry = report.handGeometry.value;
  const tiles = hand.tiles;
  const melds = hand.candidateMelds;
  const slots = [...geometry.handSlots, geometry.drawSlot];
  if (melds === undefined || !Number.isInteger(melds) || melds < 0 || melds > 4 || tiles.length !== 14 - 3 * melds)
    return blocked("complete hand length and meld count unavailable");
  if (slots.length !== tiles.length || geometry.clickPoints.length !== tiles.length)
    return blocked("hand and position counts differ");
  try { assertTilesAvailable(tiles, "sanma"); }
  catch { return blocked("recognized hand is invalid for sanma"); }
  // Counts from the recognized hand alone provide a conservative upper
  // bound, not actual live tiles. Rivers, melds and north extracts are unknown.
  const handCounts = toCounts(tiles);
  const candidates = [...new Set(tiles)].map(tile => {
    const remainder = [...tiles];
    remainder.splice(remainder.indexOf(tile), 1);
    const shape = calculateShanten(remainder, melds);
    const improvingDraws = TILE_NAMES.flatMap((_, index) => {
      const draw = tileFromIndex(index);
      if (!tileAvailableInRules(draw, "sanma")) return [];
      const maximumUnseen = 4 - handCounts[index]!;
      if (maximumUnseen <= 0 || calculateShanten([...remainder, draw], melds).shanten >= shape.shanten) return [];
      return [{tile:draw, maximumUnseen}];
    });
    return {tile, shanten:shape.shanten, form:shape.bestForm, improvingDraws,
      maximumUnseenTotal:improvingDraws.reduce((sum, entry) => sum + entry.maximumUnseen, 0),
      positions: tiles.flatMap((observed, index) => observed === tile
        ? [{index, rect:slots[index], point:geometry.clickPoints[index]}] : [])};
  });
  return {status:"blocked" as const, digest, operationAuthorized:false as const, candidates,
    reason:"unverified hand, meld count, turn and action priority; visible tiles and danger unknown",
    assumptions:["recognized tile labels and candidate meld count are correct",
      "draw totals are upper bounds from hand-only counts, not live or observed tile counts"],
    positionCalibrationRequired:geometry.requiresHoldoutValidation};
}
