import sharp from "sharp";

export interface FacePoint { x: number; y: number }

/** Corners must follow top-left, top-right, bottom-right, bottom-left order. */
export async function rectifyTileFace(
  screenshot: string | Buffer,
  corners: readonly FacePoint[],
  width = 64,
  height = 96,
): Promise<Buffer> {
  if (corners.length !== 4 || !Number.isInteger(width) || !Number.isInteger(height)
    || width < 2 || height < 2 || width > 512 || height > 512) {
    throw new Error("Invalid tile face dimensions or corners");
  }
  const { data, info } = await sharp(screenshot).toColourspace("srgb").removeAlpha().raw()
    .toBuffer({ resolveWithObject: true });
  if (corners.some(p => !Number.isFinite(p.x) || !Number.isFinite(p.y)
    || p.x < 0 || p.y < 0 || p.x > info.width - 1 || p.y > info.height - 1)) {
    throw new Error("Tile face corner outside image");
  }
  const turns = corners.map((a, i) => {
    const b = corners[(i + 1) % 4]!, c = corners[(i + 2) % 4]!;
    return (b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x);
  });
  if (!turns.every(turn => turn > 1)) throw new Error("Tile face must be a nondegenerate clockwise convex quad");
  // Solve the projective map from a unit rectangle to the source face.
  const unit = [[0, 0], [1, 0], [1, 1], [0, 1]];
  const matrix: number[][] = [];
  for (let i = 0; i < 4; i++) {
    const [u, v] = unit[i]!, { x, y } = corners[i]!;
    matrix.push([u!, v!, 1, 0, 0, 0, -x * u!, -x * v!, x]);
    matrix.push([0, 0, 0, u!, v!, 1, -y * u!, -y * v!, y]);
  }
  for (let column = 0; column < 8; column++) {
    let pivot = column;
    for (let row = column + 1; row < 8; row++) {
      if (Math.abs(matrix[row]![column]!) > Math.abs(matrix[pivot]![column]!)) pivot = row;
    }
    [matrix[column], matrix[pivot]] = [matrix[pivot]!, matrix[column]!];
    const divisor = matrix[column]![column]!;
    if (Math.abs(divisor) < 1e-10) throw new Error("Singular tile face transform");
    for (let j = column; j <= 8; j++) matrix[column]![j]! /= divisor;
    for (let row = 0; row < 8; row++) {
      if (row === column) continue;
      const factor = matrix[row]![column]!;
      for (let j = column; j <= 8; j++) matrix[row]![j]! -= factor * matrix[column]![j]!;
    }
  }
  const h = matrix.map(row => row[8]!);
  const result = Buffer.alloc(width * height * 3);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const u = x / (width - 1), v = y / (height - 1);
    const denominator = h[6]! * u + h[7]! * v + 1;
    if (denominator <= 1e-8) throw new Error("Invalid tile face projection");
    const sx = (h[0]! * u + h[1]! * v + h[2]!) / denominator;
    const sy = (h[3]! * u + h[4]! * v + h[5]!) / denominator;
    if (sx < -1e-6 || sy < -1e-6 || sx > info.width - 1 + 1e-6 || sy > info.height - 1 + 1e-6) {
      throw new Error("Tile face projection outside image");
    }
    const px = Math.max(0, Math.min(info.width - 1, sx));
    const py = Math.max(0, Math.min(info.height - 1, sy));
    const x0 = Math.floor(px), y0 = Math.floor(py);
    const x1 = Math.min(x0 + 1, info.width - 1), y1 = Math.min(y0 + 1, info.height - 1);
    const dx = px - x0, dy = py - y0;
    for (let c = 0; c < 3; c++) {
      const at = (xx: number, yy: number) => data[(yy * info.width + xx) * 3 + c]!;
      result[(y * width + x) * 3 + c] = Math.round(
        at(x0, y0) * (1 - dx) * (1 - dy) + at(x1, y0) * dx * (1 - dy)
        + at(x0, y1) * (1 - dx) * dy + at(x1, y1) * dx * dy);
    }
  }
  return sharp(result, { raw: { width, height, channels: 3 } }).png().toBuffer();
}
