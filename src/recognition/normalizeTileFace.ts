import sharp from "sharp";

/** Locate the largest bright face inside a crop, excluding thin highlights.
 * Returns the original crop when no credible face exists. This is an
 * axis-aligned correction, not a perspective/rotation estimator.
 */
export async function normalizeTileFace(input: string | Buffer): Promise<Buffer> {
  const { data, info } = await sharp(input).removeAlpha().toColourspace("srgb").raw().toBuffer({ resolveWithObject: true });
  const visited = new Uint8Array(info.width * info.height);
  const queue = new Int32Array(visited.length);
  const bright = (i: number) => Math.min(data[i * 3]!, data[i * 3 + 1]!, data[i * 3 + 2]!) > 135;
  let best: { area: number; left: number; top: number; width: number; height: number } | undefined;
  for (let start = 0; start < visited.length; start++) {
    if (visited[start] || !bright(start)) continue;
    visited[start] = 1;
    let head = 0, tail = 1, area = 0;
    let left = info.width, top = info.height, right = 0, bottom = 0;
    queue[0] = start;
    while (head < tail) {
      const i = queue[head++]!, x = i % info.width, y = Math.floor(i / info.width);
      area++; left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y); bottom = Math.max(bottom, y);
      for (const n of [x ? i - 1 : -1, x + 1 < info.width ? i + 1 : -1, y ? i - info.width : -1, y + 1 < info.height ? i + info.width : -1]) {
        if (n >= 0 && !visited[n] && bright(n)) { visited[n] = 1; queue[tail++] = n; }
      }
    }
    const width = right - left + 1, height = bottom - top + 1;
    if (area < visited.length * 0.18 || width < info.width * 0.4 || height < info.height * 0.4 || area / (width * height) < 0.35) continue;
    if (!best || area > best.area) best = { area, left, top, width, height };
  }
  let pipeline = sharp(input);
  if (best) pipeline = pipeline.extract({ left: best.left, top: best.top, width: best.width, height: best.height });
  return pipeline.png().toBuffer();
}
