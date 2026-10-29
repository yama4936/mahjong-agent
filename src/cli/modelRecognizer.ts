import { VitTileRecognizer } from "../recognition/vitRecognizer.js";
import { HybridTileRecognizer } from "../recognition/hybridTileRecognizer.js";

type ModelRecognizer = VitTileRecognizer | HybridTileRecognizer;

export function modelRecognizer(value: string): ModelRecognizer | undefined {
  if (value === "template") return undefined;
  if (value === "vit") return new VitTileRecognizer();
  if (value === "hybrid") return new HybridTileRecognizer();
  throw new Error(`Invalid recognizer: ${value}; expected template, hybrid, or vit`);
}
