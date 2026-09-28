import sharp from "sharp";
import type { GameTile } from "../game/tiles.js";
import type { PublicTileRegionName } from "./layout.js";
import type { PublicTileRecognitionRegion } from "./publicTileRecognizer.js";

/** Prompt-only evidence: a unique dominant green border on a verified last discard. */
export async function recognizeHighlightedDiscard(
  screenshot: string | Buffer,
  recognition: Partial<Record<PublicTileRegionName, PublicTileRecognitionRegion>>,
  ownSeat: "east" | "south" | "west" | "north" = "east",
): Promise<{ tile: GameTile; fromSeat: "east" | "south" | "west" | "north" } | undefined> {
  const seats = ["east", "south", "west", "north"] as const;
  const names = ["rightDiscards", "oppositeDiscards", "leftDiscards"] as const;
  const { width = 0, height = 0 } = await sharp(screenshot).metadata();
  if (width !== 1920 || height !== 1080) return undefined;
  const evidence: Array<{ count: number; tile: GameTile; fromSeat: typeof seats[number]; last: boolean; safe: boolean }> = [];
  for (const [offset, name] of names.entries()) {
    const region = recognition[name];
    if (!region) continue;
    for (const [index, tile] of region.recognized.entries()) {
      const pad = 6;
      const left = tile.x - pad, top = tile.y - pad;
      const cropWidth = tile.width + pad * 2, cropHeight = tile.height + pad * 2;
      if (left < 0 || top < 0 || left + cropWidth > width || top + cropHeight > height) return undefined;
      const pixels = await sharp(screenshot).extract({ left, top, width: cropWidth, height: cropHeight })
        .toColourspace("srgb").removeAlpha().raw().toBuffer();
      let count = 0;
      for (let y = 0; y < cropHeight; y++) for (let x = 0; x < cropWidth; x++) {
        if (x >= pad && x < pad + tile.width && y >= pad && y < pad + tile.height) continue;
        const i = (y * cropWidth + x) * 3;
        const r = pixels[i]!, g = pixels[i + 1]!, b = pixels[i + 2]!;
        if (g > 150 && g - r > 40 && g - b > 20) count++;
      }
      evidence.push({ count, tile: tile.tile,
        fromSeat: seats[(seats.indexOf(ownSeat) + offset + 1) % 4]!,
        last: index === region.recognized.length - 1,
        safe: region.classificationSafe && tile.safe && tile.gridIndex === index });
    }
  }
  evidence.sort((a, b) => b.count - a.count);
  const best = evidence[0];
  if (!best || !best.safe || !best.last || best.count < 80
    || best.count <= (evidence[1]?.count ?? 0) * 2) return undefined;
  return { tile: best.tile, fromSeat: best.fromSeat };
}
