/** Red-five-sou evidence for an upright 44x64 RGB tile face.
 * The central bamboo is red on the red five and green on the ordinary five.
 * This is color evidence only: callers must independently identify the tile
 * as five sou. Not yet wired into the live matcher.
 */
export function redFiveSouEvidence(rgb: Uint8Array) {
  if (rgb.length !== 44 * 64 * 3) throw new Error("Expected a 44x64 RGB tile face");
  let red = 0;
  let green = 0;
  for (let y = 7; y < 57; y++) {
    for (let x = 17; x < 27; x++) {
      const index = (y * 44 + x) * 3;
      const r = rgb[index]!, g = rgb[index + 1]!, b = rgb[index + 2]!;
      if (r > 90 && r - g > 35 && r - b > 35) red++;
      if (g - r > 30 && g - b > 30) green++;
    }
  }
  return { red, green, supportsRed: red >= 30 && red / (red + green) >= 0.8 };
}
