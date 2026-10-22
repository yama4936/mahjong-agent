import sharp from 'sharp';

export interface RedManNumeralEvidence {
  redPixels: number;
  otherInkPixels: number;
  redFraction: number;
}

/** Confirm upper-numeral red ink separately from the red 萬 suit glyph.
 * The returned monochrome numeral is only an input to family recognition;
 * it does not identify a five or establish a meld by itself.
 */
export async function normalizeRedManNumeral(input: Buffer): Promise<{
  image: Buffer; evidence: RedManNumeralEvidence;
} | undefined> {
  const canonical = await sharp(input).resize(44, 64, { fit: 'fill' })
    .removeAlpha().toColourspace('srgb').raw().toBuffer();
  let redPixels = 0, otherInkPixels = 0;
  for (let y = 7; y < 36; y++) for (let x = 5; x < 39; x++) {
    const i = (y * 44 + x) * 3;
    const r = canonical[i]!, g = canonical[i + 1]!, b = canonical[i + 2]!;
    if (r > 90 && r - g > 35 && r - b > 35) redPixels++;
    else if (Math.max(r, g, b) < 150 || g - r > 30 || g - b > 30) otherInkPixels++;
  }
  const redFraction = redPixels / Math.max(1, redPixels + otherInkPixels);
  if (redPixels < 30 || redFraction < 0.8) return undefined;
  const { data, info } = await sharp(input).removeAlpha().toColourspace('srgb').raw().toBuffer({ resolveWithObject: true });
  for (let y = 0; y < Math.floor(info.height / 2); y++) for (let x = 0; x < info.width; x++) {
    const i = (y * info.width + x) * 3;
    const r = data[i]!, g = data[i + 1]!, b = data[i + 2]!;
    if (r > 90 && r - g > 35 && r - b > 35) data[i] = data[i + 1] = data[i + 2] = Math.min(g, b);
  }
  return { image: await sharp(data, { raw: { width: info.width, height: info.height, channels: 3 } }).png().toBuffer(),
    evidence: { redPixels, otherInkPixels, redFraction } };
}
