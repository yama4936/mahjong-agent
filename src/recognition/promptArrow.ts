import sharp from "sharp";
import type { Rect } from "./layout.js";

/** Count green prompt-arrow pixels without treating neighboring tile glyphs
 * as arrows. All rectangles must be in screenshot coordinates.
 * This helper is not yet connected to the live highlighted-discard matcher.
 */
export async function countPromptArrowOutsideFaces(
  screenshot: string | Buffer, tile: Rect, faces: readonly Rect[],
): Promise<number> {
  const { width = 0, height = 0 } = await sharp(screenshot).metadata();
  const left = Math.round(tile.x + tile.width / 2) - 20;
  const top = tile.y - 40;
  if (left < 0 || top < 0 || left + 40 > width || top + 30 > height) return 0;
  const pixels = await sharp(screenshot).extract({ left, top, width: 40, height: 30 })
    .toColourspace("srgb").removeAlpha().raw().toBuffer();
  let count = 0;
  for (let y = 0; y < 30; y++) for (let x = 0; x < 40; x++) {
    const screenX = left + x, screenY = top + y;
    if (faces.some(face => screenX >= face.x && screenX < face.x + face.width
      && screenY >= face.y && screenY < face.y + face.height)) continue;
    const i = (y * 40 + x) * 3;
    const r = pixels[i]!, g = pixels[i + 1]!, b = pixels[i + 2]!;
    if (g > 150 && g - r > 40 && g - b > 20) count++;
  }
  return count;
}
