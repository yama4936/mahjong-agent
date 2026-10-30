import { assertTilesAvailable, normalizeTile, parseGameTile, toCounts } from "./tiles.js";

/** Manual or separately recognized observations; none of these fields are certified. */
export type KitaObservation = {
  frameSha256: string;
  atMs: number;
  roundId: string;
  hand: readonly string[];
  drawn: string;
  meldCount: number;
  ownKitaCount: number;
  wallRemaining: number;
};

/**
 * Offline consistency check, not a receipt: verifies a hypothesized north
 * extraction and replacement draw with explicit inputs. It does not prove the
 * button was clicked, the labels are correct, or that the images are current.
 */
export function inspectKitaTransition(before: KitaObservation, after: KitaObservation, clickAtMs: number) {
  const failed: string[] = [];
  try {
    for (const o of [before, after]) {
      if (!o || !/^[0-9a-f]{64}$/.test(o.frameSha256) || !Number.isSafeInteger(o.atMs)
          || !o.roundId || !Array.isArray(o.hand) || !Number.isInteger(o.meldCount) || o.meldCount < 0 || o.meldCount > 4
          || !Number.isInteger(o.ownKitaCount) || o.ownKitaCount < 0 || o.ownKitaCount > 4
          || !Number.isInteger(o.wallRemaining) || o.wallRemaining < 0
          || o.hand.length !== 14 - 3 * o.meldCount) throw new Error("invalid observation");
      const tiles = o.hand.map(parseGameTile);
      const draw = parseGameTile(o.drawn);
      assertTilesAvailable(tiles, "sanma");
      toCounts(tiles);
      if (!tiles.includes(draw) || tiles.filter(t => normalizeTile(t) === "N").length + o.ownKitaCount > 4) throw new Error("physically inconsistent observation");
    }
    if (!Number.isSafeInteger(clickAtMs) || before.atMs >= clickAtMs || clickAtMs >= after.atMs || before.frameSha256 === after.frameSha256) failed.push("frame order or identity");
    if (before.roundId !== after.roundId || before.meldCount !== after.meldCount) failed.push("round or meld changed");
    if (after.ownKitaCount !== before.ownKitaCount + 1) failed.push("extracted north count");
    if (after.wallRemaining !== before.wallRemaining - 1) failed.push("remaining wall count");
    const expected = before.hand.map(parseGameTile);
    const index = expected.indexOf("N");
    if (index < 0) failed.push("no north in prior hand");
    else {
      expected.splice(index, 1);
      expected.push(parseGameTile(after.drawn));
      if (expected.sort().join(",") !== after.hand.map(parseGameTile).sort().join(",")) failed.push("hand transition");
    }
  } catch { failed.push("invalid observation"); }
  return { status: failed.length ? "unresolved" as const : "consistent_candidate" as const, failed,
    scope: "offline_untrusted" as const, operationAuthorized: false as const };
}
